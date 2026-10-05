# Copyright (c) 2026, Asante Solutions and contributors
# For license information, please see license.txt

import unittest

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

# Stops Frappe walking this app link fields into every other app; see the
# note beside the list.
from education_extension.education_extension.testing import (  # noqa: F401
	IGNORE_TEST_RECORD_DEPENDENCIES,
	needs_doctype,
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
		needs_doctype(self, "Student")
		students = frappe.get_all("Student", pluck="name", limit=1)
		if not students:
			self.skipTest("site has no students")
		return students[0]

	def _course(self):
		needs_doctype(self, "Course")
		courses = frappe.get_all("Course", pluck="name", limit=1)
		if not courses:
			self.skipTest("site has no courses")
		return courses[0]

	def _year(self):
		needs_doctype(self, "Academic Year")
		years = frappe.get_all("Academic Year", pluck="name", limit=1)
		if not years:
			self.skipTest("site has no academic years")
		return years[0]

	def _term(self):
		needs_doctype(self, "Academic Term")
		terms = frappe.get_all("Academic Term", pluck="name", limit=1)
		if not terms:
			self.skipTest("site has no academic terms")
		return terms[0]


class TestAReMarkLandsOnTheSittingItNames(FrappeTestCase):
	"""A course with no approved sheet keeps its marks in Assessment Result, and
	a student can hold two there for one paper — the main sitting and the
	aegrotat that stood in for it.

	The sheet branch of `find_mark` has always filtered on the sitting. The
	Assessment Result branch did not filter on it at all, with `limit=1` and no
	ordering, so one arbitrary row answered for every sitting: a re-mark of one
	paper rewrote the other, and `previous_score`, the audit comment and
	`applied_to_name` all recorded the wrong row.
	"""

	def setUp(self):
		needs_doctype(self, "Assessment Result", "Mark Change")
		self.paper = a_paper_sat_twice()
		if not self.paper:
			self.skipTest("no student on this site has one paper under two sittings")

	def change_for(self, sitting):
		"""Not inserted: `find_mark` reads the document's own fields, and
		inserting would apply a re-mark nobody asked for."""
		return frappe.get_doc(
			{
				"doctype": "Mark Change",
				"student": self.paper["student"],
				"course": self.paper["course"],
				"academic_term": self.paper["academic_term"],
				"assessment_group": self.paper["assessment_group"],
				"sitting": sitting,
				"new_score": 71,
				"reason": "checking which mark this would land on",
			}
		)

	def test_each_sitting_finds_its_own_mark(self):
		for sitting, expected in self.paper["by_sitting"].items():
			found = self.change_for(sitting).find_mark()
			self.assertIsNotNone(found, sitting)
			self.assertEqual(
				found[1], expected["name"], "a {0} re-mark landed elsewhere".format(sitting)
			)
			self.assertEqual(found[2], expected["total_score"])

	def test_the_sittings_do_not_resolve_to_one_record(self):
		"""The bug itself. Both sittings answering with the same row is what let a
		re-mark of one paper overwrite the other."""
		found = {s: self.change_for(s).find_mark()[1] for s in self.paper["by_sitting"]}
		self.assertEqual(
			len(set(found.values())), len(found), "two sittings resolved to one mark: {0}".format(found)
		)

	def test_the_previous_score_recorded_is_the_one_being_replaced(self):
		"""`apply` takes `previous_score` from what `find_mark` returned, so the
		wrong row meant the audit trail named a mark that was never changed."""
		for sitting, expected in self.paper["by_sitting"].items():
			self.assertEqual(self.change_for(sitting).find_mark()[2], expected["total_score"])

	def test_a_sitting_the_student_never_sat_finds_nothing(self):
		"""And is refused on validate rather than landing on a neighbour."""
		unsat = {"Main", "Supplementary", "Aegrotat"} - set(self.paper["by_sitting"])
		if not unsat:
			self.skipTest("that student sat every sitting")

		change = self.change_for(sorted(unsat)[0])
		self.assertIsNone(change.find_mark())
		with self.assertRaises(frappe.ValidationError):
			change.validate_there_is_a_mark_to_change()

	def test_what_it_finds_always_carries_the_sitting_asked_for(self):
		"""Checked through the readers' own resolution, so this cannot pass by
		agreeing with a second opinion about what a sitting is."""
		from education_extension.education_extension.marking import sitting_of

		for sitting in self.paper["by_sitting"]:
			name = self.change_for(sitting).find_mark()[1]
			result = frappe.db.get_value(
				"Assessment Result", name, ["assessment_group", "custom_sitting as sitting"], as_dict=True
			)
			self.assertEqual(
				sitting_of(result), (self.paper["assessment_group"], sitting), name
			)


def a_paper_sat_twice():
	"""One student's paper that exists under more than one sitting, or None.

	Found rather than made. An Assessment Result needs an Assessment Plan behind
	it, so building the pair would mean constructing most of a term to test a
	lookup — and the real records say more about whether the lookup works than
	anything assembled to suit it.
	"""
	rows = frappe.db.sql(
		"""
		select student, course, academic_term, assessment_group, count(*) as sittings
		from `tabAssessment Result`
		where docstatus = 1 and ifnull(custom_sitting, '') != ''
		group by student, course, academic_term, assessment_group
		having sittings > 1
		limit 1
		""",
		as_dict=True,
	)
	if not rows:
		return None

	paper = rows[0]
	by_sitting = {}
	for result in frappe.get_all(
		"Assessment Result",
		filters={
			"student": paper.student,
			"course": paper.course,
			"academic_term": paper.academic_term,
			"assessment_group": paper.assessment_group,
			"docstatus": 1,
		},
		fields=["name", "total_score", "custom_sitting as sitting"],
	):
		by_sitting[result.sitting] = {"name": result.name, "total_score": result.total_score}

	if len(by_sitting) < 2:
		# Two rows under one sitting is a different problem, and not this one.
		return None

	return {
		"student": paper.student,
		"course": paper.course,
		"academic_term": paper.academic_term,
		"assessment_group": paper.assessment_group,
		"by_sitting": by_sitting,
	}


def run_tests(verbosity=2):
	"""Run these from a console, since bench run-tests cannot bootstrap this site.

	Without this nothing in this file ran here: it sits in a doctype folder,
	where `bench run-tests` is the only thing that looks.
	"""
	suite = unittest.TestSuite()
	loader = unittest.TestLoader()
	for case in (TestMarkChange, TestAReMarkLandsOnTheSittingItNames):
		suite.addTests(loader.loadTestsFromTestCase(case))
	return unittest.TextTestRunner(verbosity=verbosity).run(suite)
