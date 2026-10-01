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

import frappe
from frappe.tests import IntegrationTestCase

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


def run_tests(verbosity=2):
	"""Run these from a console, since bench run-tests cannot bootstrap this site."""
	suite = unittest.TestSuite()
	loader = unittest.TestLoader()
	for case in (TestOnlyStaffMayPrintAReport, TestTheFilenameComesFromTheRecord):
		suite.addTests(loader.loadTestsFromTestCase(case))
	return unittest.TextTestRunner(verbosity=verbosity).run(suite)
