# Copyright (c) 2026, Asante Solutions and Contributors
# See license.txt

"""Tests for countersigning the registration forms.

The signature is the point: a form the registrar has signed has to print with
that mark on it, and a form they have not has to print with a line they can
sign by hand. Everything else here protects the queue around that.

    from education_extension.education_extension.test_registration_forms import run_tests
    run_tests()
"""

import unittest

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase

from education_extension.education_extension import registration_forms as forms
from education_extension.education_extension.testing import needs_doctype

# A drawn mark, as the signature pad produces one. A single pixel is enough.
MARK = (
	"data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
	"AAAADUlEQVR42mP8z8AAAwAB/wFDkQvzAAAAAElFTkSuQmCC"
)


class TestSigningRoles(UnitTestCase):
	"""Who may countersign. No database."""

	def test_the_queue_answers_to_the_registrar_roles(self):
		"""These forms carry a student's name, ID number and modules. Whoever may
		read them through the report may read them here and no one else."""
		from education_extension.education_extension.dashboard import REGISTRAR_ROLES

		self.assertEqual(tuple(forms.REGISTRAR_ROLES), tuple(REGISTRAR_ROLES))

	def test_the_page_is_shown_to_the_same_people(self):
		import json
		import os

		path = os.path.join(
			os.path.dirname(forms.__file__),
			"page",
			"sign_registration_forms",
			"sign_registration_forms.json",
		)
		with open(path) as handle:
			roles = {row["role"] for row in json.load(handle)["roles"]}

		self.assertEqual(roles, set(forms.REGISTRAR_ROLES))


class TestSigningForms(IntegrationTestCase):
	"""The queue and the mark it puts on a form."""

	def setUp(self):
		needs_doctype(self, "Program Enrollment")
		if not frappe.get_all("Registration Consent", filters={"docstatus": 1}, limit=1):
			self.skipTest("no submitted consents on this site")

	def tearDown(self):
		"""Undone after each test rather than at the end of the class.

		These sign real consents, and the suite only rolls back once the class
		is done — so the mass-signing test, which runs third by name, left every
		test after it looking at a site where everything was already signed, and
		they all skipped rather than failed. A suite that quietly stops testing
		is worse than one that breaks.
		"""
		frappe.db.rollback()

	def give_the_registrar_a_signature(self):
		settings = frappe.get_single("Registration Settings")
		settings.registrar_signature = MARK
		settings.flags.ignore_permissions = True
		settings.save()

	def a_form(self):
		queue = forms.forms()
		if not queue:
			self.skipTest("every consent on this site is already signed")
		return queue[0]["name"]

	def test_signing_needs_a_signature_to_sign_with(self):
		"""Otherwise it would stamp an empty mark and report success, and the
		form would print with a blank line and a signed-on date beneath it."""
		settings = frappe.get_single("Registration Settings")
		settings.registrar_signature = None
		settings.flags.ignore_permissions = True
		settings.save()

		with self.assertRaises(frappe.ValidationError):
			forms.sign(self.a_form())

	def test_signing_records_the_mark_the_name_and_who_did_it(self):
		self.give_the_registrar_a_signature()
		name = self.a_form()

		self.assertTrue(forms.sign(name))

		signed = forms.form(name)
		self.assertTrue(signed["signed"])
		self.assertEqual(signed["registrar_signature"], MARK)
		self.assertTrue(signed["registrar_signed_at"])
		self.assertEqual(
			frappe.db.get_value("Registration Consent", name, "signed_by_registrar"),
			frappe.session.user,
		)

	def test_the_name_is_stamped_on_rather_than_looked_up_later(self):
		"""A form reprinted after the registrar changes has to still name the
		person who signed it."""
		self.give_the_registrar_a_signature()
		name = self.a_form()
		forms.sign(name)

		settings = frappe.get_single("Registration Settings")
		settings.registrar_name = "SOMEBODY ELSE"
		settings.flags.ignore_permissions = True
		settings.save()

		self.assertNotEqual(forms.form(name)["registrar_name"], "SOMEBODY ELSE")

	def test_signing_twice_is_quiet_rather_than_an_error(self):
		"""Running the queue again overlaps with what was already done, and that
		is not a reason to refuse the rest of it."""
		self.give_the_registrar_a_signature()
		name = self.a_form()

		self.assertTrue(forms.sign(name))
		when = forms.form(name)["registrar_signed_at"]

		self.assertFalse(forms.sign(name))
		self.assertEqual(forms.form(name)["registrar_signed_at"], when)

	def test_a_signed_form_leaves_the_queue(self):
		self.give_the_registrar_a_signature()
		name = self.a_form()

		forms.sign(name)

		self.assertNotIn(name, [row["name"] for row in forms.forms()])
		self.assertIn(name, [row["name"] for row in forms.forms(state=forms.SIGNED)])

	def test_the_queue_does_not_carry_the_signatures(self):
		"""A term is a couple of hundred forms and each mark is tens of
		kilobytes; the list is names, and the one on screen is fetched on its
		own."""
		for row in forms.forms(state="all")[:5]:
			self.assertNotIn("student_signature", row)
			self.assertNotIn("registrar_signature", row)

	def test_signing_all_of_them_signs_all_of_them(self):
		self.give_the_registrar_a_signature()
		waiting = [row["name"] for row in forms.forms()]

		out = forms.sign_all()

		self.assertEqual(sorted(out["signed"]), sorted(waiting))
		self.assertEqual(out["problems"], [])
		self.assertEqual(forms.forms(), [])

	def test_a_signature_can_be_taken_back_off(self):
		"""There is no other way back: the field is written after submission and
		the form is not editable."""
		self.give_the_registrar_a_signature()
		name = self.a_form()
		forms.sign(name)

		self.assertTrue(forms.unsign(name))
		self.assertFalse(forms.form(name)["signed"])
		self.assertIn(name, [row["name"] for row in forms.forms()])

	def test_the_form_shows_the_modules_it_covers(self):
		name = self.a_form()
		detail = forms.form(name)
		consent = frappe.get_doc("Registration Consent", name)

		enrolled = frappe.db.sql(
			"""
			select count(*) from `tabProgram Enrollment Course` pec
			join `tabProgram Enrollment` pe on pe.name = pec.parent
			where pe.docstatus = 1 and pe.student = %s
			  and pe.academic_year = %s and pe.academic_term = %s
			""",
			(consent.student, consent.academic_year, consent.academic_term),
		)[0][0]

		self.assertEqual(len(detail["modules"]), enrolled)

	def test_the_mark_reaches_the_printed_form(self):
		"""The whole point. Unsigned it prints a line to sign by hand; signed it
		prints the mark."""
		self.give_the_registrar_a_signature()
		name = self.a_form()

		before = frappe.get_print(
			"Registration Consent", name, print_format="Proof of Registration"
		)
		self.assertNotIn(MARK, before)
		self.assertIn("REGISTRAR", before.upper())

		forms.sign(name)

		after = frappe.get_print(
			"Registration Consent", name, print_format="Proof of Registration"
		)
		self.assertIn(MARK, after)


def run_tests(verbosity=2):
	"""Run these from a console, since bench run-tests cannot bootstrap this site."""
	suite = unittest.TestSuite()
	loader = unittest.TestLoader()
	for case in (TestSigningRoles, TestSigningForms):
		suite.addTests(loader.loadTestsFromTestCase(case))
	return unittest.TextTestRunner(verbosity=verbosity).run(suite)
