# Copyright (c) 2026, Asante Solutions and Contributors
# See license.txt

"""Tests for the printed progress report.

The doctype's own test file is where Frappe looks, but `bench run-tests` cannot
bootstrap this site, so nothing in it ever runs here. This is the runnable
sibling, in the same place as the other suites:

    from education_extension.education_extension.test_progress_report import run_tests
    run_tests()
"""

import json
import unittest
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from education_extension.education_extension import marking
from education_extension.education_extension.doctype.student_progress_report import (
	student_progress_report as report,
)
from education_extension.education_extension.testing import (
	needs_doctype,
	needs_education_app,
)

# Who the doctype lets in. Anyone else asking for a student's report is asking
# for somebody else's record.
ALLOWED_ROLES = ("System Manager", "Academics User")


class TestOnlyStaffMayPrintAReport(IntegrationTestCase):
	"""`preview_progress_report` is whitelisted and names its own student.

	Whitelisting opens an endpoint to every logged-in user and applies none of
	the doctype's permissions, so the check has to be in the function. Without
	it, any account could post another student's id and receive their marks, ID
	number and remarks as a PDF — around the User Permission confinement and
	around the release gate at the same time.
	"""

	def setUp(self):
		needs_education_app(self)
		needs_doctype(self, "Student Progress Report", "Student")

		self.outsider = an_account_without_staff_roles()
		if not self.outsider:
			self.skipTest("no account on this site is outside the staff roles")

		students = frappe.get_all("Student", limit=1, pluck="name")
		if not students:
			self.skipTest("this site has no students")
		self.student = students[0]

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def request(self):
		"""The argument the desk form sends, as it sends it: a JSON string."""
		return json.dumps({"student": self.student, "academic_year": "", "academic_term": ""})

	def test_an_account_outside_the_staff_roles_is_refused(self):
		frappe.set_user(self.outsider)
		with self.assertRaises(frappe.PermissionError):
			report.preview_progress_report(self.request())

	def test_it_is_refused_before_anything_is_read(self):
		"""The check is the first statement, so a refusal costs nothing and
		leaks nothing — not even whether the student exists."""
		frappe.set_user(self.outsider)
		with self.assertRaises(frappe.PermissionError):
			report.preview_progress_report(json.dumps({"student": "no-such-student"}))

		self.assertIsNone(
			frappe.response.get("filecontent"), "a refused request produced a document"
		)

	def test_a_student_cannot_ask_for_their_own_report_either(self):
		"""Not a restriction so much as a consequence: this is the staff tool.

		What a student is entitled to see goes through the portal, which reads
		the student from the session and holds marks back until the term
		releases them. Neither applies here.
		"""
		student_user = frappe.db.get_value(
			"Student", {"user": ["is", "set"]}, ["name", "user"], as_dict=True
		)
		if not student_user:
			self.skipTest("no student on this site has a portal account")
		if set(ALLOWED_ROLES) & set(frappe.get_roles(student_user.user)):
			self.skipTest("that student's account also holds a staff role")

		frappe.set_user(student_user.user)
		with self.assertRaises(frappe.PermissionError):
			report.preview_progress_report(json.dumps({"student": student_user.name}))

	def test_staff_are_let_through(self):
		"""The other half: the check must not have shut the tool itself."""
		frappe.set_user("Administrator")
		self.assertTrue(
			frappe.has_permission("Student Progress Report", ptype="read"),
			"the tool is closed to Administrator, which cannot be right",
		)


