# Copyright (c) 2026, Asante Solutions and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

from education_extension.education_extension.doctype.course_mark_scheme.course_mark_scheme import (
	get_scheme,
)

# The states the sheet moves through. Defined here as well as in the Workflow so
# the controller can reason about them without reading the workflow back.
AWAITING_ENTRY = "Awaiting Entry"
IN_ENTRY = "In Entry"
SUBMITTED_FOR_CHECKING = "Submitted for Checking"
CHECKED = "Checked"
MODERATED = "Moderated"
APPROVED = "Approved"
RELEASED = "Released"

# Marks may only be touched while the sheet is with the lecturer. Everything
# after that is a review of a fixed set of marks, which is the point of the
# checking step.
ENTRY_STATES = (AWAITING_ENTRY, IN_ENTRY)

# Moderation adjusts a cohort after checking. The raw score is never overwritten.
MODERATION_NONE = "None"
MODERATION_LINEAR = "Linear Scale"
MODERATION_FLAT = "Flat Adjustment"

# A Float cannot hold "not marked yet" — Frappe stores it as 0, which is also a
# real mark — so the distinction between unmarked, marked and absent is explicit.
NOT_MARKED = "Not Marked"
MARKED = "Marked"
ABSENT = "Absent"


def moderated_value(raw_score, maximum, method, value):
	"""A moderated mark, held inside the possible range.

	Scaling can push a strong mark past the maximum and a flat deduction can push
	a weak one below zero; neither is a mark anyone can be awarded.
	"""
	moderated = raw_score * value if method == MODERATION_LINEAR else raw_score + value
	return max(0, min(maximum, moderated))


