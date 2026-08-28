# Copyright (c) 2026, Asante Solutions and contributors
# For license information, please see license.txt

"""A mark changed after it was approved, and why.

Remarking is not a step in the sequence — it can happen at any point once marks
are out — so it is its own document rather than a state on the sheet. Submitting
one applies the new mark and records what the old one was, who asked, who
approved, and on what grounds.

It writes to whichever record holds the mark: an approved Course Mark Sheet
where the course has one, otherwise the Assessment Result. The reader resolves
those two the same way, so a re-mark lands wherever the mark is actually read
from.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

from education_extension.education_extension.doctype.course_mark_sheet.course_mark_sheet import (
	MARKED,
	MODERATION_FLAT,
	MODERATION_LINEAR,
	moderated_value,
)


class MarkChange(Document):
	def validate(self):
		if not self.requested_by:
			self.requested_by = self.owner or frappe.session.user
		self.validate_there_is_a_mark_to_change()

	def before_submit(self):
		self.approved_by = frappe.session.user
		self.apply()

	def on_cancel(self):
		"""Cancelling records that the change was undone, but does not put the old
		mark back: by then it may have been marked again, and silently reversing
		to a stale figure would be worse than leaving it."""
		self.add_comment(
			"Comment",
			_("Cancelled. The mark of {0} stands until something else changes it.").format(
				self.new_score
			),
		)

	def validate_there_is_a_mark_to_change(self):
		if not self.find_mark():
			frappe.throw(
				_("{0} has no {1} mark for {2} in {3} to change.").format(
					frappe.bold(self.student),
					frappe.bold(self.assessment_group),
					frappe.bold(self.course),
					frappe.bold(self.academic_term),
				)
			)

	def find_mark(self):
		"""Where this mark lives, as (doctype, name, current score).

		The sheet is looked at first, because a course with an approved sheet is
		read from it and changing the Assessment Result instead would change
		nothing anybody sees.
		"""
		entry = frappe.db.sql(
			"""
			select entry.name, entry.raw_score, sheet.name as sheet
			from `tabCourse Mark Sheet Entry` entry
			join `tabCourse Mark Sheet` sheet on sheet.name = entry.parent
			where sheet.docstatus = 1
			  and sheet.course = %(course)s
			  and sheet.academic_term = %(academic_term)s
			  and sheet.sitting = %(sitting)s
			  and entry.student = %(student)s
			  and entry.assessment_group = %(assessment_group)s
			limit 1
			""",
			self.as_dict(),
			as_dict=True,
		)
		if entry:
			return ("Course Mark Sheet Entry", entry[0].name, entry[0].raw_score, entry[0].sheet)

		result = frappe.get_all(
			"Assessment Result",
			fields=["name", "total_score"],
			filters={
				"student": self.student,
				"course": self.course,
				"academic_term": self.academic_term,
				"assessment_group": self.assessment_group,
				"docstatus": 1,
			},
			limit=1,
		)
		if result:
			return ("Assessment Result", result[0].name, result[0].total_score, None)

		return None

	def apply(self):
		doctype, name, previous, sheet = self.find_mark()

		self.previous_score = previous
		self.applied_on = now_datetime()
		self.applied_to_doctype = doctype
		self.applied_to_name = name

		if doctype == "Course Mark Sheet Entry":
			self._apply_to_sheet_entry(name, sheet)
		else:
			frappe.db.set_value("Assessment Result", name, "total_score", self.new_score)
			frappe.get_doc("Assessment Result", name).add_comment(
				"Comment", self._note()
			)

	def _apply_to_sheet_entry(self, name, sheet_name):
		sheet = frappe.get_doc("Course Mark Sheet", sheet_name)
		updates = {"raw_score": self.new_score, "status": MARKED}

		# A sheet that was moderated keeps being moderated: the cohort adjustment
		# was approved on its own terms and applies to the new mark too.
		if sheet.moderation_method in (MODERATION_LINEAR, MODERATION_FLAT):
			entry = next(row for row in sheet.entries if row.name == name)
			updates["moderated_score"] = moderated_value(
				self.new_score,
				entry.maximum_score or 100,
				sheet.moderation_method,
				sheet.moderation_value,
			)

		frappe.db.set_value("Course Mark Sheet Entry", name, updates, update_modified=False)
		sheet.add_comment("Comment", self._note())

	def _note(self):
		return _("{0}: {1} changed from {2} to {3} for {4}. {5}").format(
			self.name,
			self.assessment_group,
			self.previous_score,
			self.new_score,
			self.student,
			self.reason,
		)


def has_remark_changes(student, academic_term):
	"""Whether anything was marked again for this student in this term.

	What puts a report onto the Remarking issue date.
	"""
	return bool(
		frappe.get_all(
			"Mark Change",
			filters={"student": student, "academic_term": academic_term, "docstatus": 1},
			limit=1,
		)
	)
