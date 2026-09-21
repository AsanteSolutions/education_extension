# Copyright (c) 2026, Asante Solutions and Contributors
# See license.txt

"""Tests for countersigning the registration forms.

The signature is the point: a form the registrar has signed has to print with
that mark on it, and a form they have not has to print with a line they can
sign by hand. Everything else here protects the queue around that.

    from education_extension.education_extension.test_registration_forms import run_tests
    run_tests()
"""

import base64
import io
import unittest

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase

from education_extension.education_extension import registration_forms as forms
from education_extension.education_extension.testing import needs_doctype


def drawn(rule=False, size=(120, 60)):
	"""A mark as the pad saves one: strokes, and optionally its guide line.

	Built rather than pasted in. A signature fixture has to be something `trim`
	treats as handwriting, and a single dark pixel is indistinguishable from a
	rule that happens to be one pixel wide.
	"""
	from PIL import Image, ImageDraw

	image = Image.new("RGBA", size, (255, 255, 255, 0))
	pen = ImageDraw.Draw(image)
	# A scrawl: diagonals, so no row is solid along its own span.
	pen.line([(10, 40), (30, 15), (50, 40), (70, 15), (90, 38)], fill=(0, 0, 0, 255), width=2)
	if rule:
		# What the pad draws across itself for the signer to write on.
		pen.line([(8, 52), (size[0] - 8, 52)], fill=(0, 0, 0, 255), width=2)

	out = io.BytesIO()
	image.save(out, format="PNG")
	return "data:image/png;base64,{0}".format(base64.b64encode(out.getvalue()).decode())


def solid_rows(data_uri):
	"""The rows `trim` would call a rule."""
	from PIL import Image

	image = Image.open(io.BytesIO(base64.b64decode(data_uri.split(",", 1)[1]))).convert("RGBA")
	pixels = image.load()
	width, height = image.size

	rows = []
	for y in range(height):
		run = [x for x in range(width) if forms._inked(pixels[x, y])]
		if not run:
			continue
		span = run[-1] - run[0] + 1
		if span >= width * forms.RULE_SHARE and len(run) >= span * forms.RULE_SOLIDITY:
			rows.append(y)
	return rows


def ink(data_uri):
	from PIL import Image

	image = Image.open(io.BytesIO(base64.b64decode(data_uri.split(",", 1)[1]))).convert("RGBA")
	pixels = image.load()
	width, height = image.size
	return sum(
		1 for y in range(height) for x in range(width) if forms._inked(pixels[x, y])
	)


MARK = drawn()


class TestTrimmingThePadsLine(UnitTestCase):
	"""The pad saves its guide line with the mark; the form draws its own."""

	def test_the_guide_line_comes_off(self):
		with_rule = drawn(rule=True)
		self.assertTrue(solid_rows(with_rule), "the fixture should carry a rule")

		trimmed = forms.trim(with_rule)

		self.assertEqual(solid_rows(trimmed), [])

	def test_the_signature_survives_it(self):
		"""Taking the line off must not take the handwriting with it."""
		with_rule = drawn(rule=True)
		without = drawn(rule=False)

		trimmed = forms.trim(with_rule)

		# What is left is the scrawl, give or take the pixels the rule overlapped.
		self.assertGreater(ink(trimmed), ink(without) * 0.9)

	def test_a_mark_with_no_line_keeps_its_ink(self):
		clean = drawn(rule=False)
		self.assertEqual(ink(forms.trim(clean)), ink(clean))

	def test_it_is_cropped_to_the_signature(self):
		"""So the mark sits on the form's rule rather than floating above it."""
		from PIL import Image

		padded = drawn(rule=True, size=(400, 200))
		trimmed = forms.trim(padded)
		image = Image.open(io.BytesIO(base64.b64decode(trimmed.split(",", 1)[1])))

		self.assertLess(image.size[0], 400)
		self.assertLess(image.size[1], 200)

	def test_anything_that_is_not_an_image_is_left_alone(self):
		for value in ("", None, "/files/somewhere.png", "not a data uri"):
			self.assertEqual(forms.trim(value), value)


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

	def give_the_registrar_a_signature(self, mark=MARK):
		settings = frappe.get_single("Registration Settings")
		settings.registrar_signature = mark
		settings.flags.ignore_permissions = True
		settings.save()

	def a_form(self):
		queue = forms.forms()
		if not queue:
			self.skipTest("every consent on this site is already signed")
		return queue[0]["name"]

	def test_the_line_is_gone_by_the_time_it_is_stamped(self):
		"""The whole of the reported fault: the pad's line and the form's rule
		both printing, one above the other."""
		self.give_the_registrar_a_signature(drawn(rule=True))
		name = self.a_form()

		forms.sign(name)

		self.assertEqual(solid_rows(forms.form(name)["registrar_signature"]), [])

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
		self.assertTrue(signed["registrar_signature"].startswith("data:image/png;base64,"))
		self.assertGreater(ink(signed["registrar_signature"]), 0)
		self.assertTrue(signed["registrar_signed_at"])
		self.assertEqual(
			frappe.db.get_value("Registration Consent", name, "signed_by_registrar"),
			frappe.session.user,
		)

	def test_an_uploaded_signature_is_read_into_the_form(self):
		"""The settings may hold a file rather than a drawn mark; the consent has
		to hold the image itself either way.

		Pointing at the file would mean a form is only signed for as long as
		that file is there and unchanged, and this is the record of who
		countersigned a registration.
		"""
		png = base64.b64decode(MARK.split(",", 1)[1])
		upload = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": "registrar-signature-for-tests.png",
				"is_private": 0,
				"content": png,
			}
		).insert(ignore_permissions=True)

		self.give_the_registrar_a_signature(upload.file_url)
		name = self.a_form()
		forms.sign(name)

		stamped = forms.form(name)["registrar_signature"]
		self.assertTrue(stamped.startswith("data:image/png;base64,"), stamped[:40])
		self.assertNotIn(upload.file_url, stamped)
		self.assertGreater(ink(stamped), 0)

	def test_a_missing_signature_file_is_said_so(self):
		"""Rather than signing every form in the term with nothing on it."""
		self.give_the_registrar_a_signature("/files/no-such-signature-for-tests.png")

		with self.assertRaises(frappe.ValidationError):
			forms.sign(self.a_form())

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
		"""Unsigned it prints a line to sign by hand; signed it prints the mark
		and exactly one rule under it."""
		self.give_the_registrar_a_signature(drawn(rule=True))
		name = self.a_form()

		before = frappe.get_print(
			"Registration Consent", name, print_format="Proof of Registration"
		)
		self.assertIn("REGISTRAR", before.upper())

		forms.sign(name)
		stamped = forms.form(name)["registrar_signature"]

		after = frappe.get_print(
			"Registration Consent", name, print_format="Proof of Registration"
		)
		self.assertIn(stamped, after)
		# One rule per signature block, and none of them a leftover blank.
		self.assertEqual(
			after.count('<div class="signature-rule">'),
			after.count('class="proof-signature"'),
		)
		self.assertEqual(after.count('<div class="signature-space">'), 0)


def run_tests(verbosity=2):
	"""Run these from a console, since bench run-tests cannot bootstrap this site."""
	suite = unittest.TestSuite()
	loader = unittest.TestLoader()
	for case in (TestTrimmingThePadsLine, TestSigningRoles, TestSigningForms):
		suite.addTests(loader.loadTestsFromTestCase(case))
	return unittest.TextTestRunner(verbosity=verbosity).run(suite)
