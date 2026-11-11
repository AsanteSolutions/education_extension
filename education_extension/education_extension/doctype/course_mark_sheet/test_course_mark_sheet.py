# Copyright (c) 2026, Asante Solutions and contributors
# For license information, please see license.txt

import json
import unittest
from unittest.mock import patch

import frappe
from frappe.handler import run_doc_method
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
		self.assertEqual(entry_key(20990549, "Test 1"), entry_key("20990549", "Test 1"))
		self.assertEqual(entry_key("20990549", "Test 1"), ("20990549", "Test 1"))

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


class TestTheEntryGridShowsWhatTheMarksComeTo(FrappeTestCase):
	"""The DP and final mark beside the marks being entered.

	Read-only, and worked out by the server: the weightings live in the course
	mark scheme, and a copy of them in the browser is how the portal's grades
	page came to show a different number from the printed report.
	"""

	def setUp(self):
		sheets = frappe.get_all(
			"Course Mark Sheet",
			filters={"sitting": "Main"},
			pluck="name",
			order_by="creation desc",
		)
		self.sheet = None
		for name in sheets:
			doc = frappe.get_doc("Course Mark Sheet", name)
			if any(entry.status == "Marked" for entry in doc.entries):
				self.sheet = doc
				break
		if not self.sheet:
			self.skipTest("this site has no marked main sheet")

	def tearDown(self):
		frappe.db.rollback()

	def test_it_agrees_with_what_qa_will_read(self):
		"""The point of asking the server rather than working it out twice."""
		totals = self.sheet.mark_totals()
		review = {row["student"]: row for row in self.sheet.qa_review()["rows"]}

		self.assertTrue(totals, "no totals came back")
		for student, row in totals.items():
			self.assertEqual(row["dp"], review[student]["dp"], student)
			self.assertEqual(row["final_mark"], review[student]["final_mark"], student)

	def test_an_unsaved_mark_moves_the_total(self):
		"""What the lecturer is typing has to count, or the number is stale."""
		entry = next(e for e in self.sheet.entries if e.status == "Marked" and e.raw_score)
		before = self.sheet.mark_totals()[entry.student]

		fresh = frappe.get_doc("Course Mark Sheet", self.sheet.name)
		after = fresh.mark_totals(
			[
				{
					"student": entry.student,
					"assessment_group": entry.assessment_group,
					"status": "Marked",
					"raw_score": 0,
				}
			]
		)[entry.student]

		self.assertNotEqual(after["dp"], before["dp"], "the pending mark was not counted")

	def test_asking_writes_nothing(self):
		"""It is a preview. The marks are saved by Save Marks and nothing else."""
		entry = next(e for e in self.sheet.entries if e.status == "Marked" and e.raw_score)
		was = frappe.db.get_value("Course Mark Sheet Entry", entry.name, "raw_score")

		fresh = frappe.get_doc("Course Mark Sheet", self.sheet.name)
		fresh.mark_totals(
			[
				{
					"student": entry.student,
					"assessment_group": entry.assessment_group,
					"status": "Marked",
					"raw_score": 0,
				}
			]
		)

		self.assertEqual(
			frappe.db.get_value("Course Mark Sheet Entry", entry.name, "raw_score"),
			was,
			"a preview wrote to the sheet",
		)

	def test_a_supplementary_sheet_has_no_course_total(self):
		"""One paper standing in for an exam is not a course mark."""
		name = frappe.db.get_value("Course Mark Sheet", {"sitting": "Supplementary"}, "name")
		if not name:
			self.skipTest("this site has no supplementary sheet")

		self.assertEqual(frappe.get_doc("Course Mark Sheet", name).mark_totals(), {})


