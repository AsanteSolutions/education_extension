# Copyright (c) 2026, Asante Solutions and contributors
# For license information, please see license.txt

"""Who is registered for one module.

`Registration Status` answers the other question — it walks the cohort and
reports where each student stands, a row per student. This one starts from the
module: pick it and get the roll, which is what a lecturer is handed at the
start of a semester and what a registrar needs when a module is moved,
cancelled or over-subscribed.

Students come back in the order marking uses, so this list and the mark sheet
for the same module read the same way down the page.
"""

import frappe
from frappe import _

from education_extension.education_extension.doctype.marking_settings.marking_settings import (
	order_students,
)
from education_extension.education_extension.doctype.student_progress_report.student_progress_report import (
	_program_semester,
	_semester_label,
)


def execute(filters=None):
	filters = frappe._dict(filters or {})
	if not filters.course:
		frappe.throw(_("Select a module."))

	return columns(), rows(filters)


def columns():
	return [
		{"label": _("Student"), "fieldname": "student", "fieldtype": "Link", "options": "Student", "width": 110},
		{"label": _("Name"), "fieldname": "student_name", "fieldtype": "Data", "width": 220},
		{"label": _("Programme"), "fieldname": "program", "fieldtype": "Link", "options": "Program", "width": 220},
		{"label": _("Semester"), "fieldname": "semester", "fieldtype": "Data", "width": 120},
		{"label": _("Provisional"), "fieldname": "provisional", "fieldtype": "Check", "width": 90},
		{"label": _("Waiting On"), "fieldname": "waiting_on", "fieldtype": "Data", "width": 140},
		{"label": _("Needs Review"), "fieldname": "needs_review", "fieldtype": "Check", "width": 110},
		{"label": _("Term"), "fieldname": "academic_term", "fieldtype": "Link", "options": "Academic Term", "width": 170},
		{"label": _("Registered On"), "fieldname": "registered_on", "fieldtype": "Date", "width": 120},
		{"label": _("Enrolment"), "fieldname": "enrollment", "fieldtype": "Link", "options": "Program Enrollment", "width": 150},
	]


def rows(filters):
	enrollments = {
		row.name: row
		for row in frappe.get_all(
			"Program Enrollment",
			filters=_enrollment_filters(filters),
			fields=[
				"name",
				"student",
				"student_name",
				"program",
				"academic_term",
				"enrollment_date",
			],
			limit_page_length=0,
		)
	}
	if not enrollments:
		return []

	# The child rows carry whether the module was taken provisionally, which is
	# the part of this a registrar acts on.
	taken = frappe.get_all(
		"Program Enrollment Course",
		filters={
			"parent": ["in", list(enrollments)],
			"parenttype": "Program Enrollment",
			"course": filters.course,
		},
		fields=["parent", "custom_provisional", "custom_provisional_on", "custom_needs_review"],
		limit_page_length=0,
	)
	if not taken:
		return []

	out = []
	for row in taken:
		enrollment = enrollments[row.parent]
		block = _program_semester(enrollment.program)
		out.append(
			{
				"student": enrollment.student,
				"student_name": enrollment.student_name,
				"program": enrollment.program,
				"semester": _semester_label(block) if block else "",
				"provisional": 1 if row.custom_provisional else 0,
				"waiting_on": row.custom_provisional_on or "",
				"needs_review": 1 if row.custom_needs_review else 0,
				"academic_term": enrollment.academic_term,
				"registered_on": enrollment.enrollment_date,
				"enrollment": enrollment.name,
			}
		)

	return _in_marking_order(out)


def _enrollment_filters(filters):
	"""Submitted enrolments only — a draft is not a registration."""
	conditions = {"docstatus": 1}
	if filters.academic_term:
		conditions["academic_term"] = filters.academic_term
	if filters.program:
		conditions["program"] = filters.program
	return conditions


def _in_marking_order(out):
	"""The order the mark sheet for this module uses.

	A register and a mark sheet for the same module are read side by side, and
	two different orderings of the same people is the kind of difference someone
	spends a while checking before concluding it means nothing.

	A student registered twice in one term — a carry-over alongside their own
	semester — appears once per enrolment, so the ordering is applied to the
	students and the rows are laid out under it.
	"""
	by_student = {}
	for row in out:
		by_student.setdefault(row["student"], []).append(row)

	ordered = []
	for student in order_students(list(by_student)):
		ordered.extend(by_student[student])

	# Anything order_students did not return, rather than dropping it.
	returned = {row["student"] for row in ordered}
	for student in sorted(by_student):
		if student not in returned:
			ordered.extend(by_student[student])

	return ordered
