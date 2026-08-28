# Copyright (c) 2026, Asante Solutions and contributors
# For license information, please see license.txt

from frappe.tests.utils import FrappeTestCase

from education_extension.education_extension.doctype.course_mark_scheme.course_mark_scheme import (
	COURSEWORK,
	EXAMINATION,
	legacy_criteria_for_course,
)
from education_extension.education_extension.doctype.student_progress_report.student_progress_report import (
	calculate_final_results,
)
from education_extension.education_extension.marking import (
	calculate_course_mark,
	format_mark,
	resolve_results,
	sitting_of,
)

# One course per shape the marking rules recognise.
ARCHETYPES = [
	"OCAH1101 - Occupational Communication I",
	"ANH3506 - Herd Health",
	"ANH2404 - Animal Nutrition",
	"CLT1101 - Clinical Techniques",
	"ANH1201 - Anatomy",
]


def scheme_for(course):
	return [
		{
			"assessment_group": group,
			"component": component,
			"weightage": weightage,
			"subminimum": None,
			"is_required": 1,
		}
		for group, component, weightage in legacy_criteria_for_course(course)
	]


def results_for(course, scores):
	return [
		{
			"course": course,
			"assessment_group": group,
			"total_score": score,
			"maximum_score": 100,
		}
		for group, score in scores.items()
	]


def mark(criteria, results):
	computed = calculate_course_mark(criteria, results)
	return format_mark(
		computed["final_mark"], computed["dp_complete"] and computed["exams_complete"]
	)


