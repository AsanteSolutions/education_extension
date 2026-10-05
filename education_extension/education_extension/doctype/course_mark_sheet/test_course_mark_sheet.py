# Copyright (c) 2026, Asante Solutions and contributors
# For license information, please see license.txt

import unittest
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from education_extension.education_extension.doctype.course_mark_sheet.course_mark_sheet import (
	ABSENT,
	AEGROTAT,
	AEGROTAT_COMMENT,
	APPROVED,
	AWAITING_ENTRY,
	CHECKED,
	COURSEWORK,
	IN_ENTRY,
	MARKED,
	MODERATED,
	MODERATION_FLAT,
	MODERATION_LINEAR,
	MODERATION_NONE,
	NOT_MARKED,
	RELEASED,
	SUBMITTED_FOR_CHECKING,
	SUPPLEMENTARY_COMMENT,
	SUPPLEMENTARY_GROUP,
	entry_key,
	moderated_value,
)

# Stops Frappe walking this app link fields into every other app; see the
# note beside the list.
from education_extension.education_extension.testing import (  # noqa: F401
	IGNORE_TEST_RECORD_DEPENDENCIES,
)


def sheet_with(entries, moderation_method=MODERATION_NONE):
	"""A sheet held in memory. Enough for the parts that are pure arithmetic,
	without needing a course, a scheme or a term to exist."""
	doc = frappe.get_doc(
		{
			"doctype": "Course Mark Sheet",
			"course": "TEST1101 - Test Course",
			"sitting": "Main",
			"moderation_method": moderation_method,
			"entries": [
				{
					"student": student,
					"assessment_group": group,
					"status": status,
					"raw_score": raw,
					"moderated_score": moderated,
					"maximum_score": 100,
				}
				for student, group, status, raw, moderated in entries
			],
		}
	)
	return doc


