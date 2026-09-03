# Copyright (c) 2026, Asante Solutions and contributors
# For license information, please see license.txt

"""Who has registered for a term, and who has not.

With no approval step, this is the whole of staff visibility into what students
did — so it is built around the question a registrar actually asks, which is who
still needs chasing, not who succeeded.

It also surfaces the cases the resolution job refused to decide: a provisional
registration whose prerequisite failed after the window closed, or after work had
already been recorded against the module. Those are left standing deliberately
and need a person, and a comment on a submitted enrolment is not a queue.
"""

import frappe
from frappe import _

from education_extension.education_extension.registration import (
	programs_by_block,
	term_ordinal,
)
from education_extension.education_extension.doctype.student_progress_report.student_progress_report import (
	_program_semester,
	_semester_label,
)

REGISTERED = "Registered"
NOT_REGISTERED = "Not registered"
NOT_THIS_TERM = "Not their term"


def execute(filters=None):
	filters = frappe._dict(filters or {})
	if not filters.academic_term:
		frappe.throw(_("Select an academic term."))

	return columns(), rows(filters)


def columns():
	return [
		{"label": _("Student"), "fieldname": "student", "fieldtype": "Link", "options": "Student", "width": 110},
		{"label": _("Name"), "fieldname": "student_name", "fieldtype": "Data", "width": 200},
		{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 120},
		{"label": _("Due to Take"), "fieldname": "expected", "fieldtype": "Data", "width": 160},
		{"label": _("Registered For"), "fieldname": "programs", "fieldtype": "Data", "width": 200},
		{"label": _("Modules"), "fieldname": "modules", "fieldtype": "Int", "width": 90},
		{"label": _("Provisional"), "fieldname": "provisional", "fieldtype": "Int", "width": 100},
		{"label": _("Needs Review"), "fieldname": "needs_review", "fieldtype": "Int", "width": 110},
		{"label": _("Registered On"), "fieldname": "registered_on", "fieldtype": "Date", "width": 120},
		{"label": _("Enrolment"), "fieldname": "enrollment", "fieldtype": "Link", "options": "Program Enrollment", "width": 150},
	]


def rows(filters):
	term = filters.academic_term
	ordinal = term_ordinal(term)
	offered = programs_by_block()
	furthest = furthest_block_before(term)
	this_term = registrations_for(term)

	students = frappe.get_all(
		"Student",
		filters={"name": ["in", list(set(furthest) | set(this_term))]} if (furthest or this_term) else {"name": ""},
		fields=["name", "student_name"],
		order_by="name asc",
	)

	out = []
	for student in students:
		registered = this_term.get(student.name)
		expected = expected_block(furthest.get(student.name, 0), ordinal, offered)

		if registered:
			status = REGISTERED
		elif expected is None:
			status = NOT_THIS_TERM
		else:
			status = NOT_REGISTERED

		if filters.status and filters.status != status:
			continue
		if filters.program and (not registered or filters.program not in registered["programs"]):
			continue

		out.append(
			{
				"student": student.name,
				"student_name": student.student_name,
				"status": status,
				# Only shown for a student who has not registered, which is the only
				# one it answers a question about. It is derived from enrolment
				# history, and on a site adopted mid-programme that history is thin
				# enough that putting a guess beside the programme someone actually
				# registered for would read as a contradiction.
				"expected": _semester_label(expected) if expected and not registered else "",
				"programs": ", ".join(sorted(registered["programs"])) if registered else "",
				"modules": registered["modules"] if registered else 0,
				"provisional": registered["provisional"] if registered else 0,
				"needs_review": registered["needs_review"] if registered else 0,
				"registered_on": registered["registered_on"] if registered else None,
				"enrollment": registered["enrollment"] if registered else None,
			}
		)

	# Whoever needs attention first: unregistered students, then the flagged
	# cases, then everyone else.
	order = {NOT_REGISTERED: 0, REGISTERED: 1, NOT_THIS_TERM: 2}
	out.sort(key=lambda row: (order[row["status"]], -row["needs_review"], row["student"]))
	return out


def expected_block(furthest, ordinal, offered):
	"""The block this student is due to take in a term, or None.

	Mirrors `registration.next_block`, but off a batched highest-block lookup
	rather than a query per student — the report covers the whole cohort.
	"""
	if not offered:
		return None
	candidate = furthest + 1
	if candidate > max(offered):
		return None
	if ordinal in (1, 2) and candidate % 2 != (1 if ordinal == 1 else 0):
		return None
	return candidate


def furthest_block_before(term):
	"""student -> furthest block enrolled in *before* this term.

	Enrolments for the term itself are excluded, or a student who has already
	registered would look like they had moved a block further on than they have.
	"""
	start = frappe.db.get_value("Academic Term", term, "term_start_date")
	enrollments = frappe.get_all(
		"Program Enrollment",
		filters={"docstatus": 1, "academic_term": ["!=", term]},
		fields=["student", "program", "academic_term"],
	)

	starts = {
		row.name: row.term_start_date
		for row in frappe.get_all("Academic Term", fields=["name", "term_start_date"])
	}

	furthest = {}
	for row in enrollments:
		if start and starts.get(row.academic_term) and starts[row.academic_term] >= start:
			continue
		block = _program_semester(row.program)
		if block is None:
			continue
		if block > furthest.get(row.student, 0):
			furthest[row.student] = block
	return furthest


def registrations_for(term):
	"""student -> what they registered for in this term."""
	enrollments = frappe.get_all(
		"Program Enrollment",
		filters={"academic_term": term, "docstatus": 1},
		fields=["name", "student", "program", "enrollment_date"],
	)
	if not enrollments:
		return {}

	counts = {}
	for row in frappe.get_all(
		"Program Enrollment Course",
		filters={
			"parent": ["in", [e.name for e in enrollments]],
			"parenttype": "Program Enrollment",
		},
		fields=["parent", "custom_provisional", "custom_needs_review"],
	):
		tally = counts.setdefault(row.parent, {"modules": 0, "provisional": 0, "needs_review": 0})
		tally["modules"] += 1
		tally["provisional"] += 1 if row.custom_provisional else 0
		tally["needs_review"] += 1 if row.custom_needs_review else 0

	registrations = {}
	for row in enrollments:
		tally = counts.get(row.name, {"modules": 0, "provisional": 0, "needs_review": 0})
		# A carry-over produces a second enrolment in the same term, so the row is
		# the student rather than the document: counts add up and the link points
		# at the first of them.
		entry = registrations.setdefault(
			row.student,
			{
				"programs": set(),
				"modules": 0,
				"provisional": 0,
				"needs_review": 0,
				"registered_on": row.enrollment_date,
				"enrollment": row.name,
			},
		)
		entry["programs"].add(row.program)
		entry["modules"] += tally["modules"]
		entry["provisional"] += tally["provisional"]
		entry["needs_review"] += tally["needs_review"]
		if row.enrollment_date and (
			not entry["registered_on"] or row.enrollment_date < entry["registered_on"]
		):
			entry["registered_on"] = row.enrollment_date

	return registrations
