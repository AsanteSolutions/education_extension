# Copyright (c) 2026, Asante Solutions and contributors
# For license information, please see license.txt

"""Mirroring between the education records and the LMS.

These were six Server Scripts on `before_insert` and `before_delete`, which put
the mirror on the critical path of the thing being mirrored: anything they threw
took the original write down with it. Between them that blocked registration
three separate ways, and none of it could be worked around from the app, because
`LMS Enrollment.validate` refuses a member without an LMS admin role and no
permission flag skips a validation.

So the mirror moved off the request. Each binding is now a queued job, and the
job runs as a service user holding `Moderator` — the role the LMS actually asks
for. Registration itself needs no elevated rights at all as a result.

Two consequences worth being clear about. The mirror is eventually consistent: a
student is registered before the LMS knows about it, and if the job fails they
are registered anyway. That is the right way round — a mirror should never be
the reason a registration fails — but it does mean failures land in the Error
Log rather than in front of anyone, so the jobs are written to be idempotent and
safe to re-run.

Everything here checks that what it needs exists before touching it. The LMS is
a separate app that a site may not have installed, the records these bindings
point at are created independently, and a mirror that throws because its
counterpart is missing is the whole problem being fixed.
"""

from contextlib import contextmanager

import frappe

# A service account rather than Administrator: `LMS Enrollment.is_admin` is a
# role check, not an identity check, so the mirror needs exactly one LMS role and
# nothing else. The domain is a reserved TLD that can never resolve, so this can
# never be mistaken for a person's address or receive mail.
SERVICE_USER = "lms-sync@education-extension.invalid"
SERVICE_ROLE = "Moderator"


def lms_installed():
	"""Whether this site has the LMS at all."""
	return bool(frappe.db.exists("DocType", "LMS Enrollment"))


def course_slug(course):
	"""The LMS course name the education course maps to.

	Kept exactly as the original scripts derived it, so existing links still
	resolve.
	"""
	slug = course.replace("&", "-").replace(")", "").replace("(", "")
	return slug.replace(" - ", "-").replace(" ", "-").lower()


@contextmanager
def as_service_user():
	"""Run a block as the mirroring service user.

	Safe in a worker, where the session is synthetic. Restores everything
	`frappe.set_user` clears anyway, so calling one of these jobs inline — from a
	console or a test — cannot leave the caller's session broken: `set_user`
	overwrites `session.sid` with the username and blanks `session.data`, which
	inside a request logs the user out.
	"""
	session = frappe.local.session
	was = (session.user, session.sid, session.data, frappe.local.form_dict)

	frappe.set_user(SERVICE_USER)
	try:
		yield
	finally:
		frappe.set_user(was[0])
		session.sid, session.data, frappe.local.form_dict = was[1], was[2], was[3]


def service_user_ready():
	"""Whether the account the jobs run as exists and still holds its role."""
	if not frappe.db.exists("User", SERVICE_USER):
		return False
	return SERVICE_ROLE in frappe.get_roles(SERVICE_USER)


def enqueue(method, **kwargs):
	"""Queue a mirroring job, after the transaction that triggered it commits.

	Nothing is queued if there is no LMS to mirror into, or no service user to
	run as — there is no point filling a queue with jobs that cannot work.
	"""
	if not (lms_installed() and service_user_ready()):
		return

	frappe.enqueue(
		"education_extension.education_extension.lms_sync." + method,
		queue="short",
		enqueue_after_commit=True,
		**kwargs,
	)


# ---------------------------------------------------------------------------
# Document hooks. These only queue; the work is below.
# ---------------------------------------------------------------------------


def on_program_enrollment(doc, method=None):
	enqueue("add_program_member", program=doc.program, student=doc.student)


def on_program_enrollment_trash(doc, method=None):
	# Read now rather than in the job: by the time it runs the enrolment is gone.
	enqueue("remove_program_member", program=doc.program, student=doc.student)


