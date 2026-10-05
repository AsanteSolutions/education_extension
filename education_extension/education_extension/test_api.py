# Copyright (c) 2026, Asante Solutions and Contributors
# See license.txt

"""Tests for who the portal thinks it is talking to.

`_current_user_student` is the whole of the portal's identity. `my_options`,
`register` and `get_student_grades` all take their student from it rather than
from the caller, so everything a student may see or do rests on this one lookup
being right — and on it being the same answer twice running.

    from education_extension.education_extension.test_api import run_tests
    run_tests()
"""

import unittest

import frappe
from frappe.tests import IntegrationTestCase

from education_extension.education_extension import api
from education_extension.education_extension.student_permissions import on_student_validate
from education_extension.education_extension.testing import (
	needs_doctype,
	needs_education_app,
)


class TestWhoTheSessionBelongsTo(IntegrationTestCase):
	"""One portal account stands for one student, or for none."""

	def setUp(self):
		needs_education_app(self)
		needs_doctype(self, "Student")

		self.linked = frappe.db.get_value(
			"Student", {"user": ["is", "set"]}, ["name", "user"], as_dict=True
		)
		if not self.linked:
			self.skipTest("no student on this site has a portal account")

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def claim(self, student, user):
		"""Point a second student at an account, the way a bad import would.

		Written straight to the column, because the controller is exactly what is
		being tested: going through `save` would be refused, which is the other
		half of this and is tested on its own below.
		"""
		frappe.db.set_value("Student", student, "user", user, update_modified=False)

	def another_student(self):
		other = frappe.get_all(
			"Student", filters={"name": ["!=", self.linked.name]}, pluck="name", limit=1
		)
		if not other:
			self.skipTest("this site has only one student")
		return other[0]

	def test_a_single_account_answers_with_its_student(self):
		frappe.set_user(self.linked.user)
		self.assertEqual(api._current_user_student(), self.linked.name)

	def test_an_account_with_no_student_answers_with_none(self):
		user = frappe.db.get_value(
			"User",
			{"enabled": 1, "name": ["not in", ("Administrator", "Guest")]},
			"name",
		)
		if not user or frappe.db.exists("Student", {"user": user}):
			self.skipTest("no account on this site is without a student")

		frappe.set_user(user)
		self.assertIsNone(api._current_user_student())

	def test_administrator_and_guest_are_nobody(self):
		"""Neither is a student, and Administrator matching a stray row would be
		the worst possible thing for it to match."""
		for user in ("Administrator", "Guest"):
			frappe.set_user(user)
			self.assertIsNone(api._current_user_student())

	def test_two_students_on_one_account_is_refused_rather_than_guessed(self):
		"""The bug. The lookup this replaced had no ordering, so it answered with
		whichever row the database felt like — and could answer differently on the
		next call, against the same session."""
		self.claim(self.another_student(), self.linked.user)
		frappe.set_user(self.linked.user)

		with self.assertRaises(frappe.ValidationError):
			api._current_user_student()

	def test_the_portal_refuses_too_rather_than_serving_the_wrong_record(self):
		"""Checked through the endpoints themselves, because a helper that throws
		is no use if a caller swallows it."""
		from education_extension.education_extension.marking import get_student_grades
		from education_extension.education_extension.registration import my_options

		self.claim(self.another_student(), self.linked.user)
		frappe.set_user(self.linked.user)

		with self.assertRaises(frappe.ValidationError):
			api.get_student_info()
		with self.assertRaises(frappe.ValidationError):
			my_options()
		with self.assertRaises(frappe.ValidationError):
			get_student_grades("2026", "2026 (First Semester 2026)")


class TestOneAccountCannotStandForTwoStudents(IntegrationTestCase):
	"""Nothing upstream stops it: the link has no unique constraint and no index,
	and the education app's controller only ever sets the field."""

	def setUp(self):
		needs_education_app(self)
		needs_doctype(self, "Student")

		self.linked = frappe.db.get_value(
			"Student", {"user": ["is", "set"]}, ["name", "user"], as_dict=True
		)
		if not self.linked:
			self.skipTest("no student on this site has a portal account")

		other = frappe.get_all(
			"Student", filters={"name": ["!=", self.linked.name]}, pluck="name", limit=1
		)
		if not other:
			self.skipTest("this site has only one student")
		self.other = frappe.get_doc("Student", other[0])

	def tearDown(self):
		frappe.db.rollback()

	def test_taking_an_account_another_student_holds_is_refused(self):
		"""Through a real save, so the hook's wiring is under test as well as its
		body — and so the before-image is the one Frappe actually supplies."""
		self.other.user = self.linked.user
		with self.assertRaises(frappe.ValidationError):
			self.other.save()

	def test_the_message_names_the_student_already_holding_it(self):
		"""So the registrar can go straight to it rather than hunting."""
		self.other.user = self.linked.user
		try:
			self.other.save()
		except frappe.ValidationError:
			self.assertIn(self.linked.name, frappe.get_message_log()[-1]["message"])
		else:
			self.fail("it was allowed")

	def test_keeping_the_account_you_already_have_is_not_a_clash(self):
		"""Otherwise every save of a linked student would fail against itself."""
		frappe.get_doc("Student", self.linked.name).save()

	def test_a_student_with_no_account_is_not_checked(self):
		self.other.user = None
		on_student_validate(self.other)

	def test_a_site_that_already_holds_a_pair_can_still_edit_them(self):
		"""Refusing to save them would make the problem harder to fix than to
		keep. The check is on the link changing, not on the state existing."""
		frappe.db.set_value(
			"Student", self.other.name, "user", self.linked.user, update_modified=False
		)

		doc = frappe.get_doc("Student", self.other.name)
		doc.middle_name = "Edited"
		doc.save()

		self.assertEqual(frappe.db.get_value("Student", self.other.name, "middle_name"), "Edited")

	def test_the_hook_is_wired_up(self):
		"""A validate hook nothing calls is a comment."""
		hooks = frappe.get_hooks("doc_events") or {}
		student = hooks.get("Student") or {}
		self.assertIn(
			"education_extension.education_extension.student_permissions.on_student_validate",
			frappe.utils.cstr(student.get("validate")),
		)


def run_tests(verbosity=2):
	"""Run these from a console, since bench run-tests cannot bootstrap this site."""
	suite = unittest.TestSuite()
	loader = unittest.TestLoader()
	for case in (TestWhoTheSessionBelongsTo, TestOneAccountCannotStandForTwoStudents):
		suite.addTests(loader.loadTestsFromTestCase(case))
	return unittest.TextTestRunner(verbosity=verbosity).run(suite)
