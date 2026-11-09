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


# How a student is named where a class is listed. A mark sheet is read down the
# surname column, so the roll is conventionally "Mthembu, Nolwazi Khanyisa" --
# but the name as it was captured is what a lecturer recognises on a screen, and
# institutions differ, so it is a setting rather than a decision baked into the
# grid. Order and naming are separate questions: this one changes only what is
# shown, and nothing has to be regenerated for it.
SURNAME_FIRST = "Surname First"
AS_RECORDED = "As Recorded"


def get_student_name_display():
	"""The configured naming, falling back to surname first if nothing is set."""
	return (
		frappe.db.get_single_value("Marking Settings", "student_name_display") or SURNAME_FIRST
	)


def display_names(students, display=None):
	"""What to call each student, as {id: name}, in the configured form.

	One home for this. The entry grid, the QA review, the Course Results report
	and the printed mark sheet all name the same class, and they had already
	drifted: the QA review read "Mthembu, Nolwazi" while the grid beside it read
	"Nolwazi Khanyisa Bongiwe Mthembu".

	Built from the name fields rather than by splitting the full name. The stored
	name is "Nolwazi Khanyisa Bongiwe Mthembu" and no rule about spaces tells
	you which of those words is the surname.
	"""
	if not students:
		return {}

	# Deduplicated, because a sheet hands this one entry per student per
	# assessment -- 560 rows on a course of seventy -- and that is the IN list.
	students = list(dict.fromkeys(students))
	display = display or get_student_name_display()
	names = {}

	for row in frappe.get_all(
		"Student",
		fields=["name", "student_name", "first_name", "middle_name", "last_name"],
		filters={"name": ["in", students]},
		limit_page_length=0,
	):
		names[row.name] = _display_name(row, display)

	# A sheet can carry marks for a student the Student doctype no longer has, so
	# the id stands in for the name rather than the row coming back without one.
	for student in students:
		names.setdefault(student, student)

	return names


def _display_name(row, display):
	"""One student's name. Surname, a comma, then the given names -- or the name
	as recorded, which is also the fallback where either half is missing: a
	"Mthembu, " or a ", Nolwazi" is worse than the name somebody typed in."""
	recorded = _words(row.student_name) or row.name
	if display == AS_RECORDED:
		return recorded

	surname = _words(row.last_name)
	# The middle name joins the first, because the comma separates the surname
	# from everything else and not the first name from the rest.
	given = _words(f"{row.first_name or ''} {row.middle_name or ''}")

	return f"{surname}, {given}" if surname and given else recorded


def _words(value):
	"""Whitespace squeezed out. Captured names carry stray spaces -- one student
	is recorded with middle_name "Unathi ", which is why the name stored on them
	reads "Siyabonga Unathi  Dube"."""
	return " ".join((value or "").split())
