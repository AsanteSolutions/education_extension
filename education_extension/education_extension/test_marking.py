# Copyright (c) 2026, Asante Solutions and contributors
# For license information, please see license.txt

import unittest

import frappe
from frappe.tests import IntegrationTestCase
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
	NO_MARK,
	SUPPLEMENTARY,
	_course_remarks,
	_merge_sheet_marks,
	_supplementary_marks,
	calculate_course_mark,
	format_mark,
	legacy_course_marks,
	remark_codes,
	resolve_results,
	score_ratio,
	set_course_remark,
	sitting_of,
)
from education_extension.education_extension.testing import (
	needs_doctype,
	needs_education_app,
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


class TestTheGradesPageNamesModulesWithNoResults(IntegrationTestCase):
	"""The table is built from the marks, so a module with none has no row in it.

	A student looking for a result they were expecting found nothing and nothing
	saying why. The portal papered over that with a line of text naming one
	module, hard-coded into the page, shown to every student on every term and
	true only until somebody remembered to take it out.
	"""

	def setUp(self):
		needs_education_app(self)
		needs_doctype(self, "Program Enrollment", "Assessment Result")

		self.case = a_student_missing_a_module()
		if not self.case:
			self.skipTest("every registered module on this site has marks")

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def without_results(self):
		from education_extension.education_extension.marking import (
			_modules_with_nothing_recorded,
			get_assessment_results,
		)

		return _modules_with_nothing_recorded(
			self.case["student"],
			self.case["academic_year"],
			self.case["academic_term"],
			get_assessment_results(self.case["student"], self.case["academic_term"]),
		)

	def test_a_registered_module_with_no_marks_is_named(self):
		self.assertIn(self.case["course"], self.without_results())

	def test_a_module_the_student_has_marks_in_is_not_named(self):
		"""Or the notice would name most of the student's timetable."""
		marked = frappe.get_all(
			"Assessment Result",
			filters={
				"student": self.case["student"],
				"academic_term": self.case["academic_term"],
				"docstatus": 1,
			},
			pluck="course",
		)
		named = self.without_results()
		for course in set(marked):
			self.assertNotIn(course, named, course)

	def test_it_names_nothing_a_student_is_not_registered_for(self):
		"""It answers for this student's own timetable, not the curriculum."""
		from education_extension.education_extension.registration import registered_courses

		registered = registered_courses(
			self.case["student"], self.case["academic_year"], self.case["academic_term"]
		)
		for course in self.without_results():
			self.assertIn(course, registered, course)

	def test_the_payload_carries_it_for_the_page_to_render(self):
		"""The page reads `without_results`; a server that stops sending it would
		silently take the notice away."""
		from education_extension.education_extension.marking import get_student_grades

		user = frappe.db.get_value("Student", self.case["student"], "user")
		if not user:
			self.skipTest("that student has no portal account")

		frappe.set_user(user)
		payload = get_student_grades(self.case["academic_year"], self.case["academic_term"])
		frappe.set_user("Administrator")

		if payload.get("message"):
			self.skipTest("that term is not released for this student")
		self.assertIn("without_results", payload)
		self.assertIn(self.case["course"], payload["without_results"])


def a_student_missing_a_module():
	"""A student registered for a module with no marks on record, or None.

	Found rather than made: the state needs a submitted enrolment and an absence
	of results, and manufacturing the absence means manufacturing everything
	around it.
	"""
	row = frappe.db.sql(
		"""
		select pe.student, pe.academic_year, pe.academic_term, pec.course
		from `tabProgram Enrollment` pe
		join `tabProgram Enrollment Course` pec on pec.parent = pe.name
		where pe.docstatus = 1
		  and not exists (
			select 1 from `tabAssessment Result` ar
			where ar.docstatus = 1 and ar.student = pe.student
			  and ar.course = pec.course and ar.academic_term = pe.academic_term
		  )
		limit 1
		""",
		as_dict=True,
	)
	return row[0] if row else None


class TestAMarkWithNoMaximumRecorded(FrappeTestCase):
	"""`maximum_score` is an optional Float, so a mark captured without one holds
	a 0 — and a mark out of nought is not a mark anybody can be awarded.

	It was being read as no mark at all. `calculate_course_mark` counted the
	assessment as missing, so submitting a scheme for the course turned a mark
	the legacy calculation had been showing all along into a dash that nothing
	could clear, with nothing on the row saying the maximum was what was absent.
	"""

	COURSE = "TEST1101 - Test Course"

	def result(self, score, maximum, group="Test 1"):
		row = {"course": self.COURSE, "assessment_group": group, "total_score": score}
		if maximum is not None:
			row["maximum_score"] = maximum
		return row

	def test_a_score_with_no_maximum_is_read_out_of_a_hundred(self):
		for maximum in (0, None):
			with self.subTest(maximum=maximum):
				self.assertEqual(score_ratio(self.result(65, maximum)), 0.65)

	def test_a_real_maximum_is_still_honoured(self):
		"""The reason `score_ratio` exists; it must not become a no-op."""
		self.assertEqual(score_ratio(self.result(45, 50)), 0.9)

	def test_no_score_is_still_no_mark(self):
		"""Unmarked means no score. That is the case the None was for."""
		self.assertIsNone(score_ratio(self.result(None, 100)))
		self.assertIsNone(score_ratio(self.result(None, 0)))

	def test_a_zero_is_a_mark_not_an_absence(self):
		self.assertEqual(score_ratio(self.result(0, 100)), 0.0)
		self.assertEqual(score_ratio(self.result(0, 0)), 0.0)

	def test_the_course_is_not_dashed_for_want_of_a_maximum(self):
		"""The shape of the bug: a complete set of marks reading as incomplete."""
		criteria = [
			{"assessment_group": "Test 1", "component": COURSEWORK, "weightage": 50,
			 "subminimum": None, "is_required": 1},
			{"assessment_group": "Theory Exam", "component": EXAMINATION, "weightage": 50,
			 "subminimum": None, "is_required": 1},
		]
		results = [self.result(60, 0), self.result(70, 0, group="Theory Exam")]

		computed = calculate_course_mark(criteria, results)
		self.assertEqual(computed["missing"], [])
		self.assertEqual(computed["unmarked"], [])
		self.assertTrue(computed["dp_complete"] and computed["exams_complete"])
		self.assertEqual(mark(criteria, results), "65")

	def test_converting_the_course_to_a_scheme_does_not_change_the_mark(self):
		"""The invariant that matters. The legacy calculation reads every score as
		a percentage, so a course with no maxima recorded had a mark all along —
		submitting a scheme must not take it away."""
		course = "ANH1201 - Anatomy"
		criteria = scheme_for(course)
		results = [
			{"course": course, "assessment_group": row["assessment_group"],
			 "total_score": 63, "maximum_score": 0}
			for row in criteria
		]

		self.assertEqual(mark(criteria, results), calculate_final_results(results)[course])
		self.assertNotEqual(mark(criteria, results), NO_MARK)

	def test_a_supplementary_with_no_maximum_is_still_reported(self):
		"""It was dropping out of the supplementary column for the same reason."""
		self.assertEqual(
			_supplementary_marks(
				{self.COURSE: [self.result(58, 0, group="Supplementary Exam")]}
			),
			{self.COURSE: "58%"},
		)


class TestAnOptionalAssessmentNobodySat(FrappeTestCase):
	"""`is_required` is documented as "must be marked before the final mark is
	complete", so an optional row left unmarked is an expected state, not a gap.

	It was costing the student its weighting. Nothing went into `missing`, so the
	mark was published as complete — while the weight stayed in the denominator,
	so a student with full marks on everything they did sit came out short by
	exactly that row's share, with nothing anywhere saying why.
	"""

	COURSE = "TEST1101 - Test Course"

	def scheme(self, optional_weight=10):
		"""Two tests, an optional assignment, and a paper. Totals 100, as a
		submitted scheme is validated to."""
		return [
			{"assessment_group": "Test 1", "component": COURSEWORK, "weightage": 20,
			 "subminimum": None, "is_required": 1},
			{"assessment_group": "Test 2", "component": COURSEWORK, "weightage": 20,
			 "subminimum": None, "is_required": 1},
			{"assessment_group": "Assignment 1", "component": COURSEWORK,
			 "weightage": optional_weight, "subminimum": None, "is_required": 0},
			{"assessment_group": "Theory Exam", "component": EXAMINATION,
			 "weightage": 50 - optional_weight + 10, "subminimum": None, "is_required": 1},
		]

	def results(self, **scores):
		return [
			{
				"course": self.COURSE,
				"assessment_group": group.replace("_", " ").title(),
				"total_score": score,
				"maximum_score": 100,
			}
			for group, score in scores.items()
		]

	def test_full_marks_on_what_was_sat_is_full_marks(self):
		"""The shape of the bug. 100 on everything taken came out as 90."""
		computed = calculate_course_mark(
			self.scheme(), self.results(test_1=100, test_2=100, theory_exam=100)
		)

		self.assertTrue(computed["dp_complete"] and computed["exams_complete"])
		self.assertAlmostEqual(computed["final_mark"], 100, places=6)
		self.assertAlmostEqual(computed["dp"], 100, places=6)

	def test_the_mark_is_still_published_as_complete(self):
		"""Which it should be — that is what optional means — and is why the
		deflated mark went out rather than showing a dash."""
		computed = calculate_course_mark(
			self.scheme(), self.results(test_1=60, test_2=60, theory_exam=60)
		)

		self.assertEqual(computed["missing"], [])
		self.assertTrue(computed["dp_complete"] and computed["exams_complete"])
		self.assertAlmostEqual(computed["final_mark"], 60, places=6)

	def test_an_optional_assessment_that_was_sat_counts_normally(self):
		"""Optional is about whether it is owed, not about whether it counts."""
		computed = calculate_course_mark(
			self.scheme(), self.results(test_1=100, test_2=100, assignment_1=0, theory_exam=100)
		)

		# The 10 points it is worth are back in play, and scored nothing.
		self.assertAlmostEqual(computed["final_mark"], 90, places=6)

	def test_a_required_assessment_left_unmarked_still_reads_as_incomplete(self):
		"""The other half: a gap must not be rescaled away into a full mark."""
		computed = calculate_course_mark(
			self.scheme(), self.results(test_1=100, test_2=100, assignment_1=100)
		)

		self.assertEqual(computed["missing"], ["Theory Exam"])
		self.assertFalse(computed["exams_complete"])
		self.assertEqual(format_mark(computed["final_mark"], False), NO_MARK)

	def test_a_scheme_with_nothing_optional_is_unchanged(self):
		"""Every scheme on every site today, so this must not move."""
		for course in ARCHETYPES:
			criteria = scheme_for(course)
			scores = {row["assessment_group"]: 63 for row in criteria}
			with self.subTest(course=course):
				self.assertEqual(
					mark(criteria, results_for(course, scores)),
					calculate_final_results(results_for(course, scores))[course],
				)

	def test_a_mark_on_the_rounding_boundary_does_not_move(self):
		"""The near-miss in this change, pinned.

		Rescaling by a total that is already 100 is the same number in arithmetic
		and a different one in floating point: `57.5 / 100.0 * 100` is
		57.499999999999993, which rounds to 57 where 57.5 rounds to 58. Done
		unconditionally it moved two real students' marks by one, and a check that
		rounded to six decimals before comparing reported nothing.
		"""
		criteria = [
			{"assessment_group": "Test 1", "component": COURSEWORK, "weightage": 50,
			 "subminimum": None, "is_required": 1},
			{"assessment_group": "Theory Exam", "component": EXAMINATION, "weightage": 50,
			 "subminimum": None, "is_required": 1},
		]
		computed = calculate_course_mark(criteria, self.results(test_1=60, theory_exam=55))

		self.assertEqual(computed["final_mark"], 57.5)
		self.assertEqual(format_mark(computed["final_mark"], True), "58")

	def test_a_student_who_sat_nothing_optional_is_not_divided_by_nothing(self):
		"""Every coursework row optional and none of them sat."""
		criteria = [
			{"assessment_group": "Assignment 1", "component": COURSEWORK, "weightage": 50,
			 "subminimum": None, "is_required": 0},
			{"assessment_group": "Theory Exam", "component": EXAMINATION, "weightage": 50,
			 "subminimum": None, "is_required": 1},
		]
		computed = calculate_course_mark(criteria, self.results(theory_exam=70))

		self.assertEqual(computed["dp"], 0.0)
		self.assertAlmostEqual(computed["final_mark"], 70, places=6)


class TestTheLegacyPathReadsTheSittingToo(FrappeTestCase):
	"""The fallback for a course with no scheme, which is the one serving the
	changeover.

	It decided what an aegrotat was from the assessment group's name alone — the
	retired "AEGRO Theory Exam" convention — and never read the sitting the mark
	actually carries. So a mark whose sitting said Aegrotat but whose group was
	the plain "Theory Exam" was indistinguishable from the paper it stood in for:
	both landed on one field and, with no ordering on the query behind them,
	whichever arrived last won.
	"""

	COURSE = "ANH1201 - Anatomy"

	def result(self, group, score, sitting=None):
		row = {
			"course": self.COURSE,
			"assessment_group": group,
			"total_score": score,
			"maximum_score": 100,
		}
		if sitting:
			row["sitting"] = sitting
		return row

	def everything_but_theory(self, score=60):
		return [
			self.result(row["assessment_group"], score)
			for row in scheme_for(self.COURSE)
			if row["assessment_group"] != "Theory Exam"
		]

	def mark_for(self, theory_papers):
		return calculate_final_results(self.everything_but_theory() + theory_papers)[self.COURSE]

	def test_an_aegrotat_on_the_sitting_field_displaces_the_main_paper(self):
		"""The main theory paper scores 0 and the aegrotat 60, so a mark of 60 can
		only come from the aegrotat having replaced it — in either order, because
		nothing orders the rows."""
		papers = [
			self.result("Theory Exam", 0),
			self.result("Theory Exam", 60, sitting="Aegrotat"),
		]
		self.assertEqual(self.mark_for(papers), "60")
		self.assertEqual(self.mark_for(list(reversed(papers))), "60")

	def test_an_aegrotat_on_the_sitting_field_is_enough_on_its_own(self):
		self.assertEqual(
			self.mark_for([self.result("Theory Exam", 60, sitting="Aegrotat")]), "60"
		)

	def test_the_retired_naming_still_works(self):
		"""A mark entered on the standard form is not prompted for a sitting, so
		an AEGRO-named group has to go on meaning what it always meant."""
		papers = [
			self.result("Theory Exam", 0),
			self.result("AEGRO Theory Exam", 60),
		]
		self.assertEqual(self.mark_for(papers), "60")
		self.assertEqual(self.mark_for(list(reversed(papers))), "60")

	def test_a_supplementary_on_the_sitting_field_is_not_folded_in(self):
		"""It is reported in a column of its own. Carried on the sitting rather
		than in the group's name, it used to land on the theory field and count
		towards the final mark."""
		papers = [
			self.result("Theory Exam", 60),
			self.result("Theory Exam", 99, sitting="Supplementary"),
		]
		self.assertEqual(self.mark_for(papers), "60")
		self.assertEqual(self.mark_for(list(reversed(papers))), "60")

	def test_a_group_recorded_in_another_case_still_counts(self):
		"""Casing of an assessment group must not quietly cost a student a mark,
		which is what the scheme path already guarantees."""
		self.assertEqual(self.mark_for([self.result("theory exam", 60)]), "60")

	def test_it_agrees_with_the_scheme_calculation_on_the_same_aegrotat(self):
		"""The invariant the whole fallback exists to hold: a course converting to
		a scheme must not change what the student scored.

		Both orderings, because nothing orders the rows and the old reading
		happened to agree in one of them — it took the last mark to land on the
		field, which is the aegrotat only if the aegrotat came second.
		"""
		papers = [
			self.result("Theory Exam", 0),
			self.result("Theory Exam", 60, sitting="Aegrotat"),
		]
		criteria = scheme_for(self.COURSE)

		for order in (papers, list(reversed(papers))):
			results = self.everything_but_theory() + order
			with self.subTest(aegrotat_first=order[0].get("sitting") == "Aegrotat"):
				self.assertEqual(
					calculate_final_results(results)[self.COURSE],
					mark(criteria, results),
				)


class TestFilingAndWithdrawingAComment(IntegrationTestCase):
	"""`set_course_remark` over the whole life of one comment.

	The comment field is `reqd`, so there is no such thing as a remark with no
	remark on it. Withdrawing one therefore has to cancel the record: blanking
	the field left it submitted but invisible -- every reader tests the field and
	skips the row -- while the mark sheet went on refusing approval for want of a
	comment nobody could see had been erased.
	"""

	def setUp(self):
		needs_education_app(self)
		needs_doctype(self, "Academic Remark", "Assessment Result")

		self.keys = keys_with_no_comment_yet()
		if not self.keys:
			self.skipTest("every student already has a comment on that course and term")

		self.codes = remark_codes("Academic Remark")
		if len(self.codes) < 2:
			self.skipTest("Academic Remark offers fewer than two codes")

	def tearDown(self):
		frappe.db.rollback()

	def file(self, comment):
		return set_course_remark(comment=comment, **self.keys)

	def submitted(self):
		return frappe.get_all(
			"Academic Remark", filters=dict(self.keys, docstatus=1), pluck="name"
		)

	def test_the_whole_life_of_one_comment(self):
		first = self.file(self.codes[0])
		self.assertEqual(self.submitted(), [first], "filing did not leave one submitted record")
		self.assertEqual(frappe.db.get_value("Academic Remark", first, "remark"), self.codes[0])

		# Replacing writes in place, on the same record.
		self.assertEqual(self.file(self.codes[1]), first)
		self.assertEqual(frappe.db.get_value("Academic Remark", first, "remark"), self.codes[1])

		# Withdrawing cancels it, and says so by returning nothing to point at.
		self.assertIsNone(self.file(""))
		self.assertEqual(self.submitted(), [], "a withdrawn comment is still on file")
		self.assertEqual(frappe.db.get_value("Academic Remark", first, "docstatus"), 2)

	def test_the_judgement_itself_is_kept(self):
		"""Cancelled, not blanked. What QA decided, and then took back, is part
		of what QA did."""
		name = self.file(self.codes[0])
		self.file("")

		self.assertEqual(
			frappe.db.get_value("Academic Remark", name, "remark"),
			self.codes[0],
			"withdrawing erased the comment instead of cancelling the record",
		)

	def test_a_withdrawn_comment_leaves_the_reports(self):
		self.file(self.codes[0])
		self.assertIn(self.keys["student"], self.course_remarks())

		self.file("")
		self.assertNotIn(
			self.keys["student"],
			self.course_remarks(),
			"a withdrawn comment is still being reported",
		)

	def test_a_comment_can_be_filed_again_afterwards(self):
		"""The lookup skips cancelled records, so the next one files cleanly
		rather than colliding with what was withdrawn."""
		first = self.file(self.codes[0])
		self.file("")
		second = self.file(self.codes[1])

		self.assertNotEqual(second, first)
		self.assertEqual(self.submitted(), [second])

	def test_withdrawing_when_nothing_was_filed_does_nothing(self):
		self.assertIsNone(self.file(""))
		self.assertEqual(self.submitted(), [])

	def test_no_submitted_remark_is_ever_left_blank(self):
		"""The shape of the bug, asserted directly: whatever the sequence, a
		submitted record always carries a comment."""
		for comment in (self.codes[0], "", self.codes[1], "", ""):
			self.file(comment)
			blank = [
				name
				for name in self.submitted()
				if not (frappe.db.get_value("Academic Remark", name, "remark") or "").strip()
			]
			self.assertEqual(blank, [], "a submitted remark was left with no comment on it")

	def course_remarks(self):
		return _course_remarks(
			self.keys["course"], self.keys["academic_term"], "Academic Remark", "remark"
		)


def keys_with_no_comment_yet():
	"""Student, course and term that QA has not commented on, or None.

	The links are found rather than made — building a Student and a Course inside
	the test would mean constructing the records it is meant to be writing
	against — but the combination need not be one anybody actually sat. An
	Academic Remark requires only that the four links resolve, and on a site
	where every real sitting already carries a comment there would otherwise be
	nothing free to write to.
	"""
	term = frappe.db.get_value(
		"Academic Term", {"academic_year": ["is", "set"]}, ["name", "academic_year"], as_dict=True
	)
	course = frappe.db.get_value("Course", {}, "name")
	if not (term and course):
		return None

	for student in frappe.get_all("Student", pluck="name", limit=200):
		keys = {
			"student": student,
			"course": course,
			"academic_year": term.academic_year,
			"academic_term": term.name,
		}
		if not frappe.db.exists("Academic Remark", dict(keys, docstatus=["<", 2])):
			return keys
	return None


def run_tests(verbosity=2):
	"""Run these from a console, since bench run-tests cannot bootstrap this site."""
	suite = unittest.TestSuite()
	loader = unittest.TestLoader()
	for case in (
		TestMarking,
		TestSheetsAndSittings,
		TestLegacyFallbackShape,
		TestEverySittingCanBeReleased,
		TestTheGradesPageNamesModulesWithNoResults,
		TestAMarkWithNoMaximumRecorded,
		TestAnOptionalAssessmentNobodySat,
		TestTheLegacyPathReadsTheSittingToo,
		TestFilingAndWithdrawingAComment,
	):
		suite.addTests(loader.loadTestsFromTestCase(case))
	return unittest.TextTestRunner(verbosity=verbosity).run(suite)