class TestSigningOffTheSemesterMark(FrappeTestCase):
	"""The coursework half, signed off before the exams are marked.

	Exams are marked weeks after coursework, so approving the whole sheet cannot
	release a semester mark in time for the exam room. The coursework is signed
	off on its own instead -- and only it travels on that signature.
	"""

	def setUp(self):
		name = None
		for candidate in frappe.get_all(
			"Course Mark Sheet",
			filters={"sitting": "Main", "docstatus": 0},
			pluck="name",
			order_by="creation desc",
		):
			doc = frappe.get_doc("Course Mark Sheet", candidate)
			if doc.entries and not doc.unmarked_coursework():
				name = candidate
				break
		if not name:
			self.skipTest("no unapproved main sheet has its coursework marked")

		frappe.db.savepoint("semester_mark_test")
		self.sheet = frappe.get_doc("Course Mark Sheet", name)
		# Started from a known state rather than whatever the site happens to
		# hold: a sheet left signed off by anything else would make half of
		# these assert about the wrong thing.
		if self.sheet.semester_mark_approved:
			self.sheet.withdraw_semester_mark()
		self.student = self.sheet.entries[0].student
		self.components = self.sheet.assessment_components()

	def tearDown(self):
		frappe.set_user("Administrator")
		# To the savepoint, not just `rollback()`. These tests sign off and
		# cancel real records, and a bare rollback left both on the site.
		frappe.db.rollback(save_point="semester_mark_test")

	def seen_by_students(self):
		from education_extension.education_extension.marking import get_assessment_results

		rows = get_assessment_results(self.student, self.sheet.academic_term).get(
			self.sheet.course, []
		)
		return {row["assessment_group"] for row in rows}

	def test_nothing_reaches_students_before_it_is_signed_off(self):
		self.assertEqual(self.seen_by_students(), set())

	def test_the_coursework_reaches_students_once_it_is(self):
		self.sheet.approve_semester_mark()
		seen = self.seen_by_students()

		self.assertTrue(seen, "the coursework did not reach the student")
		for group in seen:
			self.assertEqual(
				self.components.get(group),
				"Coursework",
				"{0} is not coursework and should have waited for approval".format(group),
			)

	def test_the_exam_marks_do_not_travel_on_it(self):
		"""The one that matters. A signature on the coursework is not a
		signature on marks nobody has checked.

		The exam marks are entered first, on purpose. A sheet whose exams are
		still blank has nothing to leak, so asserting against one passes however
		wide the rule is -- which is exactly what it did before this line.
		"""
		exams = [
			entry
			for entry in self.sheet.entries
			if self.components.get(entry.assessment_group) != "Coursework"
		]
		if not exams:
			self.skipTest("that sheet carries no examination assessments")

		for entry in exams:
			entry.status = "Marked"
			entry.raw_score = 40
		self.sheet.flags.ignore_validate_update_after_submit = True
		self.sheet.save()

		self.sheet.approve_semester_mark()
		seen = self.seen_by_students()
		self.assertTrue(seen, "the coursework did not reach the student")
		self.assertEqual(
			seen & {entry.assessment_group for entry in exams},
			set(),
			"an exam mark reached a student on the semester mark signature",
		)

	def test_it_records_who_signed_it_and_when(self):
		self.sheet.approve_semester_mark()
		self.sheet.reload()

		self.assertTrue(self.sheet.semester_mark_approved)
		self.assertEqual(self.sheet.semester_mark_approved_by, frappe.session.user)
		self.assertTrue(self.sheet.semester_mark_approved_on)

	def test_it_is_refused_while_coursework_is_outstanding(self):
		"""A semester mark worked out from half the marks is not the semester
		mark, and a student would be shown it as though it were."""
		entry = next(
			e
			for e in self.sheet.entries
			if self.components.get(e.assessment_group) == "Coursework"
		)
		entry.status = "Not Marked"
		entry.raw_score = 0
		self.sheet.flags.ignore_validate_update_after_submit = True
		self.sheet.save()

		with self.assertRaises(frappe.ValidationError):
			self.sheet.approve_semester_mark()

	def test_changing_a_coursework_mark_takes_the_sign_off_off(self):
		"""A student may already have seen it, so it must not change underneath
		them without the signature going too."""
		self.sheet.approve_semester_mark()
		entry = next(
			e
			for e in self.sheet.entries
			if self.components.get(e.assessment_group) == "Coursework"
		)

		self.sheet.workflow_state = "In Entry"
		result = self.sheet.save_marks(
			[
				{
					"student": entry.student,
					"assessment_group": entry.assessment_group,
					"status": "Marked",
					"raw_score": 1,
				}
			]
		)

		self.assertTrue(result["semester_mark_withdrawn"])
		self.sheet.reload()
		self.assertFalse(self.sheet.semester_mark_approved)
		self.assertEqual(self.seen_by_students(), set(), "the marks stayed visible")

	def entry_of(self, component):
		return next(
			e for e in self.sheet.entries if self.components.get(e.assessment_group) == component
		)

	def test_entering_exam_marks_leaves_it_on(self):
		"""The signature is given so students can see the DP while the exams are
		marked. Marking them is not a reason to take it away."""
		self.sheet.approve_semester_mark()
		exam = self.entry_of("Examination")

		self.sheet.workflow_state = "In Entry"
		result = self.sheet.save_marks(
			[
				{
					"student": exam.student,
					"assessment_group": exam.assessment_group,
					"status": "Marked",
					"raw_score": 1,
				}
			]
		)

		self.assertFalse(result["semester_mark_withdrawn"])
		self.sheet.reload()
		self.assertTrue(self.sheet.semester_mark_approved)

	def test_a_coursework_cell_sent_back_unchanged_leaves_it_on(self):
		"""The grid sends every cell that fired a change, including one typed over
		and put back. Riding along with a batch of exam marks, that took the DP
		away from students and said a coursework mark had changed when none had."""
		self.sheet.approve_semester_mark()
		coursework = self.entry_of("Coursework")
		exam = self.entry_of("Examination")

		self.sheet.workflow_state = "In Entry"
		result = self.sheet.save_marks(
			[
				{
					"student": coursework.student,
					"assessment_group": coursework.assessment_group,
					"status": coursework.status,
					"raw_score": coursework.raw_score,
				},
				{
					"student": exam.student,
					"assessment_group": exam.assessment_group,
					"status": "Marked",
					"raw_score": 1,
				},
			]
		)

		self.assertFalse(result["semester_mark_withdrawn"])
		self.sheet.reload()
		self.assertTrue(self.sheet.semester_mark_approved)

	def test_withdrawing_takes_it_back_from_students(self):
		self.sheet.approve_semester_mark()
		self.assertTrue(self.seen_by_students())

		self.sheet.withdraw_semester_mark()
		self.assertEqual(self.seen_by_students(), set())


