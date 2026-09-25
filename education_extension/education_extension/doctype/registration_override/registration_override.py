# Copyright (c) 2026, Asante Solutions and contributors
# For license information, please see license.txt

"""A registrar letting a student register despite their results.

The academic standing rule next door is arithmetic, and arithmetic is a poor
judge of whether a particular student should be given another term. Illness,
a death at home, results that were never captured when this app was adopted
mid-programme — none of that is in the failure count, and all of it is a reason
a registrar might say yes.

So the rule is appealable by design, and this is the appeal. It is a record
rather than a switch: who allowed it, when, and on what grounds, against a
snapshot of the standing it was granted over. The alternative way of achieving
the same thing — editing the student's results until the rule stops firing —
would leave no trace and corrupt the transcript.

Submitting is the grant. Cancelling revokes it, and the student is blocked again
from that moment, which is why nothing here copies the permission onto the
student or their enrolment: there would then be two answers to whether they may
register, and only one of them would be revoked.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now

from education_extension.education_extension.academic_standing import standing


class RegistrationOverride(Document):
	def validate(self):
		self.validate_only_one_is_in_force()
		self.record_the_standing_it_was_granted_over()

	def before_submit(self):
		# Set here rather than on validate, because a draft is not a grant. Until
		# it is submitted nobody has allowed anything, and stamping a name on it
		# would say otherwise.
		self.granted_by = frappe.session.user
		self.granted_on = now()

	def on_submit(self):
		self.tell_the_student()

	def validate_only_one_is_in_force(self):
		"""One live permission per student per term.

		Not a correctness problem — `overrides_for` would simply pick one — but a
		second grant is how the reason on the record stops matching the decision
		anyone actually reads. Amend the first instead, which keeps the chain.
		"""
		existing = frappe.db.exists(
			"Registration Override",
			{
				"student": self.student,
				"academic_term": self.academic_term,
				"docstatus": 1,
				"name": ["!=", self.name],
			},
		)
		if existing:
			frappe.throw(
				_("{0} has already been allowed to register for {1}, by {2}.").format(
					frappe.bold(self.student_name or self.student),
					self.academic_term,
					frappe.utils.get_link_to_form("Registration Override", existing),
				)
			)

	def record_the_standing_it_was_granted_over(self):
		"""Snapshot what the rule said about this student at the time.

		Results move — a supplementary lands, a mark is changed — and a permission
		granted over five failures reads very differently beside a record that now
		shows two. Recomputed on every save while the document is a draft, so what
		is stored is what the person submitting it was looking at.
		"""
		assessed = standing(self.student, self.academic_term)
		self.modules_failed = assessed["failed"]
		self.modules_attempted = assessed["attempted"]
		self.failure_rate = assessed["rate"]
		self.failed_modules = ", ".join(assessed["failed_modules"])

	def tell_the_student(self):
		"""Say so, rather than leaving them to discover it by trying again.

		Registration windows are short and a student who has been turned away once
		has no reason to keep checking.
		"""
		from education_extension.education_extension.registration import notify_student

		message = _(
			"You have been allowed to register for {0} despite your results. "
			"Open the registration page to continue."
		).format(self.academic_term)
		if self.conditions:
			message += "<br><br>" + _("Conditions: {0}").format(self.conditions)

		notify_student(
			self.student,
			_("You may now register"),
			message,
			doctype=self.doctype,
			name=self.name,
		)