class TestMarking(FrappeTestCase):
	def test_agrees_with_the_legacy_calculation(self):
		"""The gate for pointing anything at the scheme: same mark, every shape."""
		for course in ARCHETYPES:
			criteria = scheme_for(course)
			scores = {row["assessment_group"]: 63 for row in criteria}
			with self.subTest(course=course):
				results = results_for(course, scores)
				self.assertEqual(
					mark(criteria, results),
					calculate_final_results(results)[course],
				)

	def test_a_missing_assessment_leaves_the_mark_incomplete(self):
		course = "ANH1201 - Anatomy"
		criteria = scheme_for(course)
		scores = {row["assessment_group"]: 60 for row in criteria}
		del scores["Oral Exam"]

		computed = calculate_course_mark(criteria, results_for(course, scores))
		self.assertFalse(computed["exams_complete"])
		self.assertEqual(computed["missing"], ["Oral Exam"])
		self.assertEqual(mark(criteria, results_for(course, scores)), "-")

	def test_the_dp_is_reported_out_of_one_hundred(self):
		"""Coursework is half the final mark, but the DP column shows it out of 100."""
		course = "ANH1201 - Anatomy"
		criteria = scheme_for(course)
		scores = {row["assessment_group"]: 60 for row in criteria}

		self.assertAlmostEqual(
			calculate_course_mark(criteria, results_for(course, scores))["dp"], 60, places=6
		)

	def test_an_aegrotat_sitting_displaces_the_main_one(self):
		"""The aegrotat mark counts and the main one does not, in either order."""
		course = "ANH1201 - Anatomy"
		criteria = scheme_for(course)
		everything_else = {
			row["assessment_group"]: 60
			for row in criteria
			if row["assessment_group"] != "Theory Exam"
		}

		# The main theory paper scores 0 and the aegrotat one 60, so a mark of 60
		# can only come from the aegrotat sitting having replaced it.
		orders = (
			[("Theory Exam", 0), ("AEGRO Theory Exam", 60)],
			[("AEGRO Theory Exam", 60), ("Theory Exam", 0)],
		)
		for theory_papers in orders:
			with self.subTest(order=[group for group, _score in theory_papers]):
				results = results_for(course, everything_else) + [
					{
						"course": course,
						"assessment_group": group,
						"total_score": score,
						"maximum_score": 100,
					}
					for group, score in theory_papers
				]
				self.assertEqual(mark(criteria, results), "60")

	def test_an_aegrotat_sitting_alone_is_enough(self):
		course = "ANH1201 - Anatomy"
		criteria = scheme_for(course)
		scores = {row["assessment_group"]: 60 for row in criteria}
		del scores["Theory Exam"]
		scores["AEGRO Theory Exam"] = 60

		self.assertEqual(mark(criteria, results_for(course, scores)), "60")

	def test_the_sitting_field_says_what_a_mark_counts_towards(self):
		"""The field, not the name of the assessment group."""
		self.assertEqual(
			sitting_of({"assessment_group": "Theory Exam", "sitting": "Aegrotat"}),
			("Theory Exam", "Aegrotat"),
		)
		self.assertEqual(
			sitting_of({"assessment_group": "Theory Exam", "sitting": "Main"}),
			("Theory Exam", "Main"),
		)
		self.assertEqual(
			sitting_of({"assessment_group": "Theory Exam"}), ("Theory Exam", "Main")
		)

	def test_the_old_naming_is_still_read_where_no_sitting_was_set(self):
		"""A mark entered on the standard form is not prompted for a sitting, so an
		AEGRO-named group still has to mean what it always meant."""
		for group in ("AEGRO Theory Exam", "AEGROTAT Theory Exam", "AEGROTheory Exam"):
			with self.subTest(group=group):
				self.assertEqual(sitting_of({"assessment_group": group}), ("Theory Exam", "Aegrotat"))

		self.assertEqual(
			sitting_of({"assessment_group": "Supplementary Exam"}),
			("Supplementary Exam", "Supplementary"),
		)

	def test_an_aegrotat_mark_still_carrying_the_old_name_lands_on_the_right_assessment(self):
		self.assertEqual(
			sitting_of({"assessment_group": "AEGRO Theory Exam", "sitting": "Aegrotat"}),
			("Theory Exam", "Aegrotat"),
		)

	def test_a_sitting_field_beats_the_old_naming(self):
		"""A mark moved onto the assessment it stands in for still counts once."""
		course = "ANH1201 - Anatomy"
		criteria = scheme_for(course)
		results = results_for(course, {row["assessment_group"]: 60 for row in criteria})
		for result in results:
			if result["assessment_group"] == "Theory Exam":
				result["sitting"] = "Aegrotat"

		computed = calculate_course_mark(criteria, results)
		self.assertEqual(computed["missing"], [])
		self.assertEqual(mark(criteria, results), "60")

	def test_a_supplementary_mark_is_left_out_by_its_sitting(self):
		course = "ANH1201 - Anatomy"
		criteria = scheme_for(course)
		results = results_for(course, {row["assessment_group"]: 60 for row in criteria})
		results.append(
			{
				"course": course,
				"assessment_group": "Theory Exam",
				"sitting": "Supplementary",
				"total_score": 99,
				"maximum_score": 100,
			}
		)

		# The supplementary mark is reported on its own, so the final mark is
		# still the one the main sitting earned.
		self.assertEqual(mark(criteria, results), "60")

	def test_a_group_recorded_in_another_case_still_counts(self):
		"""Casing of an assessment group must not quietly cost a student the mark."""
		course = "ANH1201 - Anatomy"
		criteria = scheme_for(course)
		scores = {row["assessment_group"]: 60 for row in criteria}
		del scores["Theory Exam"]
		scores["aegro theory exam"] = 60

		computed = calculate_course_mark(criteria, results_for(course, scores))
		self.assertEqual(computed["missing"], [])
		self.assertEqual(computed["unscheduled"], [])
		self.assertEqual(mark(criteria, results_for(course, scores)), "60")

	def test_the_supplementary_exam_takes_no_part_in_the_mark(self):
		course = "ANH1201 - Anatomy"
		criteria = scheme_for(course)
		scores = {row["assessment_group"]: 60 for row in criteria}
		scores["Supplementary Exam"] = 99

		computed = calculate_course_mark(criteria, results_for(course, scores))
		self.assertEqual(mark(criteria, results_for(course, scores)), "60")
		self.assertEqual(computed["unscheduled"], [])

	def test_a_subminimum_breach_is_reported(self):
		"""Something the legacy calculation cannot do: FSUB as a derived fact."""
		course = "ANH1201 - Anatomy"
		criteria = scheme_for(course)
		for row in criteria:
			if row["assessment_group"] == "Theory Exam":
				row["subminimum"] = 40

		scores = {row["assessment_group"]: 60 for row in criteria}
		scores["Theory Exam"] = 35

		computed = calculate_course_mark(criteria, results_for(course, scores))
		self.assertEqual(computed["failed_subminima"], ["Theory Exam"])

	def test_a_mark_the_scheme_does_not_weight_is_surfaced(self):
		course = "ANH1201 - Anatomy"
		criteria = scheme_for(course)
		scores = {row["assessment_group"]: 60 for row in criteria}
		scores["Class Participation"] = 80

		computed = calculate_course_mark(criteria, results_for(course, scores))
		self.assertEqual(computed["unscheduled"], ["Class Participation"])
		self.assertEqual(mark(criteria, results_for(course, scores)), "60")

	def test_duplicate_results_keep_the_first(self):
		resolved = resolve_results(
			[
				{"assessment_group": "Theory Exam", "total_score": 70, "maximum_score": 100},
				{"assessment_group": "Theory Exam", "total_score": 10, "maximum_score": 100},
			]
		)
		self.assertEqual(resolved["Theory Exam"]["total_score"], 70)