class TestCorrectingAMarkSchemeAfterMarkingHasStarted(FrappeTestCase):
	"""A scheme is submittable, so correcting one means cancelling and amending.

	That leaves a new scheme and the sheet stamped with the old, now cancelled,
	one -- and the stamp is read-only, so nothing could move it. The sheet went
	on being marked against a scheme somebody had already withdrawn, and the
	marks already entered were the reason not to start again.
	"""

	def setUp(self):
		name = None
		for candidate in frappe.get_all(
			"Course Mark Sheet",
			filters={"sitting": "Main", "docstatus": 0},
			pluck="name",
			order_by="creation desc",
		):
			doc = frappe.get_doc("Course Mark Sheet", candidate)
			if doc.mark_scheme and any(e.status != "Not Marked" for e in doc.entries):
				name = candidate
				break
		if not name:
			self.skipTest("no unapproved main sheet has marks on it")

		frappe.db.savepoint("scheme_change_test")
		self.sheet = frappe.get_doc("Course Mark Sheet", name)
		self.sheet.workflow_state = "In Entry"
		self.marks = {
			(e.student, e.assessment_group): (e.status, e.raw_score)
			for e in self.sheet.entries
			if e.status != "Not Marked"
		}

	def tearDown(self):
		frappe.set_user("Administrator")
		# Cancelling a scheme is not undone by a bare rollback here: an earlier
		# run of these tests left a live course pointing at a cancelled scheme.
		frappe.db.rollback(save_point="scheme_change_test")

	def correct_the_scheme(self, drop=None, reweight=5):
		"""Cancel and amend, which is the only way the doctype allows.

		The weightings have to keep totalling 100 or the scheme refuses to
		submit, so weight is moved between criteria rather than conjured: that
		is what correcting a real mistake looks like.
		"""
		scheme = frappe.get_doc("Course Mark Scheme", self.sheet.mark_scheme)
		scheme.cancel()
		fixed = frappe.copy_doc(scheme)
		fixed.amended_from = scheme.name
		fixed.docstatus = 0

		if drop:
			freed = sum(
				row.weightage or 0 for row in fixed.criteria if row.assessment_group == drop
			)
			fixed.criteria = [c for c in fixed.criteria if c.assessment_group != drop]
			fixed.criteria[0].weightage = (fixed.criteria[0].weightage or 0) + freed
		elif reweight and len(fixed.criteria) > 1:
			# Taken off one and put on another, so the total does not move.
			moved = min(reweight, fixed.criteria[1].weightage or 0)
			fixed.criteria[0].weightage = (fixed.criteria[0].weightage or 0) + moved
			fixed.criteria[1].weightage = (fixed.criteria[1].weightage or 0) - moved

		for position, row in enumerate(fixed.criteria, start=1):
			row.idx = position
		fixed.insert()
		fixed.submit()
		self.sheet.reload()
		return fixed

	def test_the_sheet_is_left_on_a_cancelled_scheme(self):
		"""The shape of the problem, asserted so the fix cannot be read as
		solving something that was never broken."""
		fixed = self.correct_the_scheme()

		self.assertNotEqual(self.sheet.mark_scheme, fixed.name)
		self.assertEqual(
			frappe.db.get_value("Course Mark Scheme", self.sheet.mark_scheme, "docstatus"),
			2,
			"the stamped scheme should be the cancelled one",
		)

	def test_it_offers_the_move_and_says_what_it_costs(self):
		dropped = self.sheet.entries[0].assessment_group
		fixed = self.correct_the_scheme(drop=dropped)

		change = self.sheet.scheme_change()
		self.assertEqual(change["stamped"], self.sheet.mark_scheme)
		self.assertEqual(change["current"], fixed.name)
		self.assertIn(dropped, change["removed"])
		self.assertIn(dropped, change["marks_lost"], "a mark about to be lost was not named")

	def test_nothing_is_offered_when_the_scheme_has_not_moved(self):
		self.assertIsNone(self.sheet.scheme_change())

	def test_the_marks_already_entered_survive_the_move(self):
		"""The whole point. Correcting a scheme must not cost a term of marking."""
		self.correct_the_scheme()
		self.sheet.restamp_scheme()
		self.sheet.reload()

		kept = {
			(e.student, e.assessment_group): (e.status, e.raw_score)
			for e in self.sheet.entries
			if e.status != "Not Marked"
		}
		self.assertEqual(kept, self.marks)

	def test_the_sheet_ends_up_on_the_live_scheme(self):
		fixed = self.correct_the_scheme()
		self.sheet.restamp_scheme()
		self.sheet.reload()

		self.assertEqual(self.sheet.mark_scheme, fixed.name)
		self.assertEqual(
			frappe.db.get_value("Course Mark Scheme", self.sheet.mark_scheme, "docstatus"), 1
		)

	def test_a_dropped_assessment_leaves_with_its_marks(self):
		dropped = self.sheet.entries[0].assessment_group
		self.correct_the_scheme(drop=dropped)
		self.sheet.restamp_scheme()
		self.sheet.reload()

		self.assertFalse([e for e in self.sheet.entries if e.assessment_group == dropped])
		survivors = {k: v for k, v in self.marks.items() if k[1] != dropped}
		kept = {
			(e.student, e.assessment_group): (e.status, e.raw_score)
			for e in self.sheet.entries
			if e.status != "Not Marked"
		}
		self.assertEqual(kept, survivors, "the move took marks it should have kept")

	def test_a_semester_mark_signed_off_under_the_old_scheme_comes_off(self):
		"""It was given against weightings that no longer apply."""
		if self.sheet.unmarked_coursework():
			self.skipTest("that sheet cannot be signed off yet")
		if self.sheet.semester_mark_approved:
			self.sheet.withdraw_semester_mark()
		self.sheet.approve_semester_mark()
		self.correct_the_scheme()

		result = self.sheet.restamp_scheme()
		self.sheet.reload()
		self.assertTrue(result["semester_mark_withdrawn"])
		self.assertFalse(self.sheet.semester_mark_approved)

	def test_it_is_refused_once_the_sheet_has_left_the_lecturer(self):
		"""Checking and moderation were done against the stamped scheme, so the
		sheet comes back for correction first rather than changing underneath
		whoever is reviewing it."""
		self.correct_the_scheme()
		self.sheet.workflow_state = "Submitted for Checking"

		with self.assertRaises(frappe.ValidationError):
			self.sheet.restamp_scheme()


