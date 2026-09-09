# Copyright (c) 2026, Asante Solutions and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from education_extension.education_extension.doctype.marking_settings.marking_settings import (
	BY_FIRST_NAME,
	BY_LAST_NAME,
	BY_STUDENT_ID,
	SORT_FIELD,
	get_student_order,
	order_students,
)


class TestMarkingSettings(FrappeTestCase):
	def test_every_option_sorts_on_a_real_student_field(self):
		"""An option with no field behind it would silently fall back to surname."""
		options = frappe.get_meta("Marking Settings").get_field("student_order").options.split("\n")
		self.assertEqual(set(options), set(SORT_FIELD))

		student_fields = {df.fieldname for df in frappe.get_meta("Student").fields}
		student_fields.add("name")
		for option, fieldname in SORT_FIELD.items():
			with self.subTest(option=option):
				self.assertIn(fieldname, student_fields)

	def test_nothing_to_order_is_not_an_error(self):
		self.assertEqual(order_students([]), [])
		self.assertEqual(order_students(None), [])

	def test_student_id_order_needs_no_lookup(self):
		self.assertEqual(
			order_students(["20240010", "20220001", "20230005"], BY_STUDENT_ID),
			["20220001", "20230005", "20240010"],
		)

	def test_an_unknown_option_falls_back_to_surname(self):
		students = self._students(4)
		self.assertEqual(order_students(students, "Nonsense"), order_students(students, BY_LAST_NAME))

	def test_surname_order_is_alphabetical_and_case_blind(self):
		students = self._students(12)
		ordered = order_students(students, BY_LAST_NAME)
		surnames = [
			(frappe.db.get_value("Student", student, "last_name") or "").casefold()
			for student in ordered
		]
		self.assertEqual(surnames, sorted(surnames))

	def test_ordering_keeps_everyone(self):
		"""A student missing the field being sorted on moves, but is never dropped."""
		students = self._students(12)
		for order in (BY_LAST_NAME, BY_FIRST_NAME, BY_STUDENT_ID):
			with self.subTest(order=order):
				self.assertCountEqual(order_students(students, order), students)

	def test_the_configured_order_is_one_of_the_options(self):
		self.assertIn(get_student_order(), SORT_FIELD)

	def _students(self, count):
		students = frappe.get_all("Student", pluck="name", limit=count)
		if len(students) < 2:
			self.skipTest("site has too few students to order")
		return students