def on_course_enrollment(doc, method=None):
	enqueue("add_course_enrollment", course=doc.course, student=doc.student)


def on_course_enrollment_trash(doc, method=None):
	enqueue("remove_course_enrollment", course=doc.course, student=doc.student)


def on_lms_program(doc, method=None):
	enqueue("create_program_from_lms", lms_program=doc.name)


def on_lms_course(doc, method=None):
	enqueue("create_course_from_lms", lms_course=doc.name)


# ---------------------------------------------------------------------------
# The jobs
# ---------------------------------------------------------------------------


def student_login(student):
	"""The User a student signs in as.

	`user`, not `student_email_id`: the LMS links members by User, and the two
	differ for a fair number of students here — which is what stopped 22 of them
	registering at all.
	"""
	return frappe.db.get_value("Student", student, "user")


def add_program_member(program, student):
	"""Put the student into the matching LMS programme."""
	member = student_login(student)
	if not (member and frappe.db.exists("LMS Program", program)):
		return

	if frappe.db.exists("LMS Program Member", {"parent": program, "member": member}):
		return

	with as_service_user():
		lms_program = frappe.get_doc("LMS Program", program)
		lms_program.append("program_members", {"member": member})
		lms_program.save(ignore_permissions=True)


def remove_program_member(program, student):
	"""Take the student out of the matching LMS programme."""
	member = student_login(student)
	if not (member and frappe.db.exists("LMS Program", program)):
		return

	with as_service_user():
		lms_program = frappe.get_doc("LMS Program", program)
		remaining = [row for row in lms_program.program_members if row.member != member]
		if len(remaining) == len(lms_program.program_members):
			return
		lms_program.program_members = remaining
		lms_program.save(ignore_permissions=True)


def add_course_enrollment(course, student):
	"""Enrol the student in the matching LMS course."""
	member = student_login(student)
	slug = course_slug(course)
	if not (member and frappe.db.exists("LMS Course", slug)):
		return

	if frappe.db.exists("LMS Enrollment", {"course": slug, "member": member}):
		return

	with as_service_user():
		frappe.get_doc(
			{"doctype": "LMS Enrollment", "course": slug, "member": member}
		).insert(ignore_permissions=True)


def remove_course_enrollment(course, student):
	"""Withdraw the student from the matching LMS course."""
	member = student_login(student)
	slug = course_slug(course)
	if not member:
		return

	names = frappe.get_all(
		"LMS Enrollment", filters={"course": slug, "member": member}, pluck="name"
	)
	if not names:
		return

	with as_service_user():
		for name in names:
			frappe.delete_doc("LMS Enrollment", name, ignore_permissions=True, force=True)


def create_program_from_lms(lms_program):
	"""Create the education programme for a new LMS programme."""
	if not (frappe.db.exists("LMS Program", lms_program) and frappe.db.exists("DocType", "Program")):
		return

	source = frappe.get_doc("LMS Program", lms_program)
	if frappe.db.exists("Program", source.title):
		return

	with as_service_user():
		program = frappe.new_doc("Program")
		program.program_name = source.title
		for row in source.program_courses:
			# Only courses that exist: a Program Course row is a Link, and one
			# pointing at nothing would fail validation and lose the whole
			# programme rather than one row of it.
			if frappe.db.exists("Course", row.course_title):
				program.append("courses", {"course": row.course_title, "required": 1})
		program.flags.ignore_permissions = True
		program.insert()


def create_course_from_lms(lms_course):
	"""Create the education course for a new LMS course."""
	if not (frappe.db.exists("LMS Course", lms_course) and frappe.db.exists("DocType", "Course")):
		return

	source = frappe.get_doc("LMS Course", lms_course)
	# Course is named after its title, so an existing one of the same name is the
	# same course; creating it again would only raise a duplicate.
	if frappe.db.exists("Course", source.title):
		return

	with as_service_user():
		course = frappe.new_doc("Course")
		course.course_name = source.title
		course.description = source.description
		course.flags.ignore_permissions = True
		course.insert()