class TestThePrintedMarkSheet(FrappeTestCase):
	"""The sheet on paper, laid out the way it was marked.

	The standard print format walks the child table: on a course of seventy
	students across eight assessments it prints 561 rows of one mark each,
	629KB, and the student number does not appear on it anywhere. Nobody can
	check, sign or file that. The printed grid is the entry grid -- students
	down, assessments across -- and it reads its totals from `mark_totals`, so
	the paper and the screen cannot come to different numbers.
	"""

	PRINT_FORMAT = "Course Mark Sheet Grid"

	def setUp(self):
		sheets = frappe.get_all(
			"Course Mark Sheet",
			filters={"sitting": "Main"},
			pluck="name",
			order_by="creation desc",
		)
		# More than one of each, because a sheet with a single student and a
		# single assessment is not a grid and would let the shape tests pass
		# without showing anything.
		self.sheet = None
		for name in sheets:
			doc = frappe.get_doc("Course Mark Sheet", name)
			if (
				any(entry.status == MARKED for entry in doc.entries)
				and len({entry.student for entry in doc.entries}) > 1
				and len({entry.assessment_group for entry in doc.entries}) > 1
			):
				self.sheet = doc
				break
		if not self.sheet:
			self.skipTest("this site has no marked main sheet with marks across a grid")

	def tearDown(self):
		frappe.db.rollback()

	def test_a_row_per_student_and_a_column_per_assessment(self):
		"""The shape, which is the whole point of printing it this way."""
		grid = self.sheet.mark_grid()
		students = {entry.student for entry in self.sheet.entries}
		assessments = {entry.assessment_group for entry in self.sheet.entries}

		self.assertTrue(len(students) > 1 and len(assessments) > 1, "not a grid")
		self.assertEqual(len(grid["rows"]), len(students))
		self.assertEqual(
			{column["assessment_group"] for column in grid["assessments"]}, assessments
		)
		for row in grid["rows"]:
			self.assertEqual(len(row["cells"]), len(grid["assessments"]), row["student"])

	def test_the_rows_are_in_the_order_the_grid_shows_them(self):
		"""A printed sheet that is sorted differently from the screen it was
		checked against is a second sheet, not a copy of this one."""
		grid = self.sheet.mark_grid()

		on_screen = []
		for entry in self.sheet.entries:
			if entry.student not in on_screen:
				on_screen.append(entry.student)

		self.assertEqual([row["student"] for row in grid["rows"]], on_screen)

	def test_the_printed_totals_are_the_ones_qa_will_read(self):
		"""Read from `mark_totals` rather than worked out again. The weightings
		live in the course mark scheme, and a second copy of them is how the
		portal's grades page came to disagree with the printed report."""
		grid = self.sheet.mark_grid()
		totals = self.sheet.mark_totals()

		self.assertFalse(grid["totals_failed"], "the totals could not be worked out")
		self.assertTrue(totals, "no totals came back")
		for row in grid["rows"]:
			self.assertEqual(row["dp"], totals[row["student"]]["dp"], row["student"])
			self.assertEqual(
				row["final_mark"], totals[row["student"]]["final_mark"], row["student"]
			)

	def test_a_supplementary_sheet_prints_no_course_total(self):
		"""One paper standing in for an exam is not a course mark."""
		name = frappe.db.get_value("Course Mark Sheet", {"sitting": "Supplementary"}, "name")
		if not name:
			self.skipTest("this site has no supplementary sheet")

		grid = frappe.get_doc("Course Mark Sheet", name).mark_grid()
		self.assertFalse(grid["totals_apply"])

	def test_the_format_prints_every_student_on_the_sheet(self):
		"""Rendered through Frappe, not read out of the dict: a template that
		loops over the wrong name prints a sheet with no marks on it and raises
		nothing at all."""
		if not frappe.db.exists("Print Format", self.PRINT_FORMAT):
			self.skipTest("the print format is not installed on this site")

		html = frappe.get_print(
			"Course Mark Sheet", self.sheet.name, print_format=self.PRINT_FORMAT
		)

		self.assertIn("COURSE MARK SHEET", html)
		for row in self.sheet.mark_grid()["rows"]:
			self.assertIn(row["student"], html)
		for column in self.sheet.mark_grid()["assessments"]:
			self.assertIn(column["assessment_group"], html)

	def test_the_printed_names_are_the_ones_the_entry_grid_shows(self):
		"""Both come from `student_names`, so the paper and the screen cannot
		name the same class two ways -- which is what they used to do, the grid
		reading the name as recorded and the review beside it surname first."""
		grid = self.sheet.mark_grid()
		names = self.sheet.student_names()

		self.assertTrue(names, "no names came back")
		for row in grid["rows"]:
			self.assertEqual(row["student_name"], names[row["student"]], row["student"])

	def test_the_printed_sheet_and_the_qa_review_agree_on_the_names(self):
		grid = self.sheet.mark_grid()
		review = {row["student"]: row["student_name"] for row in self.sheet.qa_review()["rows"]}

		for row in grid["rows"]:
			self.assertEqual(row["student_name"], review[row["student"]], row["student"])

	def test_the_naming_setting_decides_what_is_printed(self):
		"""Read on sight rather than frozen onto the entry rows when the sheet
		was generated, so changing the setting does not mean regenerating."""
		from education_extension.education_extension.doctype.marking_settings import (
			marking_settings,
		)

		def named(display):
			with patch.object(
				marking_settings, "get_student_name_display", return_value=display
			):
				return {
					row["student"]: row["student_name"]
					for row in frappe.get_doc(
						"Course Mark Sheet", self.sheet.name
					).mark_grid()["rows"]
				}

		surname_first = named("Surname First")
		as_recorded = named("As Recorded")

		# Somebody on the sheet has both halves of a name, or neither form says
		# anything and the test passes without showing that the setting is read.
		self.assertTrue(
			any(surname_first[student] != as_recorded[student] for student in surname_first),
			"no student on this sheet is named differently by the two settings",
		)
		for student, name in as_recorded.items():
			recorded = frappe.db.get_value("Student", student, "student_name")
			if recorded:
				self.assertEqual(name, " ".join(recorded.split()), student)

	def test_a_mark_prints_as_it_was_awarded(self):
		"""Rounding is for a percentage. This is the mark on the paper."""
		doc = sheet_with([("S1", "Test 1", MARKED, 67.5, 0)])
		self.assertEqual(doc.printed_mark(doc.entries[0])["text"], "67.5")

	def test_a_whole_mark_does_not_print_its_decimal(self):
		doc = sheet_with([("S1", "Test 1", MARKED, 50, 0)])
		self.assertEqual(doc.printed_mark(doc.entries[0])["text"], "50")

	def test_a_zero_prints_as_a_zero(self):
		"""Zero is a mark, and an empty box on a mark sheet is not."""
		doc = sheet_with([("S1", "Test 1", MARKED, 0, 0)])
		self.assertEqual(doc.printed_mark(doc.entries[0])["text"], "0")

	def test_an_absence_prints_as_an_absence(self):
		doc = sheet_with([("S1", "Test 1", ABSENT, 0, 0)])
		self.assertEqual(doc.printed_mark(doc.entries[0])["text"], "A")

	def test_an_unmarked_cell_prints_as_an_empty_box(self):
		doc = sheet_with([("S1", "Test 1", NOT_MARKED, 0, 0)])
		cell = doc.printed_mark(doc.entries[0])
		self.assertEqual(cell["text"], "")
		self.assertEqual(cell["status"], NOT_MARKED)

	def test_a_cell_the_sheet_has_no_row_for_is_not_an_unmarked_one(self):
		"""A re-sitting carries only the papers being sat again. A cell nobody
		can fill has to look different from one that is waiting to be filled,
		or an aegrotat sheet prints as a sheet somebody forgot to finish."""
		doc = sheet_with([("S1", "Test 1", MARKED, 60, 0)])
		self.assertIsNone(doc.printed_mark(None)["status"])
		self.assertEqual(doc.printed_mark(doc.entries[0])["status"], MARKED)

	def test_the_adjustment_is_stated_where_moderation_stands(self):
		"""The cells hold the mark as awarded, so a DP the raw marks do not add
		up to is owed its reason on the same page."""
		doc = sheet_with(
			[("S1", "Test 1", MARKED, 60, 65)], moderation_method=MODERATION_FLAT
		)
		doc.moderation_value = 5
		doc.moderation_reason = "The paper was long."

		self.assertEqual(doc.mark_grid()["moderation"]["value"], "5")
		self.assertEqual(doc.mark_grid()["moderation"]["reason"], "The paper was long.")

	def test_nothing_is_stated_where_no_moderation_stands(self):
		doc = sheet_with([("S1", "Test 1", MARKED, 60, 0)])
		self.assertIsNone(doc.mark_grid()["moderation"])

	def test_a_total_that_cannot_be_worked_out_says_so(self):
		"""A dash is what an unmarked student shows, so a failure that printed
		one would read as "no marks yet" and be invisible. The entry grid shows
		a question mark for the same reason."""
		doc = sheet_with([("S1", "Test 1", MARKED, 60, 0)])
		# No scheme and no course behind it, so the totals cannot be reached.
		grid = doc.mark_grid()

		self.assertTrue(grid["totals_failed"])
		self.assertEqual(grid["rows"][0]["dp"], "?")
		self.assertEqual(grid["rows"][0]["final_mark"], "?")


