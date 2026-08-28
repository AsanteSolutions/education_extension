# Copyright (c) 2026, Asante Solutions and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from education_extension.education_extension.doctype.course_mark_sheet.course_mark_sheet import (
	MODERATION_FLAT,
	MODERATION_LINEAR,
	moderated_value,
)
from education_extension.education_extension.doctype.mark_change.mark_change import (
	has_remark_changes,
)


class TestMarkChange(FrappeTestCase):
	def test_a_change_needs_a_mark_to_change(self):
		"""Recording a re-mark of something never marked would leave a change with
		nowhere to land."""
		change = frappe.get_doc(
			{
				"doctype": "Mark Change",
				"student": self._student(),
				"course": self._course(),
				"academic_year": self._year(),
				"academic_term": self._term(),
				"assessment_group": "Theory Exam",
				"sitting": "Main",
				"new_score": 70,
				"reason": "there is no such mark",
			}
		)
		change.student = "no-such-student"
		self.assertRaises(frappe.ValidationError, change.insert)

	def test_nothing_remarked_is_not_a_remarking(self):
		self.assertFalse(has_remark_changes("no-such-student", "no-such-term"))

	def test_a_remark_on_a_moderated_sheet_keeps_the_adjustment(self):
		"""The cohort adjustment was approved on its own terms, so it applies to
		the new mark too rather than being lost with the old one."""
		self.assertEqual(moderated_value(80, 100, MODERATION_FLAT, 10), 90)
		self.assertEqual(moderated_value(80, 100, MODERATION_LINEAR, 1.1), 88)

	def test_a_reason_is_required(self):
		meta = frappe.get_meta("Mark Change")
		self.assertTrue(meta.get_field("reason").reqd)
		self.assertTrue(meta.get_field("new_score").reqd)

	def test_the_previous_score_is_not_something_anyone_types(self):
		"""It is read off the mark at the moment of applying, so the record says
		what was actually there rather than what someone believed."""
		meta = frappe.get_meta("Mark Change")
		self.assertTrue(meta.get_field("previous_score").read_only)
		self.assertTrue(meta.get_field("approved_by").read_only)
		self.assertTrue(meta.get_field("applied_on").read_only)

	def _student(self):
		students = frappe.get_all("Student", pluck="name", limit=1)
		if not students:
			self.skipTest("site has no students")
		return students[0]

	def _course(self):
		courses = frappe.get_all("Course", pluck="name", limit=1)
		if not courses:
			self.skipTest("site has no courses")
		return courses[0]

	def _year(self):
		years = frappe.get_all("Academic Year", pluck="name", limit=1)
		if not years:
			self.skipTest("site has no academic years")
		return years[0]

	def _term(self):
		terms = frappe.get_all("Academic Term", pluck="name", limit=1)
		if not terms:
			self.skipTest("site has no academic terms")
		return terms[0]