class CourseMarkSheet(Document):
	def validate(self):
		self.validate_scheme()
		self.validate_no_duplicate_sheet()
		self.validate_entries()
		self.validate_marks_are_still_editable()

	def before_submit(self):
		"""Submission is the approval step. From here the sheet is the record of
		these marks — the calculation reads it in preference to any Assessment
		Result for the same course."""
		self.validate_every_mark_accounted_for()
		self.approved_by = frappe.session.user

	def validate_scheme(self):
		if self.mark_scheme:
			return
		scheme = get_scheme(self.course, self.academic_year)
		if not scheme:
			frappe.throw(
				_("{0} has no submitted mark scheme for {1}, so there is nothing to mark against.").format(
					frappe.bold(self.course), frappe.bold(self.academic_year)
				)
			)
		self.mark_scheme = scheme.name

	def validate_no_duplicate_sheet(self):
		existing = frappe.get_all(
			"Course Mark Sheet",
			filters={
				"course": self.course,
				"academic_term": self.academic_term,
				"sitting": self.sitting,
				"docstatus": ["<", 2],
				"name": ["!=", self.name],
			},
			pluck="name",
			limit=1,
		)
		if existing:
			frappe.throw(
				_("{0} already has a {1} sheet for {2}: {3}.").format(
					frappe.bold(self.course),
					frappe.bold(self.sitting),
					frappe.bold(self.academic_term),
					existing[0],
				)
			)

	def validate_entries(self):
		seen = set()
		for entry in self.entries:
			key = (entry.student, entry.assessment_group)
			if key in seen:
				frappe.throw(
					_("Row {0}: {1} already has a row for {2}.").format(
						entry.idx, frappe.bold(entry.student), frappe.bold(entry.assessment_group)
					)
				)
			seen.add(key)

			if entry.status != MARKED:
				entry.raw_score = 0
				entry.moderated_score = 0
				continue

			maximum = entry.maximum_score or 100
			if entry.raw_score < 0 or entry.raw_score > maximum:
				frappe.throw(
					_("Row {0}: {1} scored {2} out of {3} for {4}, which is not a possible mark.").format(
						entry.idx,
						frappe.bold(entry.student),
						entry.raw_score,
						maximum,
						frappe.bold(entry.assessment_group),
					)
				)

	def validate_marks_are_still_editable(self):
		"""Once the sheet has left the lecturer, the marks are what is under
		review, so they stop being editable. Without this the workflow would only
		be a label — anyone with write access could change a checked mark."""
		if self.is_new() or self.workflow_state in ENTRY_STATES:
			return

		previous = self.get_doc_before_save()
		if not previous:
			return

		def snapshot(doc):
			return {
				(entry.student, entry.assessment_group): (
					entry.raw_score,
					entry.status,
					entry.maximum_score,
				)
				for entry in doc.entries
			}

		if snapshot(self) != snapshot(previous):
			frappe.throw(
				_("The marks cannot be changed while the sheet is {0}. Return it for correction first.").format(
					frappe.bold(self.workflow_state)
				)
			)

	def validate_every_mark_accounted_for(self):
		"""A mark that is neither entered nor marked absent is an oversight, and
		approving it would quietly publish an incomplete sheet."""
		outstanding = [
			f"{entry.student} — {entry.assessment_group}"
			for entry in self.entries
			if entry.status == NOT_MARKED
		]
		if outstanding:
			frappe.throw(
				_("{0} mark(s) are neither entered nor marked absent, starting with {1}.").format(
					len(outstanding), frappe.bold(outstanding[0])
				)
			)

	# -- marks ---------------------------------------------------------------

	def effective_score(self, entry):
		"""The mark that counts, or None where there is not one: the moderated
		score while moderation stands, otherwise the score as awarded."""
		if entry.status != MARKED:
			return None
		if self.moderation_method in (MODERATION_LINEAR, MODERATION_FLAT):
			return entry.moderated_score
		return entry.raw_score

	def outstanding_count(self):
		"""How many marks are still neither entered nor accounted for as absent."""
		return sum(1 for entry in self.entries if entry.status == NOT_MARKED)

	@frappe.whitelist()
	def save_marks(self, changes):
		"""Apply a batch of marks from the entry grid.

		The grid sends only the cells that changed, so a lecturer working through
		a course of eighty students is not posting eight hundred rows back on every
		save. Anything the sheet does not have a row for is ignored rather than
		created: the roll comes from the enrolment, not from the browser.
		"""
		if self.workflow_state not in ENTRY_STATES:
			frappe.throw(_("Marks can only be entered while the sheet is with the lecturer."))

		if isinstance(changes, str):
			changes = frappe.parse_json(changes)

		by_key = {(entry.student, entry.assessment_group): entry for entry in self.entries}
		applied = 0

		for change in changes:
			entry = by_key.get((change.get("student"), change.get("assessment_group")))
			if not entry:
				continue

			status = change.get("status")
			if status not in (NOT_MARKED, MARKED, ABSENT):
				frappe.throw(_("{0} is not a mark status.").format(frappe.bold(status)))

			entry.status = status
			entry.raw_score = float(change.get("raw_score") or 0) if status == MARKED else 0
			applied += 1

		self.entered_by = frappe.session.user
		self.save()
		return {"applied": applied, "outstanding": self.outstanding_count()}

	@frappe.whitelist()
	def generate_entries(self):
		"""Build a row per student per assessment from the course's scheme.

		Re-runnable while the sheet is with the lecturer: rows already carrying a
		mark are kept, rows for students no longer enrolled are dropped, and
		anything newly required is added.
		"""
		if self.workflow_state not in ENTRY_STATES:
			frappe.throw(_("Entries can only be generated while the sheet is awaiting or in entry."))

		scheme = frappe.get_doc("Course Mark Scheme", self.mark_scheme)
		students = self.get_students()
		if not students:
			frappe.throw(
				_("No students are enrolled for {0} in {1}.").format(
					frappe.bold(self.course), frappe.bold(self.academic_term)
				)
			)

		existing = {(entry.student, entry.assessment_group): entry for entry in self.entries}
		wanted = [
			(student, row.assessment_group) for student in students for row in scheme.criteria
		]

		self.entries = []
		for student, assessment_group in wanted:
			kept = existing.get((student, assessment_group))
			self.append(
				"entries",
				{
					"student": student,
					"assessment_group": assessment_group,
					"raw_score": kept.raw_score if kept else 0,
					"moderated_score": kept.moderated_score if kept else 0,
					"status": kept.status if kept else NOT_MARKED,
					"maximum_score": (kept.maximum_score if kept else None) or 100,
				},
			)

		self.save()
		return {"students": len(students), "entries": len(self.entries)}

	def get_students(self):
		"""Whose marks belong on this sheet: the student group's members when one
		is named, otherwise everyone enrolled for the course this term."""
		if self.student_group:
			return frappe.get_all(
				"Student Group Student",
				filters={"parent": self.student_group, "parenttype": "Student Group", "active": 1},
				pluck="student",
				order_by="idx",
				limit_page_length=0,
			)

		enrolled = frappe.get_all(
			"Program Enrollment",
			fields=["name", "student"],
			filters={"academic_term": self.academic_term, "docstatus": 1},
			limit_page_length=0,
		)
		if not enrolled:
			return []

		# The course sits in the enrolment's child table, so the enrolments taking
		# it have to be looked up before their students can be.
		taking_the_course = set(
			frappe.get_all(
				"Program Enrollment Course",
				filters={
					"parent": ["in", [row.name for row in enrolled]],
					"parenttype": "Program Enrollment",
					"course": self.course,
				},
				pluck="parent",
				limit_page_length=0,
			)
		)

		return sorted({row.student for row in enrolled if row.name in taking_the_course})

	# -- moderation ----------------------------------------------------------

	@frappe.whitelist()
	def apply_moderation(self, method, value, reason):
		"""Adjust the cohort, leaving every raw score untouched.

		Recorded on the sheet — method, value, reason and author — so the Head
		approves the adjustment along with the marks.
		"""
		if self.workflow_state not in (CHECKED, MODERATED):
			frappe.throw(_("Moderation belongs between checking and approval."))
		if method not in (MODERATION_LINEAR, MODERATION_FLAT):
			frappe.throw(_("{0} is not a moderation method.").format(frappe.bold(method)))
		if not reason:
			frappe.throw(_("Moderation needs a reason."))

		value = float(value)
		for entry in self.entries:
			if entry.status != MARKED:
				continue
			entry.moderated_score = moderated_value(
				entry.raw_score, entry.maximum_score or 100, method, value
			)

		self.moderation_method = method
		self.moderation_value = value
		self.moderation_reason = reason
		self.moderated_by = frappe.session.user
		self.moderated_on = now_datetime()
		self.save()
		return self.moderation_summary()

	@frappe.whitelist()
	def clear_moderation(self):
		"""Put the raw marks back."""
		if self.workflow_state not in (CHECKED, MODERATED):
			frappe.throw(_("Moderation can only be cleared before approval."))

		for entry in self.entries:
			entry.moderated_score = 0
		self.moderation_method = MODERATION_NONE
		self.moderation_value = None
		self.moderation_reason = None
		self.moderated_by = None
		self.moderated_on = None
		self.save()

	def moderation_summary(self):
		moderated = [e for e in self.entries if e.status == MARKED]
		if not moderated:
			return {"adjusted": 0}
		return {
			"adjusted": len(moderated),
			"average_before": sum(e.raw_score for e in moderated) / len(moderated),
			"average_after": sum(e.moderated_score for e in moderated) / len(moderated),
		}

	# -- what the calculation reads -----------------------------------------

	def marks(self):
		"""The sheet's marks in the shape the calculation reads results in.

		An approved sheet is the record for its course. Nothing is copied into
		Assessment Result: that doctype recomputes its total from child detail rows
		and wants an Assessment Plan behind it, so writing one from here would mean
		threading plans through the sheet and keeping the same mark in two places.
		"""
		rows = []
		for entry in self.entries:
			score = self.effective_score(entry)
			if score is None:
				continue
			rows.append(
				{
					"student": entry.student,
					"course": self.course,
					"assessment_group": entry.assessment_group,
					"total_score": score,
					"maximum_score": entry.maximum_score or 100,
				}
			)
		return rows