class TestTheFilenameComesFromTheRecord(IntegrationTestCase):
	"""The name lands in a Content-Disposition header, so the caller does not
	get to choose it — the request carries a `student_name` of its own."""

	def setUp(self):
		needs_education_app(self)
		needs_doctype(self, "Student")

	def tearDown(self):
		frappe.db.rollback()

	def test_it_reads_the_name_off_the_student(self):
		student = frappe.get_all("Student", fields=["name", "student_name"], limit=1)
		if not student:
			self.skipTest("this site has no students")
		student = student[0]
		if not student.student_name:
			self.skipTest("that student has no name recorded")

		self.assertEqual(report._filename_for(student.name), student.student_name)

	def test_an_unknown_student_does_not_produce_an_empty_filename(self):
		self.assertEqual(report._filename_for("no-such-student"), "no-such-student")
		self.assertEqual(report._filename_for(None), "Student")
		self.assertEqual(report._filename_for(""), "Student")

	def test_characters_that_would_break_the_header_are_dropped(self):
		cases = {
			'Doe"; filename="payroll.pdf': "Doe filename=payroll.pdf",
			"Doe\r\nX-Injected: 1": "DoeX-Injected: 1",
			"../../etc/passwd": "....etcpasswd",
		}
		for supplied, expected in cases.items():
			# Fed through the Student lookup's fallback, which is the path a name
			# this odd would actually take.
			self.assertEqual(report._filename_for(supplied), expected, repr(supplied))

	def test_an_ordinary_name_is_left_alone(self):
		"""Sanitising is not an excuse to mangle people's names."""
		for name in ("O'Brien", "Nomsa Dlamini-Khumalo", "Jean-Luc Picard", "Ní Mháille"):
			self.assertEqual(report._filename_for(name), name)


class TestTheSupplementaryColumnAgreesWithThePortal(IntegrationTestCase):
	"""The printed report and the portal read the same re-sit, so they have to
	report the same mark for it.

	They did not. This read Assessment Result on its own, so a supplementary
	marked on an approved Course Mark Sheet was invisible and the PDF printed no
	supplementary row at all — and it treated the score as though it were already
	a percentage, so one marked out of anything but 100 printed as the raw score.
	"""

	COURSE = "ANH9999 - Test Course"

	def setUp(self):
		needs_doctype(self, "Student Progress Report")
		self.doc = frappe._dict(
			{"student": "S1", "academic_year": "2026", "academic_term": "2026 (Term)"}
		)

	def results(self, *rows):
		"""What `get_assessment_results` hands back, which is already resolved:
		an approved sheet answers for its sitting and Assessment Result for the
		rest, so patching here is patching the only thing this reads."""
		return {self.COURSE: list(rows)}

	def supplementary(self, score, maximum=100, sitting="Supplementary", group="Supplementary Exam"):
		return {
			"assessment_group": group,
			"sitting": sitting,
			"total_score": score,
			"maximum_score": maximum,
		}

	def marks_for(self, by_course):
		with patch.object(marking, "get_assessment_results", return_value=by_course):
			return report.get_supplementary_results(self.doc)

	def test_a_mark_out_of_fifty_is_reported_as_a_percentage(self):
		"""45 out of 50 is 90%, and printed 45 before this."""
		self.assertEqual(
			self.marks_for(self.results(self.supplementary(45, maximum=50))),
			{self.COURSE: "90"},
		)

	def test_a_mark_out_of_a_hundred_is_unchanged(self):
		"""The case every site has today, which must not move."""
		self.assertEqual(
			self.marks_for(self.results(self.supplementary(57))), {self.COURSE: "57"}
		)

	def test_a_supplementary_held_on_an_approved_sheet_is_reported(self):
		"""The reader resolves a sheet ahead of Assessment Result, so going
		through it is what makes a sheet-marked re-sit visible. Reading the
		doctype directly, as this did, printed nothing at all."""
		marks = self.marks_for(
			self.results(
				{"assessment_group": "Theory Exam", "sitting": "Main",
				 "total_score": 48, "maximum_score": 100},
				self.supplementary(31, maximum=50),
			)
		)
		self.assertEqual(marks, {self.COURSE: "62"})

	def test_the_old_naming_still_counts(self):
		"""A supplementary entered on the standard form carries no sitting; the
		assessment group's name is what says what it is."""
		self.assertEqual(
			self.marks_for(self.results(self.supplementary(70, sitting=None))),
			{self.COURSE: "70"},
		)

	def test_a_course_with_no_supplementary_is_not_listed(self):
		marks = self.marks_for(
			self.results(
				{"assessment_group": "Theory Exam", "sitting": "Main",
				 "total_score": 64, "maximum_score": 100}
			)
		)
		self.assertEqual(marks, {})

	def test_an_unmarked_supplementary_is_not_a_mark_of_nought(self):
		self.assertEqual(self.marks_for(self.results(self.supplementary(None))), {})

	def test_it_puts_the_report_on_the_supplementary_issue_date(self):
		"""The knock-on. `_issue_date_kinds` reads this, so a supplementary it
		could not see also took the report out to the wrong issue date."""
		by_course = self.results(self.supplementary(31, maximum=50))
		with patch.object(marking, "get_assessment_results", return_value=by_course):
			with patch.object(report, "get_supplementary_remarks", return_value={}):
				with patch.object(report, "_has_aegrotat_result", return_value=False):
					with patch.object(report, "_has_remarked_result", return_value=False):
						kinds = report._issue_date_kinds(self.doc)

		self.assertIn(report.ISSUE_DATE_SUPPLEMENTARY, kinds)

	def test_the_printed_report_and_the_portal_report_the_same_mark(self):
		"""Against whatever this site actually holds, so the two cannot drift
		apart on real data without this failing."""
		needs_education_app(self)
		students = frappe.db.sql(
			"""select distinct student, academic_term from `tabAssessment Result`
			   where docstatus = 1 and custom_sitting = 'Supplementary' limit 10""",
			as_dict=True,
		)
		if not students:
			self.skipTest("no student on this site has a supplementary mark")

		for row in students:
			doc = frappe._dict(row)
			printed = report.get_supplementary_results(doc)
			portal = marking._supplementary_marks(
				marking.get_assessment_results(doc.student, doc.academic_term)
			)
			self.assertEqual(
				printed,
				{course: mark.rstrip("%") for course, mark in portal.items()},
				row.student,
			)


