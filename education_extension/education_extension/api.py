# Copyright (c) 2026, Asante Solutions and contributors
# For license information, please see license.txt

"""Portal API adapters for the education_extension student portal.

The upstream `education` app refactored its portal API (e.g. it removed
`get_student_info` in favour of `get_student_profile` / `get_program_context`).
Our compiled portal frontend still expects the older payloads, so we provide
compatible endpoints here and point the frontend at them, insulating the portal
from further churn in the education app.
"""

import frappe

# Student fields the portal reads (ProfileModal, headers, report dialog, etc.).
PORTAL_STUDENT_FIELDS = [
	"name",
	"student_name",
	"image",
	"student_email_id",
	"student_mobile_number",
	"joining_date",
	"date_of_birth",
	"blood_group",
	"gender",
	"nationality",
	# The address the profile panel has always tried to show. It read these six
	# fields and this list sent none of them, so "Address:" rendered empty for
	# everyone, and the payment dialog's country prefill was never filled in.
	# A student's own address, sent to that student: the same footing as the
	# date of birth and mobile number already here.
	"address_line_1",
	"address_line_2",
	"city",
	"state",
	"pincode",
	"country",
]


def _current_user_student():
	"""The Student record linked to the logged-in user, if any.

	This is how the portal decides who it is talking to: `my_options`, `register`
	and `get_student_grades` all take their student from here rather than from the
	caller, so everything a student may see or do rests on this one lookup.

	Which is why it refuses to choose. `Student.user` carries no unique
	constraint and the education app's controller only ever sets the field, so
	nothing upstream stops two students sharing an account — and the lookup this
	replaced had no ordering either, so it answered with whichever row the
	database felt like and could answer differently on the next call. A student
	shown another student's marks, or registered against the wrong record, is
	worse in every way than being told to go to the office.

	`student_permissions.on_student_validate` stops the pair being made in the
	first place. This is for the pair that got in before it, or around it.
	"""
	user = frappe.session.user
	if user in ("Guest", "Administrator"):
		return None

	students = frappe.get_all(
		"Student", filters={"user": user}, pluck="name", order_by="creation asc", limit=2
	)
	if len(students) > 1:
		frappe.throw(
			frappe._(
				"Your account is linked to more than one student record, so this page "
				"cannot tell which one is yours. The academic office needs to put that "
				"right before you can continue."
			)
		)

	return students[0] if students else None


def _student_groups(student, program):
	"""Student groups the student belongs to for the given program, shaped as
	[{"label": <group name>}] — the form the portal's schedule call expects."""
	if not student or not program:
		return []
	sg = frappe.qb.DocType("Student Group")
	sgs = frappe.qb.DocType("Student Group Student")
	return (
		frappe.qb.from_(sg)
		.inner_join(sgs)
		.on(sg.name == sgs.parent)
		.select(sgs.parent.as_("label"))
		.where(sgs.student == student)
		.where(sg.program == program)
		.run(as_dict=1)
	)


@frappe.whitelist()
def get_student_info():
	"""Portal bootstrap for the logged-in student: a flat Student dict plus
	`current_program` and `student_groups`. Reproduces the education app's old
	`get_student_info` payload, which the portal store still relies on."""
	student = _current_user_student()
	if not student:
		return None

	info = frappe.db.get_value("Student", student, PORTAL_STUDENT_FIELDS, as_dict=True)
	if not info:
		return None

	# get_current_enrollment is a stable helper still exported by the education
	# app; it returns the current Program Enrollment (with `program`) or None.
	from education.education.api import get_current_enrollment

	enrollment = get_current_enrollment(student) or {}
	info["current_program"] = enrollment
	info["student_groups"] = _student_groups(student, enrollment.get("program"))
	return info