class TestCourseMarkSheet(FrappeTestCase):
	def test_an_unmarked_assessment_has_no_score(self):
		"""Zero is a mark. Not having one is not, which a Float alone cannot say."""
		doc = sheet_with([("S1", "Test 1", NOT_MARKED, 0, 0)])
		self.assertIsNone(doc.effective_score(doc.entries[0]))

	def test_a_zero_is_a_score(self):
		doc = sheet_with([("S1", "Test 1", MARKED, 0, 0)])
		self.assertEqual(doc.effective_score(doc.entries[0]), 0)

	def test_an_absent_assessment_has_no_score(self):
		doc = sheet_with([("S1", "Test 1", ABSENT, 0, 0)])
		self.assertIsNone(doc.effective_score(doc.entries[0]))

	def test_the_moderated_score_counts_while_moderation_stands(self):
		doc = sheet_with([("S1", "Test 1", MARKED, 60, 65)], moderation_method=MODERATION_FLAT)
		self.assertEqual(doc.effective_score(doc.entries[0]), 65)

	def test_the_raw_score_counts_once_moderation_is_cleared(self):
		doc = sheet_with([("S1", "Test 1", MARKED, 60, 65)], moderation_method=MODERATION_NONE)
		self.assertEqual(doc.effective_score(doc.entries[0]), 60)

	def test_marks_leaves_out_what_has_no_score(self):
		doc = sheet_with(
			[
				("S1", "Test 1", MARKED, 60, 0),
				("S1", "Test 2", ABSENT, 0, 0),
				("S2", "Test 1", NOT_MARKED, 0, 0),
			]
		)
		marks = doc.marks()
		self.assertEqual(len(marks), 1)
		self.assertEqual(marks[0]["student"], "S1")
		self.assertEqual(marks[0]["total_score"], 60)

	def test_a_score_beyond_the_maximum_is_rejected(self):
		doc = sheet_with([("S1", "Test 1", MARKED, 140, 0)])
		self.assertRaises(frappe.ValidationError, doc.validate_entries)

	def test_a_negative_score_is_rejected(self):
		doc = sheet_with([("S1", "Test 1", MARKED, -1, 0)])
		self.assertRaises(frappe.ValidationError, doc.validate_entries)

	def test_a_student_cannot_have_two_rows_for_one_assessment(self):
		doc = sheet_with(
			[("S1", "Test 1", MARKED, 60, 0), ("S1", "Test 1", MARKED, 70, 0)]
		)
		self.assertRaises(frappe.ValidationError, doc.validate_entries)

	def test_an_unmarked_row_blocks_approval(self):
		doc = sheet_with([("S1", "Test 1", MARKED, 60, 0), ("S2", "Test 1", NOT_MARKED, 0, 0)])
		self.assertRaises(frappe.ValidationError, doc.validate_every_mark_accounted_for)

	def test_an_absent_row_does_not_block_approval(self):
		"""Absent is a decision that has been made; unmarked is one that has not."""
		doc = sheet_with([("S1", "Test 1", MARKED, 60, 0), ("S2", "Test 1", ABSENT, 0, 0)])
		doc.validate_every_mark_accounted_for()

	def test_moderation_summary_reports_the_shift(self):
		doc = sheet_with(
			[("S1", "Test 1", MARKED, 50, 55), ("S2", "Test 1", MARKED, 70, 75)],
			moderation_method=MODERATION_FLAT,
		)
		summary = doc.moderation_summary()
		self.assertEqual(summary["adjusted"], 2)
		self.assertEqual(summary["average_before"], 60)
		self.assertEqual(summary["average_after"], 65)

	def test_scaling_cannot_push_a_mark_past_the_maximum(self):
		self.assertEqual(moderated_value(98, 100, MODERATION_LINEAR, 1.5), 100)

	def test_a_deduction_cannot_push_a_mark_below_zero(self):
		self.assertEqual(moderated_value(3, 100, MODERATION_FLAT, -10), 0)

	def test_scaling_and_adding_do_what_they_say(self):
		self.assertEqual(moderated_value(60, 100, MODERATION_LINEAR, 1.1), 66)
		self.assertEqual(moderated_value(60, 100, MODERATION_FLAT, 5), 65)

	def test_a_cell_is_identified_the_same_however_it_arrives(self):
		"""The browser posts a numeric-looking student id as a number. Keyed on the
		raw values it would match no row, and the mark would be dropped as one the
		sheet does not have — a save that saves nothing and reports success."""
		self.assertEqual(entry_key(20240549, "Test 1"), entry_key("20240549", "Test 1"))
		self.assertEqual(entry_key("20240549", "Test 1"), ("20240549", "Test 1"))

	def test_an_assessment_named_like_a_number_is_keyed_the_same_way(self):
		self.assertEqual(entry_key("S1", 1), entry_key("S1", "1"))

	def test_a_sitting_the_sheet_does_not_know_will_not_generate(self):
		"""Rather than quietly producing an empty sheet, or the main sitting's roll."""
		doc = sheet_with([])
		doc.sitting = "Something Else"
		self.assertRaises(frappe.ValidationError, doc.wanted_entries)

	def test_a_supplementary_is_one_paper_for_the_course(self):
		"""Not a re-sit of each assessment, which is why the report gives it a
		single column."""
		self.assertEqual(SUPPLEMENTARY_GROUP, "Supplementary Exam")
		self.assertEqual(SUPPLEMENTARY_COMMENT, "SUPP")

	def test_a_sheet_reports_the_sitting_its_marks_belong_to(self):
		"""Merging an aegrotat sheet into the main one relies on this: without the
		sitting on each mark, the main one would win and the aegrotat paper would
		count for nothing."""
		doc = sheet_with([("S1", "Theory Exam", MARKED, 60, 0)])
		doc.sitting = AEGROTAT
		self.assertEqual(doc.marks()[0]["sitting"], AEGROTAT)

	def test_a_missed_test_scores_nothing_rather_than_leaving_a_hole(self):
		"""There is no re-sitting for a test, so an absence from one is a zero and
		the semester mark can still be worked out."""
		doc = sheet_with([("S1", "Test 1", ABSENT, 0, 0)])
		with patch.object(doc, "assessment_components", return_value={"Test 1": COURSEWORK}):
			marks = doc.marks()

		self.assertEqual(len(marks), 1)
		self.assertEqual(marks[0]["total_score"], 0)

	def test_a_missed_exam_leaves_the_course_incomplete(self):
		"""It waits for an aegrotat paper rather than being scored zero, because
		one may still be sat."""
		doc = sheet_with([("S1", "Theory Exam", ABSENT, 0, 0)])
		with patch.object(doc, "assessment_components", return_value={"Theory Exam": "Examination"}):
			self.assertEqual(doc.marks(), [])

	def test_an_aegrotat_needs_the_comment_not_just_an_absence(self):
		"""A student can miss a paper without producing the documentation that
		entitles them to sit it again."""
		self.assertEqual(AEGROTAT_COMMENT, "AEGRO")

	def test_approval_needs_a_comment_for_every_student(self):
		"""A result is a mark and what QA made of it. Approving with comments
		missing signs off half of one."""
		doc = sheet_with([("S1", "Test 1", MARKED, 60, 0), ("S2", "Test 1", MARKED, 55, 0)])
		doc.course, doc.academic_term = "no-such-course", "no-such-term"

		# No comments exist for that course, so every student is outstanding.
		with self.assertRaises(frappe.ValidationError):
			doc.validate_every_student_has_a_comment()

	def test_the_supplementary_gate_looks_at_supplementary_comments(self):
		"""A student can carry SUPP on the main sheet and still have nothing said
		about how the supplementary itself went."""
		doc = sheet_with([("S1", "Supplementary Exam", MARKED, 52, 0)])
		doc.sitting = "Supplementary"
		doc.course, doc.academic_term = "no-such-course", "no-such-term"

		with self.assertRaises(frappe.ValidationError):
			doc.validate_every_student_has_a_comment()