def an_account_without_staff_roles():
	"""A real enabled account holding none of the roles the doctype allows.

	Found rather than made: creating a User inside the test would need a role
	profile and a password policy this site may have, and the point is to prove
	the check fires for an account the site actually has.
	"""
	for user in frappe.get_all(
		"User",
		filters={"enabled": 1, "name": ["not in", ("Administrator", "Guest")]},
		pluck="name",
		limit=200,
	):
		if not set(ALLOWED_ROLES) & set(frappe.get_roles(user)):
			return user
	return None


class TestAnAegrotatIsSeenHoweverItWasRecorded(IntegrationTestCase):
	"""An aegrotat sitting moves the report onto its own Date of Issue.

	This matched only the AEGRO-prefixed assessment group — the convention the
	sitting field replaced — and read Assessment Result directly. So an aegrotat
	recorded the way the form now asks for it, or held on an approved Course Mark
	Sheet, counted as none at all, and the report printed the Standard date.
	"""

	COURSE = "ANH9999 - Test Course"

	def setUp(self):
		needs_doctype(self, "Student Progress Report")
		self.doc = frappe._dict(
			{"student": "S1", "academic_year": "2026", "academic_term": "2026 (Term)"}
		)

	def mark(self, group, sitting):
		return {
			"assessment_group": group,
			"sitting": sitting,
			"total_score": 55,
			"maximum_score": 100,
		}

	def seen(self, *rows):
		"""Through `get_assessment_results`, which is what resolves an approved
		sheet ahead of Assessment Result. Going through it is the half of this
		fix that makes a sheet-marked aegrotat visible at all."""
		with patch.object(
			marking, "get_assessment_results", return_value={self.COURSE: list(rows)}
		):
			return report._has_aegrotat_result(self.doc)

	def test_a_sitting_recorded_on_the_field_counts(self):
		"""The way the form asks for it, and the case that was missed."""
		self.assertTrue(self.seen(self.mark("Theory Exam", "Aegrotat")))

	def test_the_old_group_naming_still_counts(self):
		"""A mark can still be entered against one of those groups on the
		standard form, where nothing prompts for a sitting."""
		self.assertTrue(self.seen(self.mark("AEGRO Theory Exam", "Main")))

	def test_a_term_with_no_aegrotat_is_not_one(self):
		self.assertFalse(self.seen(self.mark("Theory Exam", "Main")))

	def test_a_supplementary_is_not_an_aegrotat(self):
		"""Two different sittings, with two different issue dates."""
		self.assertFalse(self.seen(self.mark("Supplementary Exam", "Supplementary")))

	def test_it_puts_the_report_on_the_aegrotat_issue_date(self):
		"""The knock-on, as for the supplementary column beside it."""
		by_course = {self.COURSE: [self.mark("Theory Exam", "Aegrotat")]}
		with patch.object(marking, "get_assessment_results", return_value=by_course):
			with patch.object(report, "get_supplementary_remarks", return_value={}):
				with patch.object(report, "_has_remarked_result", return_value=False):
					kinds = report._issue_date_kinds(self.doc)

		self.assertIn(report.ISSUE_DATE_AEGROTAT, kinds)

	def test_every_aegrotat_on_this_site_is_seen(self):
		"""Against the real records, so the two cannot drift apart silently."""
		needs_education_app(self)
		rows = frappe.get_all(
			"Assessment Result",
			filters={"custom_sitting": "Aegrotat", "docstatus": 1},
			fields=["student", "academic_term"],
			limit_page_length=0,
		)
		if not rows:
			self.skipTest("no student on this site has an aegrotat mark")

		for row in {(r.student, r.academic_term): r for r in rows}.values():
			doc = frappe._dict(
				{
					"student": row.student,
					"academic_term": row.academic_term,
					"academic_year": frappe.db.get_value(
						"Academic Term", row.academic_term, "academic_year"
					),
				}
			)
			self.assertTrue(
				report._has_aegrotat_result(doc),
				"{0} has an aegrotat mark for {1} that the report cannot see".format(
					row.student, row.academic_term
				),
			)