class TestTheGridAsksForTheSheetByName(FrappeTestCase):
	"""Save Marks failed two ways, and both came from how the call was made.

	`frm.call` posts the browser's whole copy of the document, and the server
	refuses it unless its timestamp still matches the database -- which saving
	marks has just moved. Then `reload_doc` takes the document out of `locals`
	while it fetches the new one, and the debounced totals call that lands in
	that window has no copy to post at all: the key is dropped and the server is
	asked to run the method on nothing, which is the "first non keyword argument
	must be a string or dict" that came back from `frappe.get_doc(None)`.

	The grid now sends the name instead, the way the framework's own preview
	fields do. These run the methods through that same door.
	"""

	def setUp(self):
		sheets = frappe.get_all(
			"Course Mark Sheet",
			filters={"sitting": "Main", "workflow_state": ["in", (AWAITING_ENTRY, IN_ENTRY)]},
			pluck="name",
			order_by="creation desc",
		)
		self.sheet = None
		for name in sheets:
			doc = frappe.get_doc("Course Mark Sheet", name)
			if len(doc.entries) > 1:
				self.sheet = doc
				break
		if not self.sheet:
			self.skipTest("this site has no sheet still with the lecturer")

		# `run_doc_method` is written for a request and reads the HTTP method off
		# one. There is no request here, so it is stood up rather than faked
		# further in: the point of these tests is the real dispatch.
		self.had_request = hasattr(frappe.local, "request")
		self.request = getattr(frappe.local, "request", None)
		frappe.local.request = frappe._dict({"method": "POST"})

	def tearDown(self):
		frappe.db.rollback()
		if self.had_request:
			frappe.local.request = self.request
		else:
			del frappe.local.request

	def by_name(self, method, args=None):
		"""What `sheet_call` sends: the name, and nothing off the form."""
		frappe.local.response = frappe._dict({"docs": []})
		run_doc_method(
			method=method,
			dt="Course Mark Sheet",
			dn=self.sheet.name,
			args=json.dumps(args or {}),
		)
		return frappe.local.response.get("message")

	def by_posting_a_copy(self, copy, method, args=None):
		"""What `frm.call` used to send: the document as the browser holds it."""
		frappe.local.response = frappe._dict({"docs": []})
		run_doc_method(method=method, docs=copy, args=json.dumps(args or {}))
		return frappe.local.response.get("message")

	def mark(self, entry, score):
		return {
			"student": entry.student,
			"assessment_group": entry.assessment_group,
			"status": MARKED,
			"raw_score": score,
		}

	def test_every_method_the_grid_calls_runs_from_the_name_alone(self):
		"""One test for the lot, because the dispatch is what is being checked:
		a method with no arguments and one with arguments go different ways
		through `run_doc_method`."""
		self.assertTrue(self.by_name("student_names"), "no names came back")
		self.assertIn("rows", self.by_name("qa_review") or {}, "no review came back")

		totals = self.by_name("mark_totals", {"changes": [self.mark(self.sheet.entries[0], 5)]})
		self.assertIsInstance(totals, dict, "no totals came back")

	def test_a_mark_saves_after_the_browsers_copy_has_gone_behind(self):
		"""The reported failure, end to end: the first save moves the timestamp,
		and the second one used to be refused because the browser was still
		holding the sheet as it was before the first."""
		first, second = self.sheet.entries[0], self.sheet.entries[1]
		copy = frappe.get_doc("Course Mark Sheet", self.sheet.name).as_json()

		self.by_name("save_marks", {"changes": [self.mark(first, 5)]})

		with self.assertRaises(frappe.TimestampMismatchError):
			self.by_posting_a_copy(copy, "save_marks", {"changes": [self.mark(second, 6)]})

		self.by_name("save_marks", {"changes": [self.mark(second, 6)]})

		self.assertEqual(frappe.db.get_value("Course Mark Sheet Entry", first.name, "raw_score"), 5)
		self.assertEqual(frappe.db.get_value("Course Mark Sheet Entry", second.name, "raw_score"), 6)

	def test_a_sheet_the_browser_is_not_holding_can_still_be_asked_about(self):
		"""`reload_doc` empties `locals` before it fetches, so for as long as the
		fetch takes there is nothing to post. The totals call landed in that
		window and came back as a `ValueError` from deep inside the framework."""
		with self.assertRaises(ValueError):
			self.by_posting_a_copy(None, "mark_totals", {"changes": []})

		self.assertIsInstance(self.by_name("mark_totals", {"changes": []}), dict)


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
		TestTheEntryGridShowsWhatTheMarksComeTo,
		TestSigningOffTheSemesterMark,
		TestCorrectingAMarkSchemeAfterMarkingHasStarted,
		TestThePrintedMarkSheet,
		TestTheGridAsksForTheSheetByName,
	):
		suite.addTests(loader.loadTestsFromTestCase(case))
	return unittest.TextTestRunner(verbosity=verbosity).run(suite)
