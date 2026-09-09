# Copyright (c) 2026, Asante Solutions and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from education_extension.education_extension.doctype.course_mark_scheme.course_mark_scheme import (
	COURSEWORK,
	EXAMINATION,
	legacy_criteria_for_course,
)

# One course per shape the marking rules recognise, with the number of
# assessments each is marked on.
ARCHETYPES = {
	"OCAH1101 - Occupational Communication I": 5,  # no practical test, theory paper only
	"ANH3506 - Herd Health": 6,  # practical test, theory paper only
	"ANH2404 - Animal Nutrition": 7,  # no practical test, three papers
	"CLT1101 - Clinical Techniques": 7,  # practical test, no oral
	"ANH1201 - Anatomy": 8,  # the standard shape
}


class TestCourseMarkScheme(FrappeTestCase):
	def test_legacy_derivation_covers_every_course_shape(self):
		for course, expected_rows in ARCHETYPES.items():
			with self.subTest(course=course):
				rows = legacy_criteria_for_course(course)
				self.assertEqual(len(rows), expected_rows)

	def test_legacy_weightings_total_one_hundred(self):
		for course in ARCHETYPES:
			with self.subTest(course=course):
				total = sum(weightage for _group, _component, weightage in legacy_criteria_for_course(course))
				self.assertAlmostEqual(total, 100, places=6)

	def test_legacy_split_is_half_coursework_half_examination(self):
		for course in ARCHETYPES:
			with self.subTest(course=course):
				rows = legacy_criteria_for_course(course)
				coursework = sum(w for _g, component, w in rows if component == COURSEWORK)
				examination = sum(w for _g, component, w in rows if component == EXAMINATION)
				self.assertAlmostEqual(coursework, 50, places=6)
				self.assertAlmostEqual(examination, 50, places=6)

	def test_an_unlisted_course_gets_the_standard_shape(self):
		"""A course in none of the exception sets is marked on everything."""
		rows = legacy_criteria_for_course("ZZZ9999 - Something New")
		groups = [group for group, _component, _weightage in rows]
		self.assertIn("Practical Test", groups)
		self.assertIn("Oral Exam", groups)
		self.assertEqual(len(rows), 8)

	def test_weightings_must_total_one_hundred(self):
		scheme = self._draft(criteria=[("Theory Exam", EXAMINATION, 40)])
		self.assertRaises(frappe.ValidationError, scheme.insert)

	def test_an_assessment_cannot_appear_twice(self):
		scheme = self._draft(
			criteria=[("Theory Exam", EXAMINATION, 50), ("Theory Exam", EXAMINATION, 50)]
		)
		self.assertRaises(frappe.ValidationError, scheme.insert)

	def test_totals_are_set_on_save(self):
		scheme = self._draft(
			criteria=[("Test 1", COURSEWORK, 50), ("Theory Exam", EXAMINATION, 50)]
		)
		scheme.insert()
		self.assertAlmostEqual(scheme.coursework_weightage, 50, places=6)
		self.assertAlmostEqual(scheme.examination_weightage, 50, places=6)
		self.assertAlmostEqual(scheme.total_weightage, 100, places=6)

	def _draft(self, criteria):
		"""A scheme against whatever course and year the site happens to have."""
		course = frappe.get_all("Course", pluck="name", limit=1)
		academic_year = frappe.get_all("Academic Year", pluck="name", limit=1)
		if not course or not academic_year:
			self.skipTest("site has no Course or Academic Year to build a scheme against")

		return frappe.get_doc(
			{
				"doctype": "Course Mark Scheme",
				"course": course[0],
				"academic_year": academic_year[0],
				"criteria": [
					{"assessment_group": group, "component": component, "weightage": weightage}
					for group, component, weightage in criteria
				],
			}
		)
