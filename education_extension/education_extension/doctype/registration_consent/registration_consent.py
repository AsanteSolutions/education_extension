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

import frappe
from frappe import _
from frappe.model.document import Document


class RegistrationConsent(Document):
	def validate(self):
		self.validate_both_declarations_given()
		self.validate_the_wording_was_recorded()

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