@frappe.whitelist()
def return_for_correction(name, reason):
	"""Send a sheet back to the lecturer, recording who returned it and why.

	Available while the sheet is still in draft. An approved sheet has to be
	cancelled and amended instead, which is the heavier trail an already-approved
	mark deserves.
	"""
	if not reason:
		frappe.throw(_("Returning a sheet needs a reason."))

	sheet = frappe.get_doc("Course Mark Sheet", name)
	if sheet.docstatus != 0:
		frappe.throw(_("An approved sheet has to be cancelled and amended, not returned."))
	if sheet.workflow_state in ENTRY_STATES:
		frappe.throw(_("The sheet is already with the lecturer."))

	sheet.return_reason = "{0} — {1}".format(frappe.session.user, reason)
	sheet.workflow_state = IN_ENTRY
	sheet.save()
	sheet.add_comment("Comment", _("Returned for correction: {0}").format(reason))
	return sheet.workflow_state


@frappe.whitelist()
def generate_sheets(academic_year, academic_term, sitting="Main", courses=None):
	"""Open a sheet for every course that has a mark scheme for the year.

	Re-runnable: a course that already has a sheet for the term and sitting is
	left alone. Returns what it opened, skipped, and could not open.
	"""
	frappe.only_for(("Academics User", "Education Manager", "System Manager"))

	if isinstance(courses, str):
		courses = frappe.parse_json(courses)
	if not courses:
		courses = frappe.get_all(
			"Course Mark Scheme",
			filters={"academic_year": academic_year, "docstatus": 1},
			pluck="course",
			limit_page_length=0,
		)

	created, skipped, problems = [], [], []

	for course in courses:
		if frappe.db.exists(
			"Course Mark Sheet",
			{
				"course": course,
				"academic_term": academic_term,
				"sitting": sitting,
				"docstatus": ["<", 2],
			},
		):
			skipped.append(course)
			continue

		sheet = frappe.get_doc(
			{
				"doctype": "Course Mark Sheet",
				"course": course,
				"academic_year": academic_year,
				"academic_term": academic_term,
				"sitting": sitting,
				"workflow_state": AWAITING_ENTRY,
			}
		)
		try:
			sheet.insert()
			sheet.generate_entries()
		except frappe.ValidationError as error:
			problems.append({"course": course, "reason": str(error)})
			continue

		created.append(sheet.name)

	return {"created": created, "skipped": skipped, "problems": problems}
