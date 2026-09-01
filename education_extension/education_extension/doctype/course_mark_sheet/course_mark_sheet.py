# Copyright (c) 2026, Asante Solutions and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

from education_extension.education_extension.doctype.student_progress_report.student_progress_report import (
	round_half_up,
)

from education_extension.education_extension.doctype.course_mark_scheme.course_mark_scheme import (
	get_scheme,
)
from education_extension.education_extension.doctype.marking_settings.marking_settings import (
	order_students,
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

# The sittings a sheet can cover. Main is the course as everyone sits it; the
# other two are re-sittings, and each is opened for a different reason and so
# for a different set of students.
MAIN = "Main"
SUPPLEMENTARY = "Supplementary"
AEGROTAT = "Aegrotat"
SPECIAL = "Special"

# A supplementary is one paper covering the course, not a re-sit of each
# assessment, which is why it is reported in a column of its own.
SUPPLEMENTARY_GROUP = "Supplementary Exam"

# Who is entitled to a re-sitting: QA says so with a comment. Being absent is
# not enough on its own — an aegrotat needs documentation, and it is QA who has
# seen it.
SUPPLEMENTARY_COMMENT = "SUPP"
AEGROTAT_COMMENT = "AEGRO"

# Only exams are sat again. A missed test or assignment scores nothing, because
# there is no second chance at one.
COURSEWORK = "Coursework"


def entry_key(student, assessment_group):
	"""Identifies a cell on the sheet.

	As strings, always. A student id that looks like a number arrives from the
	browser as one — jQuery reads data-student="20240549" as 20240549 — and a key
	built from the raw values would miss the row it belongs to. The cell would
	then be dropped as one the sheet does not have, which is a save that saves
	nothing and says it worked.
	"""
	return (str(student), str(assessment_group))


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

		by_key = {entry_key(entry.student, entry.assessment_group): entry for entry in self.entries}
		applied = 0
		ignored = 0

		for change in changes:
			entry = by_key.get(entry_key(change.get("student"), change.get("assessment_group")))
			if not entry:
				ignored += 1
				continue

			status = change.get("status")
			if status not in (NOT_MARKED, MARKED, ABSENT):
				frappe.throw(_("{0} is not a mark status.").format(frappe.bold(status)))

			entry.status = status
			entry.raw_score = float(change.get("raw_score") or 0) if status == MARKED else 0
			applied += 1

		self.entered_by = frappe.session.user
		self.save()
		# `ignored` is reported rather than swallowed: a cell the sheet does not
		# recognise is far more likely a bug than a hostile browser, and saying
		# nothing is how a save that saved nothing looks like it worked.
		return {
			"applied": applied,
			"ignored": ignored,
			"outstanding": self.outstanding_count(),
		}

	# Once the marks are in, the sheet stops being a grid to fill and becomes a
	# set of results to read. These are the states where that is what it is.
	REVIEW_STATES = (SUBMITTED_FOR_CHECKING, CHECKED, MODERATED, APPROVED, RELEASED)

	@frappe.whitelist()
	def qa_review(self):
		"""The sheet as a reviewer reads it: a row per student with every score,
		the semester mark, the final mark and the comments.

		Built from the sheet's own entries rather than from where marks normally
		come from, because a sheet under review is not approved and so is not yet
		the record. The rows are assembled by the same function the Course Results
		report uses, so checking a sheet and reporting on it cannot show the same
		course two different ways.
		"""
		from education_extension.education_extension.marking import review_rows

		by_student = {}
		for entry in self.entries:
			by_student.setdefault(entry.student, [])
		for row in self.marks():
			by_student[row["student"]].append(row)

		moderated = self.moderation_method in (MODERATION_LINEAR, MODERATION_FLAT)

		if self.sitting == SUPPLEMENTARY:
			# One paper, reported on its own. A semester mark and a final mark
			# belong to the course, and this sheet is not the course.
			return {
				"mode": "supplementary",
				"criteria": [],
				"rows": self.supplementary_rows(),
				"moderated": moderated,
			}

		scheme = frappe.get_doc("Course Mark Scheme", self.mark_scheme)
		criteria = [
			{"assessment_group": row.assessment_group, "component": row.component}
			for row in scheme.criteria
		]

		if self.sitting == AEGROTAT:
			# An aegrotat paper only makes sense read against the course it belongs
			# to, so the rest of the marks come from the main sheet and the ones
			# sat here are pointed out.
			rows, sourced_here = self.aegrotat_rows(scheme)
			for row in rows:
				row["aegrotat"] = sorted(sourced_here.get(row["student"], ()))
			return {"mode": "aegrotat", "criteria": criteria, "rows": rows, "moderated": moderated}

		return {
			"mode": "main",
			"criteria": criteria,
			"rows": review_rows(self.course, self.academic_term, scheme.criteria, by_student),
			"moderated": moderated,
		}

	def supplementary_rows(self):
		"""A row per student sitting the supplementary: their mark and its comment."""
		from education_extension.education_extension.doctype.marking_settings.marking_settings import (
			order_students,
		)
		from education_extension.education_extension.marking import _course_remarks, _student_names

		marks = {}
		for entry in self.entries:
			score = self.effective_score(entry)
			marks[entry.student] = (
				f"{round_half_up(score / (entry.maximum_score or 100) * 100)}%"
				if score is not None
				else ("Absent" if entry.status == ABSENT else "-")
			)

		comments = _course_remarks(
			self.course, self.academic_term, "Supplementary Academic Remark", "supp_remark"
		)
		names = _student_names(marks)

		return [
			{
				"student": student,
				"student_name": names.get(student, student),
				"supplementary": marks[student],
				"supp_remark": comments.get(student, ""),
				"missing": [] if marks[student] != "-" else ["Supplementary Exam"],
			}
			for student in order_students(list(marks))
		]

	def aegrotat_rows(self, scheme):
		"""The course as it stands once this sheet's papers are counted.

		The other marks come from the main sheet, because an aegrotat paper is only
		meaningful as part of the result it completes. The aegrotat marks displace
		the ones they stand in for through the rule that already governs that, so
		nothing here decides precedence a second time.
		"""
		from education_extension.education_extension.marking import review_rows

		main = frappe.get_all(
			"Course Mark Sheet",
			filters={
				"course": self.course,
				"academic_term": self.academic_term,
				"sitting": MAIN,
				"docstatus": ["<", 2],
			},
			pluck="name",
			limit=1,
		)

		by_student = {}
		if main:
			for row in frappe.get_doc("Course Mark Sheet", main[0]).marks():
				by_student.setdefault(row["student"], []).append(row)

		sourced_here = {}
		for row in self.marks():
			by_student.setdefault(row["student"], []).append(row)
			sourced_here.setdefault(row["student"], set()).add(row["assessment_group"])

		# Only the students sitting this one, not the whole cohort of the main sheet.
		mine = {entry.student for entry in self.entries}
		by_student = {student: rows for student, rows in by_student.items() if student in mine}

		return review_rows(self.course, self.academic_term, scheme.criteria, by_student), sourced_here

	@frappe.whitelist()
	def generate_entries(self):
		"""Build a row per student per assessment from the course's scheme.

		Re-runnable while the sheet is with the lecturer: rows already carrying a
		mark are kept, rows for students no longer enrolled are dropped, and
		anything newly required is added.
		"""
		if self.workflow_state not in ENTRY_STATES:
			frappe.throw(_("Entries can only be generated while the sheet is awaiting or in entry."))

		wanted = self.wanted_entries()
		if not wanted:
			frappe.throw(self.nothing_to_generate_message())

		existing = {(entry.student, entry.assessment_group): entry for entry in self.entries}

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
		return {
			"students": len({student for student, _group in wanted}),
			"entries": len(self.entries),
		}

	def wanted_entries(self):
		"""Which (student, assessment) pairs belong on this sheet.

		Main covers everyone enrolled across every assessment the scheme weights.
		A re-sitting covers neither: only the students entitled to it, and only the
		assessments they are actually sitting again. Generating a re-sit sheet the
		way a main one is generated would put the whole cohort on it and then
		refuse to approve until every irrelevant cell was marked absent.
		"""
		if self.sitting == MAIN:
			scheme = frappe.get_doc("Course Mark Scheme", self.mark_scheme)
			return [
				(student, row.assessment_group)
				for student in self.get_students()
				for row in scheme.criteria
			]

		if self.sitting == SUPPLEMENTARY:
			return [(student, SUPPLEMENTARY_GROUP) for student in self.supplementary_students()]

		if self.sitting == AEGROTAT:
			return self.aegrotat_entries()

		frappe.throw(
			_(
				"A {0} sitting is either a supplementary or an aegrotat one. Open the sheet as "
				"whichever it is, so it knows who is sitting it and what they are sitting."
			).format(frappe.bold(SPECIAL))
		)

	def supplementary_students(self):
		"""Everyone QA has given the SUPP comment for this course and term.

		Entitlement is a QA judgement rather than a mark threshold — the legend
		distinguishes a supplementary from a subminimum failure that does not
		qualify for one — so the comment is what decides it."""
		from education_extension.education_extension.doctype.marking_settings.marking_settings import (
			order_students,
		)

		return order_students(
			frappe.get_all(
				"Academic Remark",
				filters={
					"course": self.course,
					"academic_term": self.academic_term,
					"remark": SUPPLEMENTARY_COMMENT,
					"docstatus": 1,
				},
				pluck="student",
				limit_page_length=0,
			)
		)

	def aegrotat_entries(self):
		"""Whoever missed a sitting, and only what they missed.

		Read off the main sheet, which is the only place an absence is recorded —
		an Assessment Result cannot say a student was absent, only that there is no
		mark, which is not the same thing.
		"""
		from education_extension.education_extension.doctype.marking_settings.marking_settings import (
			order_students,
		)

		main = frappe.get_all(
			"Course Mark Sheet",
			filters={
				"course": self.course,
				"academic_term": self.academic_term,
				"sitting": MAIN,
				"docstatus": ["<", 2],
			},
			pluck="name",
			limit=1,
		)
		if not main:
			frappe.throw(
				_(
					"{0} has no main sheet for {1}, and an absence is only recorded on one. "
					"Open the main sheet first."
				).format(frappe.bold(self.course), frappe.bold(self.academic_term))
			)

		entitled = set(
			frappe.get_all(
				"Academic Remark",
				filters={
					"course": self.course,
					"academic_term": self.academic_term,
					"remark": AEGROTAT_COMMENT,
					"docstatus": 1,
				},
				pluck="student",
				limit_page_length=0,
			)
		)
		if not entitled:
			return []

		absences = frappe.get_all(
			"Course Mark Sheet Entry",
			fields=["student", "assessment_group"],
			filters={
				"parent": main[0],
				"parenttype": "Course Mark Sheet",
				"status": ABSENT,
				"student": ["in", list(entitled)],
			},
			limit_page_length=0,
		)

		# Only exams are sat again; a missed test already counts as zero.
		components = self.assessment_components()

		by_student = {}
		for row in absences:
			if components.get(row.assessment_group) == COURSEWORK:
				continue
			by_student.setdefault(row.student, []).append(row.assessment_group)

		return [
			(student, group)
			for student in order_students(list(by_student))
			for group in sorted(by_student[student])
		]

	def nothing_to_generate_message(self):
		if self.sitting == SUPPLEMENTARY:
			return _("Nobody is marked {0} for {1} in {2}, so there is no supplementary to sit.").format(
				frappe.bold(SUPPLEMENTARY_COMMENT), frappe.bold(self.course), frappe.bold(self.academic_term)
			)
		if self.sitting == AEGROTAT:
			return _(
				"Nobody marked {0} for {1} in {2} missed an exam. Being absent is not enough on "
				"its own — an aegrotat needs the comment, which is how QA records that the "
				"documentation was seen."
			).format(
				frappe.bold(AEGROTAT_COMMENT),
				frappe.bold(self.course),
				frappe.bold(self.academic_term),
			)
		return _("No students are enrolled for {0} in {1}.").format(
			frappe.bold(self.course), frappe.bold(self.academic_term)
		)

	def get_students(self):
		"""Whose marks belong on this sheet, in the order Marking Settings lists a
		class in: the student group's members when one is named, otherwise everyone
		enrolled for the course this term."""
		if self.student_group:
			return order_students(
				frappe.get_all(
					"Student Group Student",
					filters={"parent": self.student_group, "parenttype": "Student Group", "active": 1},
					pluck="student",
					limit_page_length=0,
				)
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

		return order_students({row.student for row in enrolled if row.name in taking_the_course})

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

	def assessment_components(self):
		"""Which half of the mark each assessment belongs to, from the scheme."""
		if not self.mark_scheme:
			return {}
		return {
			row.assessment_group: row.component
			for row in frappe.get_all(
				"Course Mark Scheme Criterion",
				fields=["assessment_group", "component"],
				filters={"parent": self.mark_scheme, "parenttype": "Course Mark Scheme"},
				limit_page_length=0,
			)
		}

	def marks(self):
		"""The sheet's marks in the shape the calculation reads results in.

		An approved sheet is the record for its course. Nothing is copied into
		Assessment Result: that doctype recomputes its total from child detail rows
		and wants an Assessment Plan behind it, so writing one from here would mean
		threading plans through the sheet and keeping the same mark in two places.
		"""
		components = self.assessment_components()

		rows = []
		for entry in self.entries:
			score = self.effective_score(entry)
			if score is None:
				# A missed test or assignment scores nothing; there is no re-sitting
				# for one. A missed exam contributes nothing at all, leaving the
				# course incomplete until an aegrotat paper answers for it.
				if entry.status == ABSENT and components.get(entry.assessment_group) == COURSEWORK:
					score = 0
				else:
					continue
			rows.append(
				{
					"student": entry.student,
					"course": self.course,
					"assessment_group": entry.assessment_group,
					"sitting": self.sitting,
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
