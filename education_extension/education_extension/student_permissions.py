# Copyright (c) 2026, Asante Solutions and contributors
# For license information, please see license.txt

"""Confine a student to their own records.

Without this a logged-in student can list every other student — name, ID number,
SAVC number, date of birth, contact details — and every assessment result on the
site. Role permissions cannot express "only your own": they are per doctype, not
per row.

A User Permission can. It constrains only the doctypes that carry a Link to
Student, so a student sees their own results, enrolments, attendance, fees and
consent, and nothing changes for records that have no student on them at all —
the LMS courses and enrolments, the curriculum, the academic calendar.

Deliberately not `if_owner`: most of these records are created by staff, so their
owner is a staff member and the student would see none of their own.
"""

import frappe

# Anyone holding one of these needs to see across students to do their job, so
# they are never confined even if a Student record points at them. A user who is
# both would otherwise lose their staff view the moment this ran.
STAFF_ROLES = frozenset(
	{"System Manager", "Education Manager", "Academics User", "Instructor", "Moderator"}
)


def is_staff(user):
	return bool(STAFF_ROLES & set(frappe.get_roles(user)))


def existing_permission(user, student):
	"""A permission that actually confines this user, not merely one that exists.

	`apply_to_all_doctypes` is the whole point of the one `confine` creates. A
	narrow permission -- one left `applicable_for` a single doctype, which is how
	Frappe's own UI offers to create them -- restricts that doctype and nothing
	else, Student itself included. Counting it as the confinement already being
	in place is how a student kept a full list of every other student while this
	reported "already".
	"""
	return frappe.db.exists(
		"User Permission",
		{
			"user": user,
			"allow": "Student",
			"for_value": student,
			"apply_to_all_doctypes": 1,
		},
	)


def confine(student, user):
	"""Give this user a User Permission for this student, if it is safe to.

	Returns what happened, so the patch can report rather than guess.
	"""
	if not user:
		return "no user"
	if is_staff(user):
		return "staff"
	if existing_permission(user, student):
		return "already"

	permission = frappe.new_doc("User Permission")
	permission.update(
		{
			"user": user,
			"allow": "Student",
			"for_value": student,
			# Every doctype that links to Student, which is the point: naming them
			# individually would go stale the moment one is added.
			"apply_to_all_doctypes": 1,
		}
	)
	permission.flags.ignore_permissions = True
	permission.insert()
	return "created"


def release(student, user=None):
	"""Drop the confinement, for a student whose user has changed or gone."""
	filters = {"allow": "Student", "for_value": student}
	if user:
		filters["user"] = user
	for name in frappe.get_all("User Permission", filters=filters, pluck="name"):
		frappe.delete_doc("User Permission", name, ignore_permissions=True, force=True)


def on_student_validate(doc, method=None):
	"""One portal account, one student.

	Nothing upstream enforces it: `Student.user` carries no unique constraint and
	no index, and the education app's controller only ever sets the field. But
	the link is read backwards to decide who a logged-in user *is* — by the
	registration page, the grades page and the confinement in this module — and
	two students on one account makes all three a guess.

	Checked only where the link is being set or changed, so a site that already
	holds such a pair can still edit both records while somebody sorts them out.
	Refusing to save them would make the problem harder to fix than to keep.
	"""
	if not doc.user:
		return

	before = doc.get_doc_before_save()
	if before and before.user == doc.user:
		return

	other = frappe.db.get_value(
		"Student", {"user": doc.user, "name": ["!=", doc.name or ""]}, "name"
	)
	if not other:
		return

	frappe.throw(
		frappe._(
			"{0} is already the portal account of {1}. One account cannot stand for two "
			"students: the registration and grades pages read it to decide whose records "
			"to show."
		).format(frappe.bold(doc.user), frappe.utils.get_link_to_form("Student", other))
	)


def on_student_insert(doc, method=None):
	confine(doc.name, doc.user)


def on_student_update(doc, method=None):
	"""Follow a change of user, so the permission never points at the wrong one.

	A student whose portal account is replaced would otherwise keep the old
	account's access and get none of their own.
	"""
	before = doc.get_doc_before_save()
	if before and before.user == doc.user:
		return

	if before and before.user:
		release(doc.name, before.user)
	confine(doc.name, doc.user)


def on_student_trash(doc, method=None):
	release(doc.name)
