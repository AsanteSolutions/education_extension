# Copyright (c) 2026, Asante Solutions and contributors
# For license information, please see license.txt

import unittest

import frappe
from frappe.tests.utils import FrappeTestCase

from education_extension.education_extension.doctype.marking_settings.marking_settings import (
	AS_RECORDED,
	BY_FIRST_NAME,
	BY_LAST_NAME,
	BY_STUDENT_ID,
	SORT_FIELD,
	SURNAME_FIRST,
	_display_name,
	display_names,
	get_student_name_display,
	get_student_order,
	order_students,
)
from education_extension.education_extension.testing import needs_doctype

# Stops Frappe walking this app link fields into every other app; see the
# note beside the list.
from education_extension.education_extension.testing import (  # noqa: F401
	IGNORE_TEST_RECORD_DEPENDENCIES,
)


class TestMarkingSettings(FrappeTestCase):
	def test_every_option_sorts_on_a_real_student_field(self):
		"""An option with no field behind it would silently fall back to surname."""
		options = frappe.get_meta("Marking Settings").get_field("student_order").options.split("\n")
		self.assertEqual(set(options), set(SORT_FIELD))

		needs_doctype(self, "Student")
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
		needs_doctype(self, "Student")
		students = frappe.get_all("Student", pluck="name", limit=count)
		if len(students) < 2:
			self.skipTest("site has too few students to order")
		return students


class TestHowAStudentIsNamed(FrappeTestCase):
	"""Surname first, or the name as it was captured.

	A mark sheet is read down the surname column, which is why the QA review has
	always shown "Mthembu, Nolwazi" -- but the entry grid beside it showed
	"Nolwazi Khanyisa Bongiwe Mthembu", so one form named the same class two
	ways. Both now ask `display_names`, and which form it gives is a setting.
	"""

	def test_the_options_are_the_ones_the_code_knows(self):
		"""An option the code does not know falls through to surname first, so a
		third one added to the Select would quietly do nothing."""
		options = (
			frappe.get_meta("Marking Settings").get_field("student_name_display").options.split("\n")
		)
		self.assertEqual(set(options), {SURNAME_FIRST, AS_RECORDED})

	def test_the_configured_naming_is_one_of_the_options(self):
		self.assertIn(get_student_name_display(), (SURNAME_FIRST, AS_RECORDED))

	def test_the_surname_comes_first_and_then_a_comma(self):
		row = frappe._dict(
			name="20260001",
			student_name="Nolwazi Mthembu",
			first_name="Nolwazi",
			middle_name=None,
			last_name="Mthembu",
		)
		self.assertEqual(_display_name(row, SURNAME_FIRST), "Mthembu, Nolwazi")

	def test_the_middle_name_travels_with_the_first(self):
		"""The comma separates the surname from everything else, not the first
		name from the rest."""
		row = frappe._dict(
			name="20990044",
			student_name="Siyabonga Unathi Dube",
			first_name="Siyabonga",
			middle_name="Unathi",
			last_name="Dube",
		)
		self.assertEqual(_display_name(row, SURNAME_FIRST), "Dube, Siyabonga Unathi")

	def test_a_double_surname_stays_whole(self):
		"""Why the name fields are read instead of the stored name being split: no
		rule about spaces tells you that "Van Der Merwe" is one surname and not a
		given name and a surname."""
		row = frappe._dict(
			name="20260001",
			student_name="Jan Van Der Merwe",
			first_name="Jan",
			middle_name=None,
			last_name="Van Der Merwe",
		)
		self.assertEqual(_display_name(row, SURNAME_FIRST), "Van Der Merwe, Jan")

	def test_stray_spaces_are_squeezed_out(self):
		"""Captured names carry them: one student on this site is recorded with
		middle_name "Unathi ", which is why their stored name has a double
		space in it."""
		row = frappe._dict(
			name="20990044",
			student_name="Siyabonga Unathi  Dube",
			first_name="Siyabonga",
			middle_name="Unathi ",
			last_name=" Dube",
		)
		self.assertEqual(_display_name(row, SURNAME_FIRST), "Dube, Siyabonga Unathi")
		self.assertEqual(_display_name(row, AS_RECORDED), "Siyabonga Unathi Dube")

	def test_as_recorded_is_the_name_on_the_student_record(self):
		row = frappe._dict(
			name="20260001",
			student_name="Nolwazi Khanyisa Bongiwe Mthembu",
			first_name="Nolwazi Khanyisa Bongiwe",
			middle_name=None,
			last_name="Mthembu",
		)
		self.assertEqual(
			_display_name(row, AS_RECORDED), "Nolwazi Khanyisa Bongiwe Mthembu"
		)

	def test_a_student_with_no_surname_is_shown_as_recorded(self):
		"""A "Nolwazi, " or a ", Mthembu" is worse than the name somebody typed."""
		row = frappe._dict(
			name="20260001",
			student_name="Nolwazi",
			first_name="Nolwazi",
			middle_name=None,
			last_name=None,
		)
		self.assertEqual(_display_name(row, SURNAME_FIRST), "Nolwazi")

	def test_a_student_with_no_name_at_all_is_called_by_their_id(self):
		row = frappe._dict(
			name="20260001", student_name=None, first_name=None, middle_name=None, last_name=None
		)
		self.assertEqual(_display_name(row, SURNAME_FIRST), "20260001")

	def test_an_unknown_naming_falls_back_to_surname_first(self):
		row = frappe._dict(
			name="20260001",
			student_name="Nolwazi Mthembu",
			first_name="Nolwazi",
			middle_name=None,
			last_name="Mthembu",
		)
		self.assertEqual(_display_name(row, "Nonsense"), _display_name(row, SURNAME_FIRST))

	def test_nobody_to_name_is_not_an_error(self):
		self.assertEqual(display_names([]), {})
		self.assertEqual(display_names(None), {})

	def test_a_student_the_doctype_no_longer_has_keeps_their_id(self):
		"""A sheet can carry marks for a student who has since gone. The row
		still has to come back with something in the name column."""
		self.assertEqual(display_names(["no-such-student"]), {"no-such-student": "no-such-student"})

	def test_the_same_student_is_only_asked_for_once(self):
		"""A sheet hands this one entry per student per assessment -- 560 rows on
		a course of seventy -- and that list becomes the IN clause."""
		needs_doctype(self, "Student")
		student = frappe.get_all("Student", pluck="name", limit=1)
		if not student:
			self.skipTest("site has no students")

		self.assertEqual(len(display_names(student * 8)), 1)

	def test_both_namings_name_everyone(self):
		needs_doctype(self, "Student")
		students = frappe.get_all("Student", pluck="name", limit=12)
		if len(students) < 2:
			self.skipTest("site has too few students to name")

		for display in (SURNAME_FIRST, AS_RECORDED):
			with self.subTest(display=display):
				names = display_names(students, display)
				self.assertCountEqual(names, students)
				self.assertTrue(all(names.values()), "somebody came back without a name")


def run_tests(verbosity=2):
	"""Run these from a console, since bench run-tests cannot bootstrap this site.

	This file sat in a doctype folder with no runner, so nothing in it ran for
	anyone working locally -- only in CI, which is the worst of both.
	"""
	suite = unittest.TestSuite()
	loader = unittest.TestLoader()
	for case in (TestMarkingSettings, TestHowAStudentIsNamed):
		suite.addTests(loader.loadTestsFromTestCase(case))
	return unittest.TextTestRunner(verbosity=verbosity).run(suite)