class TestApprovalCannotBeSkipped(FrappeTestCase):
	"""Submission is the approval step, so it has to have come from one."""

	def sheet_in(self, state):
		doc = sheet_with([("S1", "Test 1", MARKED, 60, 0)])
		doc.workflow_state = state
		return doc

	def test_a_bare_submit_is_refused(self):
		"""Frappe validates a workflow transition, not a state: a plain submit
		changes no state field, so nothing is compared and nothing objects. It
		then relabels the document to whichever state carries docstatus 1, so
		the sheet ends up reading Approved with checking never done."""
		for state in (AWAITING_ENTRY, IN_ENTRY, SUBMITTED_FOR_CHECKING, CHECKED, MODERATED):
			with self.subTest(state=state):
				with self.assertRaises(frappe.ValidationError):
					self.sheet_in(state).validate_it_came_through_the_workflow()

	def test_the_approve_action_is_allowed(self):
		"""It sets the state before saving, so by here it already reads Approved."""
		for state in (APPROVED, RELEASED):
			with self.subTest(state=state):
				self.sheet_in(state).validate_it_came_through_the_workflow()


class TestModerationIsNotEditable(FrappeTestCase):
	"""The adjusted score is a mark too, and it sat outside the marks check."""

	def pair(self, moderated_now, moderated_before):
		doc = sheet_with([("S1", "Test 1", MARKED, 60, moderated_now)], MODERATION_FLAT)
		previous = sheet_with([("S1", "Test 1", MARKED, 60, moderated_before)], MODERATION_FLAT)
		doc.workflow_state = CHECKED
		return doc, previous

	def test_an_edited_moderated_score_is_refused(self):
		"""Writing the field straight onto the document needs no more than the
		write permission an Instructor already holds."""
		doc, previous = self.pair(moderated_now=90, moderated_before=66)

		with patch.object(type(doc), "get_doc_before_save", return_value=previous):
			with self.assertRaises(frappe.ValidationError):
				doc.validate_moderation_came_from_the_moderation_step()

	def test_the_moderation_step_itself_is_allowed(self):
		"""apply_moderation and clear_moderation set the flag before saving."""
		doc, previous = self.pair(moderated_now=90, moderated_before=66)
		doc.flags.moderating = True

		with patch.object(type(doc), "get_doc_before_save", return_value=previous):
			doc.validate_moderation_came_from_the_moderation_step()

	def test_an_unchanged_sheet_passes(self):
		doc, previous = self.pair(moderated_now=66, moderated_before=66)

		with patch.object(type(doc), "get_doc_before_save", return_value=previous):
			doc.validate_moderation_came_from_the_moderation_step()


