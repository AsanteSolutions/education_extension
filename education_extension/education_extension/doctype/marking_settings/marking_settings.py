# Copyright (c) 2026, Asante Solutions and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

# How a class can be listed. Institutions differ on this — a surname roll is
# conventional on a mark sheet, but some work from a student number — so it is a
# setting rather than a decision baked into the grid.
BY_LAST_NAME = "Last Name"
BY_FIRST_NAME = "First Name"
BY_STUDENT_NAME = "Student Name"
BY_STUDENT_NUMBER = "Student Number"
BY_STUDENT_ID = "Student ID"

# The Student field each option sorts on. Student ID is the docname itself.
SORT_FIELD = {
	BY_LAST_NAME: "last_name",
	BY_FIRST_NAME: "first_name",
	BY_STUDENT_NAME: "student_name",
	BY_STUDENT_NUMBER: "custom_student_number",
	BY_STUDENT_ID: "name",
}


class MarkingSettings(Document):
	pass


def get_student_order():
	"""The configured order, falling back to surname if nothing is set yet."""
	return frappe.db.get_single_value("Marking Settings", "student_order") or BY_LAST_NAME


def order_students(students, order=None):
	"""Put a list of student ids into the configured order.

	Sorting happens here rather than in SQL so every caller orders a class the
	same way, and so a student missing the field being sorted on falls to the end
	by name instead of disappearing into an arbitrary position.
	"""
	if not students:
		return []

	order = order or get_student_order()
	field = SORT_FIELD.get(order, SORT_FIELD[BY_LAST_NAME])

	if field == "name":
		return sorted(students)

	values = {
		row.name: row.get(field)
		for row in frappe.get_all(
			"Student",
			fields=["name", field],
			filters={"name": ["in", list(students)]},
			limit_page_length=0,
		)
	}

	def key(student):
		value = (values.get(student) or "").strip()
		# Anyone without the field sorts after everyone who has it, rather than
		# ahead of them on an empty string.
		return (not value, value.casefold(), student)

	return sorted(students, key=key)
