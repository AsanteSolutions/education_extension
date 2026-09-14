# Copyright (c) 2026, Asante Solutions and contributors
# For license information, please see license.txt

import unittest

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
	AEGROTAT,
	LEGACY_EMPTY_KEYS,
	MAIN,
	SUPPLEMENTARY,
	_merge_sheet_marks,
	_supplementary_marks,
	calculate_course_mark,
	format_mark,
	legacy_course_marks,
	remark_codes,
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

	def test_every_code_in_the_printed_legend_can_be_chosen(self):
		"""The legend explains what a code means to a student; if QA cannot pick
		one, the report explains something nobody can award."""
		import os
		import re

		template = os.path.join(
			os.path.dirname(__file__),
			"doctype",
			"student_progress_report",
			"student_progress_report_template.html",
		)
		with open(template) as handle:
			legend = set(
				re.findall(r'<td class="code">(?:<sup>\d</sup>\s*)?([A-Z]+)</td>', handle.read())
			)

		self.assertTrue(legend, "no codes found in the legend — has the template changed?")
		self.assertEqual(legend - set(remark_codes()), set())

	def test_both_remark_doctypes_offer_the_same_codes(self):
		"""They are one field per sitting, and QA picks from whichever it is
		editing. A code on one and not the other would be awardable in the first
		semester and not the second."""
		self.assertEqual(
			remark_codes("Academic Remark"),
			remark_codes("Supplementary Academic Remark"),
		)


class TestSheetsAndSittings(FrappeTestCase):
	"""A sheet answers for the sitting it covers, and only that one."""

	def stored(self, **sittings):
		"""One course of Assessment Result rows, a Theory Exam per sitting."""
		return {
			"ANH1201 - Anatomy": [
				{
					"course": "ANH1201 - Anatomy",
					"assessment_group": "Theory Exam",
					"sitting": sitting,
					"total_score": score,
					"maximum_score": 100,
				}
				for sitting, score in sittings.items()
			]
		}

	def sheet(self, sitting, score):
		return {
			"ANH1201 - Anatomy": [
				{
					"course": "ANH1201 - Anatomy",
					"assessment_group": "Theory Exam",
					"sitting": sitting,
					"total_score": score,
					"maximum_score": 100,
				}
			]
		}

	def test_a_supplementary_sheet_leaves_the_main_marks_alone(self):
		"""The one that was wrong: a term marked through Assessment Result lost
		its DP and final mark the moment one supplementary sheet was approved."""
		merged = _merge_sheet_marks(self.stored(Main=55), self.sheet(SUPPLEMENTARY, 62))

		rows = merged["ANH1201 - Anatomy"]
		by_sitting = {row["sitting"]: row["total_score"] for row in rows}
		self.assertEqual(by_sitting[MAIN], 55, "the main mark was displaced")
		self.assertEqual(by_sitting[SUPPLEMENTARY], 62)

	def test_a_sheet_replaces_the_sitting_it_covers(self):
		"""It is still the record for its own sitting, so the stored row goes."""
		merged = _merge_sheet_marks(self.stored(Main=55), self.sheet(MAIN, 71))

		rows = merged["ANH1201 - Anatomy"]
		self.assertEqual([row["total_score"] for row in rows], [71])

	def test_a_course_with_no_sheet_is_untouched(self):
		stored = self.stored(Main=55)
		self.assertEqual(_merge_sheet_marks(stored, {}), stored)

	def test_the_student_sees_a_supplementary_held_on_a_sheet(self):
		"""Read through the same resolution as the staff side. Querying
		Assessment Result directly could not see a sheet, so the student was
		shown a dash for a re-sit the report showed a mark for."""
		merged = _merge_sheet_marks(self.stored(Main=40), self.sheet(SUPPLEMENTARY, 62))
		self.assertEqual(_supplementary_marks(merged), {"ANH1201 - Anatomy": "62%"})

	def test_no_supplementary_means_no_entry(self):
		self.assertEqual(_supplementary_marks(self.stored(Main=55)), {})


class TestLegacyFallbackShape(FrappeTestCase):
	"""The fallback has to answer in the same shape as the scheme calculation,
	because the same readers read both."""

	COURSE = "ANH1201 - Anatomy"

	def results(self, score, maximum):
		return [
			{
				"course": self.COURSE,
				"assessment_group": "Test 1",
				"sitting": MAIN,
				"total_score": score,
				"maximum_score": maximum,
			}
		]

	def test_it_reports_the_lists_the_scheme_calculation_reports(self):
		"""review_rows subscripted `missing` and the legacy result had no such
		key, so the Course Results report died on exactly the courses the
		fallback exists to serve."""
		computed = legacy_course_marks(self.results(45, 100))[self.COURSE]
		for key in LEGACY_EMPTY_KEYS:
			self.assertIn(key, computed)
		self.assertIsNone(computed["scheme"])

	def test_a_mark_out_of_fifty_is_read_as_a_percentage(self):
		"""45 out of 50 is 90, and was reaching the legacy weightings as 45."""
		out_of_fifty = legacy_course_marks(self.results(45, 50))[self.COURSE]
		out_of_a_hundred = legacy_course_marks(self.results(90, 100))[self.COURSE]
		self.assertEqual(out_of_fifty["dp"], out_of_a_hundred["dp"])

	def test_an_unmarked_result_survives_the_restatement(self):
		computed = legacy_course_marks(self.results(None, 100))[self.COURSE]
		self.assertEqual(computed["dp"], 0.0)
		self.assertFalse(computed["dp_complete"])



class TestEverySittingCanBeReleased(FrappeTestCase):
	"""Publication is decided per sitting, so every sitting needs a kind of
	issue date to be published under — otherwise marks for it are recorded, and
	then held back forever by a release that has nowhere to be recorded."""

	def test_the_backfill_knows_every_sitting(self):
		from education_extension.patches.release_historical_progress_reports import (
			KIND_FOR_SITTING,
		)

		for sitting in (MAIN, SUPPLEMENTARY, AEGROTAT):
			with self.subTest(sitting=sitting):
				self.assertIn(sitting, KIND_FOR_SITTING)

	def test_a_result_from_before_the_sitting_field_counts_as_main(self):
		"""Those rows hold NULL, and they are ordinary marks."""
		from education_extension.patches.release_historical_progress_reports import (
			KIND_FOR_SITTING,
		)

		self.assertEqual(KIND_FOR_SITTING[None], KIND_FOR_SITTING[MAIN])
		self.assertEqual(KIND_FOR_SITTING[""], KIND_FOR_SITTING[MAIN])


def run_tests(verbosity=2):
	"""Run these from a console, since bench run-tests cannot bootstrap this site."""
	suite = unittest.TestSuite()
	loader = unittest.TestLoader()
	for case in (
		TestMarking,
		TestSheetsAndSittings,
		TestLegacyFallbackShape,
		TestEverySittingCanBeReleased,
	):
		suite.addTests(loader.loadTestsFromTestCase(case))
	return unittest.TextTestRunner(verbosity=verbosity).run(suite)
