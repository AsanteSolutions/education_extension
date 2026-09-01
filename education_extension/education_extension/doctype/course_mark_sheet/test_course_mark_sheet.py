# Copyright (c) 2026, Asante Solutions and contributors
# For license information, please see license.txt

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from education_extension.education_extension.doctype.course_mark_sheet.course_mark_sheet import (
	ABSENT,
	AEGROTAT,
	AEGROTAT_COMMENT,
	COURSEWORK,
	SPECIAL,
	SUPPLEMENTARY_COMMENT,
	SUPPLEMENTARY_GROUP,
	MARKED,
	MODERATION_FLAT,
	MODERATION_LINEAR,
	MODERATION_NONE,
	NOT_MARKED,
	entry_key,
	moderated_value,
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

	def test_a_special_sitting_will_not_generate(self):
		"""Special covers both kinds of re-sitting, so it cannot say who is sitting
		what. The sheet has to be opened as the one it actually is."""
		doc = sheet_with([])
		doc.sitting = SPECIAL
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
