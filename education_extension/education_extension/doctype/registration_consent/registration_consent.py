# Copyright (c) 2026, Asante Solutions and contributors
# For license information, please see license.txt

"""What a student agreed to when they registered.

Submittable and read-only throughout: a consent record that can be edited
afterwards is not evidence of anything. Submitting is the signature, and an
amendment leaves the original standing with the new one pointing back at it.

The wording is snapshotted onto the record rather than referenced, because the
institution can amend the text in Registration Settings and a consent has to
keep saying what was actually put in front of that student on that day.
"""

import re

import frappe
from frappe import _
from frappe.model.document import Document

# A drawn signature arrives as a PNG data URI from the canvas the student signs
# on. Anything else is not a signature, and the cap is there because the field is
# fed by a request: a signature of this size is a few tens of kilobytes.
SIGNATURE = re.compile(r"^data:image/(png|jpeg);base64,[A-Za-z0-9+/=\s]+$")
SIGNATURE_LIMIT = 250 * 1024


class RegistrationConsent(Document):
	def validate(self):
		self.validate_both_declarations_given()
		self.validate_the_wording_was_recorded()
		self.validate_the_student_signed()
		self.validate_the_guardian_signed_completely()

	def validate_the_student_signed(self):
		if not (self.student_signature or "").strip():
			frappe.throw(_("The declaration has not been signed."))
		validate_signature(self.student_signature, _("Student signature"))

	def validate_the_guardian_signed_completely(self):
		"""A guardian signature and a guardian name go together or not at all.

		Either half on its own is not a countersignature: a name with no mark is
		not signed, and a mark with no name cannot be attributed to anybody.
		"""
		name = (self.guardian_name or "").strip()
		signature = (self.guardian_signature or "").strip()

		if not self.signed_by_guardian:
			if name or signature:
				frappe.throw(
					_("A parent or guardian signature was given but not marked as one.")
				)
			return

		if not name:
			frappe.throw(_("The parent or guardian has not been named."))
		if not signature:
			frappe.throw(_("The parent or guardian has not signed."))
		validate_signature(signature, _("Parent or guardian signature"))


	def validate_both_declarations_given(self):
		"""Neither declaration is optional, and neither implies the other.

		The form carries two separate signature lines for a reason: one is a
		declaration about the student's own academic standing, the other is consent
		to process their personal information. Recording a half-agreement as a
		consent would misrepresent it.
		"""
		if not self.prerequisites_declared:
			frappe.throw(_("The pre-requisite declaration has not been made."))
		if not self.popia_consented:
			frappe.throw(_("Consent to process personal information has not been given."))

	def validate_the_wording_was_recorded(self):
		if not (self.declaration_text or "").strip():
			frappe.throw(_("The declaration wording was not recorded."))
		if not (self.consent_text or "").strip():
			frappe.throw(_("The POPIA consent wording was not recorded."))


def validate_signature(value, label):
	"""A drawn mark, or nothing.

	The size cap matters because this field is fed straight from a request: a
	real signature is a few tens of kilobytes, and without a limit the field is
	an invitation to post megabytes into the database.
	"""
	if len(value) > SIGNATURE_LIMIT:
		frappe.throw(_("{0} is too large.").format(label))
	if not SIGNATURE.match(value.strip()):
		frappe.throw(_("{0} is not a signature.").format(label))


def consent_for(student, academic_year, academic_term):
	"""The consent already on record for this student and term, if any."""
	return frappe.db.exists(
		"Registration Consent",
		{
			"student": student,
			"academic_year": academic_year,
			"academic_term": academic_term,
			"docstatus": 1,
		},
	)