class TestAnAmendedSupplementaryCommentIsARemarking(IntegrationTestCase):
	"""`_has_remarked_result` reads the three doctypes `_last_marks_change` does.

	It read two. A supplementary comment that was amended is a remarked result
	exactly as a main one is, and leaving it out dated the report as though
	nothing had been looked at again.
	"""

	def setUp(self):
		needs_education_app(self)
		needs_doctype(self, "Supplementary Academic Remark", "Student Progress Report")

		result = frappe.get_all(
			"Assessment Result",
			filters={"docstatus": 1},
			fields=["student", "course", "academic_term"],
			limit=1,
		)
		if not result:
			self.skipTest("this site has no results to hang a comment on")

		self.keys = dict(result[0])
		self.keys["academic_year"] = frappe.db.get_value(
			"Academic Term", self.keys["academic_term"], "academic_year"
		)
		self.doc = frappe._dict(self.keys)

		codes = marking.remark_codes("Supplementary Academic Remark")
		if not codes:
			self.skipTest("Supplementary Academic Remark offers no codes")
		self.code = codes[0]

		# Only observable on a student and term nothing else has remarked.
		if report._has_remarked_result(self.doc):
			self.skipTest("that student and term already count as remarked")

	def tearDown(self):
		frappe.db.rollback()

	def test_an_amended_supplementary_comment_counts_as_a_remarking(self):
		first = frappe.get_doc(dict(self.keys, doctype="Supplementary Academic Remark", supp_remark=self.code))
		first.insert()
		first.submit()

		# Correcting a submitted document in Frappe is a cancel and an amend, and
		# the amendment is the trace this looks for.
		self.assertFalse(
			report._has_remarked_result(self.doc), "filing a comment is not a remarking"
		)
		first.cancel()
		amended = frappe.copy_doc(first)
		amended.amended_from = first.name
		amended.docstatus = 0
		amended.insert()
		amended.submit()

		self.assertTrue(
			report._has_remarked_result(self.doc),
			"an amended supplementary comment was not counted as a remarking",
		)


def run_tests(verbosity=2):
	"""Run these from a console, since bench run-tests cannot bootstrap this site."""
	suite = unittest.TestSuite()
	loader = unittest.TestLoader()
	for case in (
		TestOnlyStaffMayPrintAReport,
		TestTheFilenameComesFromTheRecord,
		TestTheSupplementaryColumnAgreesWithThePortal,
		TestAnAegrotatIsSeenHoweverItWasRecorded,
		TestAnAmendedSupplementaryCommentIsARemarking,
	):
		suite.addTests(loader.loadTestsFromTestCase(case))
	return unittest.TextTestRunner(verbosity=verbosity).run(suite)
