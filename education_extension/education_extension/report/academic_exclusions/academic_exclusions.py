# Copyright (c) 2026, Asante Solutions and contributors
# For license information, please see license.txt

"""Who the academic standing rule is stopping, and what has been done about it.

The Registration Status report carries a Standing column, but it is a column on
a list of everybody — fine for noticing in passing, useless for working through.
A student the rule has barred is a case that needs a decision, and a queue of
decisions deserves a page of its own, with the figures the decision rests on
beside each name rather than a doctype away.

It lists the students already permitted as well as those still barred, because
"who has been let through, by whom, and why" is the other half of the same
question — and the half an auditor asks.
"""

import frappe
from frappe import _

from education_extension.education_extension.academic_standing import (
	ALLOWED_ANYWAY,
	CANNOT_REGISTER,
	label,
	rule,
	standing_for,
)
from education_extension.education_extension.doctype.student_progress_report.student_progress_report import (
	_semester_label,
)
from education_extension.education_extension.registration import (
	REMARK_SOURCES,
	programs_by_block,
	term_ordinal,
)
from education_extension.education_extension.report.registration_status import (
	registration_status as status,
)

RULE_IS_OFF = _(
	"No academic standing rule is switched on, so nobody is excluded. Turn it on "
	"in Registration Settings, where the thresholds are."
)


def execute(filters=None):
	filters = frappe._dict(filters or {})
	if not filters.academic_term:
		frappe.throw(_("Select an academic term."))

	# Said out loud rather than shown as an empty table. Nothing excluded and no
	# rule to exclude anybody read exactly the same way otherwise, and they are
	# very different things to report to a registrar.
	if not rule():
		return columns(), [], RULE_IS_OFF

	return columns(), rows(filters)


def columns():
	return [
		{"label": _("Student"), "fieldname": "student", "fieldtype": "Link", "options": "Student", "width": 110},
		{"label": _("Name"), "fieldname": "student_name", "fieldtype": "Data", "width": 190},
		{"label": _("Standing"), "fieldname": "standing", "fieldtype": "Data", "width": 130},
		{"label": _("Failed"), "fieldname": "failed", "fieldtype": "Int", "width": 70},
		{"label": _("Taken"), "fieldname": "attempted", "fieldtype": "Int", "width": 70},
		{"label": _("Rate"), "fieldname": "rate", "fieldtype": "Percent", "width": 80},
		{"label": _("Counted Over"), "fieldname": "counted_over", "fieldtype": "Data", "width": 180},
		{"label": _("Modules Failed"), "fieldname": "failed_modules", "fieldtype": "Data", "width": 220},
		{"label": _("Due to Take"), "fieldname": "expected", "fieldtype": "Data", "width": 130},
		{"label": _("Registered"), "fieldname": "registered", "fieldtype": "Data", "width": 100},
		{"label": _("Permission"), "fieldname": "override", "fieldtype": "Link", "options": "Registration Override", "width": 175},
		{"label": _("Granted By"), "fieldname": "granted_by", "fieldtype": "Link", "options": "User", "width": 160},
		{"label": _("Reason"), "fieldname": "reason", "fieldtype": "Data", "width": 300},
	]


def rows(filters):
	term = filters.academic_term
	students = students_with_results()
	if not students:
		return []

	standings = standing_for(students, term)
	granted = grants_for(students, term)

	# Only the students the rule has something to say about. Everyone else is on
	# the Registration Status report, which is where "how is everybody doing" is
	# asked; this one is a queue.
	excluded = {
		student: assessed for student, assessed in standings.items() if assessed["excluded"]
	}
	if not excluded:
		return []

	details = {
		row.name: row
		for row in frappe.get_all(
			"Student", filters={"name": ["in", list(excluded)]}, fields=["name", "student_name"]
		)
	}
	registered = status.registrations_for(term)
	furthest = status.furthest_block_before(term)
	# The same source the other report uses, so the two cannot disagree about
	# what a student is due to take.
	offered = programs_by_block()
	ordinal = term_ordinal(term)

	out = []
	for student, assessed in excluded.items():
		standing_label = label(assessed)
		if filters.standing and filters.standing != standing_label:
			continue

		permission = granted.get(student) or frappe._dict()
		block = status.expected_block(furthest.get(student, 0), ordinal, offered)

		out.append(
			{
				"student": student,
				"student_name": (details.get(student) or frappe._dict()).student_name,
				"standing": standing_label,
				"failed": assessed["failed"],
				"attempted": assessed["attempted"],
				"rate": assessed["rate"],
				# Named per student, not taken from the setting: the window lands on
				# the latest period each student has results in, so two students can
				# be judged over different semesters under the same rule.
				"counted_over": assessed["window"] or _("Whole record"),
				"failed_modules": ", ".join(assessed["failed_modules"]),
				# Whether the exclusion bites this term at all. A student with no
				# semester due is not being kept out of anything.
				"expected": _semester_label(block) if block else _("Nothing this term"),
				"registered": _("Yes") if student in registered else _("No"),
				"override": permission.get("name"),
				"granted_by": permission.get("granted_by"),
				"reason": permission.get("reason"),
			}
		)

	# Still barred first, then whoever has failed the most of what they took --
	# the order a registrar would work down it in.
	out.sort(key=lambda row: (row["standing"] != CANNOT_REGISTER, -row["rate"], row["student"]))
	return out


def students_with_results():
	"""Every student with a submitted remark on record.

	The population the rule can judge. Asking it of every Student would put
	applicants and long-graduated students on a list about registering for the
	term ahead, and the rule has nothing to say about a record that is empty.
	"""
	students = set()
	for doctype, _field in REMARK_SOURCES:
		students.update(frappe.get_all(doctype, filters={"docstatus": 1}, pluck="student"))
	students.discard(None)
	return sorted(students)


def grants_for(students, academic_term):
	"""student -> the permission in force for this term, with who granted it."""
	if not students:
		return {}

	return {
		row.student: row
		for row in frappe.get_all(
			"Registration Override",
			filters={
				"student": ["in", list(students)],
				"academic_term": academic_term,
				"docstatus": 1,
			},
			fields=["name", "student", "granted_by", "reason"],
			order_by="creation asc",
		)
	}