class TestCorrectingAMarkTakesTheModerationOff(FrappeTestCase):
	"""An adjustment is worked out from the marks and approved as a pair with
	them, so a mark changing afterwards leaves it describing numbers that are no
	longer there.

	Nothing on the way back to the lecturer takes it off -- `return_for_correction`
	moves the state and leaves the moderation standing -- so without this the
	corrected mark went in and `effective_score` went on returning the old
	moderated figure, all the way through approval.
	"""

	def returned_sheet(self):
		"""Moderated, then sent back to the lecturer: the state the bug needs."""
		doc = sheet_with(
			[("S1", "Test 1", MARKED, 60, 65), ("S2", "Test 1", MARKED, 70, 75)],
			moderation_method=MODERATION_FLAT,
		)
		doc.workflow_state = IN_ENTRY
		doc.moderation_value = 5
		doc.moderation_reason = "The paper was harder than usual."
		doc.moderated_by = "qa@example.com"
		doc.moderated_on = "2026-10-01 09:00:00"
		return doc

	def enter(self, doc, changes):
		"""`save_marks` with the two writes stubbed out, so the decision it makes
		can be checked without a course, a scheme and a term existing."""
		with patch.object(type(doc), "save", lambda self: None):
			with patch.object(type(doc), "add_comment", lambda self, *a, **k: None):
				return doc.save_marks(changes)

	def mark(self, student, score):
		return [{"student": student, "assessment_group": "Test 1", "status": MARKED, "raw_score": score}]

	def test_a_corrected_mark_is_the_mark_that_counts(self):
		doc = self.returned_sheet()
		self.enter(doc, self.mark("S1", 70))

		self.assertEqual(doc.entries[0].raw_score, 70)
		self.assertEqual(
			doc.effective_score(doc.entries[0]),
			70,
			"the sheet would have been approved on the old moderated score",
		)

	def test_the_whole_adjustment_comes_off_and_not_just_the_row_touched(self):
		"""A flat adjustment applies to the cohort, so half an adjustment is not
		a thing the sheet can mean."""
		doc = self.returned_sheet()
		self.enter(doc, self.mark("S1", 70))

		self.assertEqual(doc.moderation_method, MODERATION_NONE)
		self.assertEqual(doc.effective_score(doc.entries[1]), 70, "S2 kept its moderated score")
		self.assertTrue(all(entry.moderated_score == 0 for entry in doc.entries))

	def test_everything_recording_the_adjustment_is_cleared(self):
		"""Not just the scores: a reason and an author left behind would say the
		sheet was moderated when it is not."""
		doc = self.returned_sheet()
		self.enter(doc, self.mark("S1", 70))

		for field in ("moderation_value", "moderation_reason", "moderated_by", "moderated_on"):
			self.assertFalse(doc.get(field), field)

	def test_it_says_so(self):
		"""A moderation that disappears quietly is how a sheet gets approved by
		someone who thinks it is still adjusted."""
		self.assertTrue(self.enter(self.returned_sheet(), self.mark("S1", 70))["moderation_withdrawn"])

	def test_a_sheet_that_was_never_moderated_is_untouched(self):
		doc = sheet_with([("S1", "Test 1", MARKED, 60, 0)])
		doc.workflow_state = IN_ENTRY

		result = self.enter(doc, self.mark("S1", 70))

		self.assertFalse(result["moderation_withdrawn"])
		self.assertEqual(doc.moderation_method, MODERATION_NONE)

	def test_a_save_that_changes_nothing_leaves_the_adjustment_alone(self):
		"""Opening a returned sheet and saving is not a correction."""
		doc = self.returned_sheet()

		result = self.enter(doc, [])

		self.assertFalse(result["moderation_withdrawn"])
		self.assertEqual(doc.moderation_method, MODERATION_FLAT)
		self.assertEqual(doc.effective_score(doc.entries[0]), 65)

	def test_a_cell_the_sheet_does_not_know_is_not_a_correction_either(self):
		doc = self.returned_sheet()

		result = self.enter(doc, [
			{"student": "nobody", "assessment_group": "Test 1", "status": MARKED, "raw_score": 99}
		])

		self.assertEqual((result["applied"], result["ignored"]), (0, 1))
		self.assertFalse(result["moderation_withdrawn"])
		self.assertEqual(doc.moderation_method, MODERATION_FLAT)

	def test_the_moderation_guard_does_not_refuse_the_save(self):
		"""The moderated scores change here, which is exactly what that guard
		normally refuses -- so this path has to be marked as the moderation step.

		It also closes a trap that was there before: marking a student absent
		makes `validate_entries` zero that row's moderated score, which tripped
		the guard and failed the save with a message about Moderate Marks.
		"""
		for changes in (
			self.mark("S1", 70),
			[{"student": "S1", "assessment_group": "Test 1", "status": ABSENT, "raw_score": 0}],
		):
			doc = self.returned_sheet()
			previous = self.returned_sheet()
			self.enter(doc, changes)

			with patch.object(type(doc), "get_doc_before_save", return_value=previous):
				doc.validate_moderation_came_from_the_moderation_step()

	def test_an_ordinary_mark_save_still_cannot_touch_a_moderated_score(self):
		"""The flag is set only where the adjustment is being withdrawn, so the
		guard still covers everything else."""
		doc = sheet_with([("S1", "Test 1", MARKED, 60, 0)])
		doc.workflow_state = IN_ENTRY
		self.enter(doc, self.mark("S1", 70))

		self.assertFalse(doc.flags.get("moderating"))


def run_tests(verbosity=2):
	"""Run these from a console, since bench run-tests cannot bootstrap this site.

	Without this nothing in this file ran here at all: it sits in a doctype
	folder, which is where Frappe looks and where `bench run-tests` is the only
	thing that looks.
	"""
	suite = unittest.TestSuite()
	loader = unittest.TestLoader()
	for case in (
		TestCourseMarkSheet,
		TestApprovalCannotBeSkipped,
		TestModerationIsNotEditable,
		TestCorrectingAMarkTakesTheModerationOff,
	):
		suite.addTests(loader.loadTestsFromTestCase(case))
	return unittest.TextTestRunner(verbosity=verbosity).run(suite)
