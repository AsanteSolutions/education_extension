# Copyright (c) 2026, Asante Solutions and contributors
# For license information, please see license.txt

"""What QA reads when checking a course's marks and writing its comments.

A standard, file-based twin of the Assessment Result Report that has been used
until now, differing in where the marks come from: that report carries its own
copy of the weightings and the course-code exception lists, while this one asks
marking.py, the same calculation the portal and the printed report use. Swapping
to it is what stops a fourth copy of the rules drifting from the other three.

The columns follow the course's mark scheme rather than a fixed set of eight, so
a course examined on a theory paper alone shows five columns instead of eight
with dashes in three of them.
"""

import frappe
from frappe import _

from education_extension.education_extension.marking import course_marks


def execute(filters=None):
	filters = frappe._dict(filters or {})
	if not (filters.course and filters.academic_year and filters.academic_term):
		return columns_for([]), []

	marks = course_marks(filters.course, filters.academic_year, filters.academic_term)
	return columns_for(marks["criteria"]), rows_for(marks)


def columns_for(criteria):
	"""Assessment columns come from the scheme, in the order it lists them — so
	reordering the scheme reorders the report."""
	coursework = [row for row in criteria if row.component == "Coursework"]
	examination = [row for row in criteria if row.component != "Coursework"]

	columns = [
		{"fieldname": "student", "label": _("Student Number"), "fieldtype": "Link", "options": "Student", "width": 130},
		{"fieldname": "student_name", "label": _("Student Name"), "fieldtype": "Data", "width": 220},
	]
	columns += [_assessment_column(row) for row in coursework]
	columns.append({"fieldname": "dp", "label": _("Semester Mark"), "fieldtype": "Data", "width": 120})
	columns += [_assessment_column(row) for row in examination]
	columns += [
		{"fieldname": "final_mark", "label": _("Final Mark"), "fieldtype": "Data", "width": 100},
		{"fieldname": "supplementary", "label": _("Supplementary Mark"), "fieldtype": "Data", "width": 150},
		{"fieldname": "remark", "label": _("Remark"), "fieldtype": "Data", "width": 90},
		{"fieldname": "action", "label": _("Action"), "fieldtype": "Data", "width": 80},
		{"fieldname": "supp_remark", "label": _("Supp Remark"), "fieldtype": "Data", "width": 110},
		{"fieldname": "supp_action", "label": _("Supp Action"), "fieldtype": "Data", "width": 100},
	]
	return columns


def _assessment_column(row):
	# Keyed on the assessment group itself, so a course with an assessment no
	# other course has still gets its own column.
	return {
		"fieldname": frappe.scrub(row.assessment_group),
		"label": _(row.assessment_group),
		"fieldtype": "Data",
		"width": 110,
	}


def rows_for(marks):
	rows = []
	for row in marks["rows"]:
		out = {
			"student": row["student"],
			"student_name": row["student_name"],
			"dp": row["dp"],
			"final_mark": row["final_mark"],
			"supplementary": row["supplementary"],
			"remark": row["remark"],
			# The client script turns these into the links that open the comment
			# editor; the report itself only says which student a row belongs to.
			"action": "edit",
			"supp_remark": row["supp_remark"],
			"supp_action": "edit",
		}
		for group, score in row["scores"].items():
			out[frappe.scrub(group)] = score
		rows.append(out)
	return rows
