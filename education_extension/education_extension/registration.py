# Copyright (c) 2026, Asante Solutions and contributors
# For license information, please see license.txt

"""What a student may register for, and why.

This module only reads. Writing the enrolment is step 05, kept apart so the
rules can be tested without creating anything — which matters more here than
usual, because registration is final on submission and nothing downstream
reviews what this decides.

Pass and fail come from the remark codes rather than from recomputed marks. The
code is what QA signed off, and reading it keeps registration independent of how
marks happen to be calculated.
"""

import frappe
from frappe import _
from frappe.utils import getdate, nowdate

from education_extension.education_extension.doctype.registration_period.registration_period import (
	next_period,
	open_period,
)
from education_extension.education_extension.doctype.registration_settings.registration_settings import (
	fee_block,
)
from education_extension.education_extension.doctype.student_progress_report.student_progress_report import (
	_program_semester,
	_semester_label,
)

# How a module stands for a student.
PASSED = "passed"
FAILED = "failed"
PENDING = "pending"
NEVER = "never"

# From the legend printed on the progress report. A condoned 49% carries the
# credit, so it carries the prerequisite too. Everything not named here and not
# pending is a fail: F, FS, FSE, FSUB, NSM, DISC.
PASS_CODES = frozenset({"P", "PD", "C", "PS", "PSE"})
PENDING_CODES = frozenset({"SUPP", "AEGRO"})

# The better outcome wins when a module has been attempted more than once.
_RANK = {NEVER: 0, FAILED: 1, PENDING: 2, PASSED: 3}

PREREQUISITE = "Prerequisite"
COREQUISITE = "Co-requisite"

# What the portal renders against each module.
REQUIRED = "required"
CARRIED_OVER = "carried_over"
PROVISIONAL = "provisional"
BLOCKED = "blocked"
ALREADY_PASSED = "passed"
AWAITING = "awaiting_result"
REGISTERED = "registered"

SELECTABLE = frozenset({REQUIRED, CARRIED_OVER, PROVISIONAL})


def outcome_of(code):
	"""What one remark code means for eligibility."""
	if not code:
		return NEVER
	code = code.strip().upper()
	if code in PASS_CODES:
		return PASSED
	if code in PENDING_CODES:
		return PENDING
	return FAILED


def academic_history(student):
	"""course -> PASSED / FAILED / PENDING across every attempt.

	A supplementary result supersedes the SUPP that granted it, so the two remark
	doctypes are collapsed per attempt before the best attempt is taken. An
	aegrotat needs no such handling: its mark displaces the main sitting, so the
	original remark is what changes.
	"""
	attempts = {}

	for row in frappe.get_all(
		"Academic Remark",
		filters={"student": student, "docstatus": 1},
		fields=["course", "academic_year", "academic_term", "remark"],
	):
		attempts[(row.course, row.academic_year, row.academic_term)] = row.remark

	for row in frappe.get_all(
		"Supplementary Academic Remark",
		filters={"student": student, "docstatus": 1},
		fields=["course", "academic_year", "academic_term", "supp_remark"],
	):
		attempts[(row.course, row.academic_year, row.academic_term)] = row.supp_remark

	history = {}
	for (course, _year, _term), code in attempts.items():
		outcome = outcome_of(code)
		if _RANK[outcome] > _RANK.get(history.get(course, NEVER), 0):
			history[course] = outcome
	return history


def curriculum_blocks():
	"""course -> the semester block that offers it, the earliest if several do.

	Deliberately not `get_course_semesters`, which lets a student enrolment
	override the curriculum. The question here is where a module sits in the
	programme, not where one student happens to be taking it.
	"""
	blocks = {}
	for row in frappe.get_all(
		"Program Course", fields=["course", "parent"], filters={"parenttype": "Program"}
	):
		block = _program_semester(row.parent)
		if block is None:
			continue
		if block < blocks.get(row.course, block + 1):
			blocks[row.course] = block
	return blocks


def courses_by_block(blocks=None):
	"""block -> its modules, in code order."""
	grouped = {}
	for course, block in (blocks or curriculum_blocks()).items():
		grouped.setdefault(block, []).append(course)
	for courses in grouped.values():
		courses.sort()
	return grouped


def programs_by_block():
	"""block -> the Program offering it."""
	programs = {}
	for name in frappe.get_all("Program", pluck="name"):
		block = _program_semester(name)
		if block is not None:
			programs.setdefault(block, name)
	return programs


def prerequisite_rules():
	"""course -> [(other course, kind)], from the seeded table."""
	rules = {}
	for row in frappe.get_all(
		"Course Prerequisite",
		filters={"parenttype": "Course", "parentfield": "custom_prerequisites"},
		fields=["parent", "course", "kind"],
		order_by="parent asc, idx asc",
	):
		rules.setdefault(row.parent, []).append((row.course, row.kind))
	return rules


def term_ordinal(academic_term):
	"""Which term of its academic year this is: 1, 2, ...

	Taken from the start dates rather than the term name, which is free text.
	"""
	year = frappe.db.get_value("Academic Term", academic_term, "academic_year")
	if not year:
		return None
	terms = frappe.get_all(
		"Academic Term",
		filters={"academic_year": year},
		order_by="term_start_date asc",
		pluck="name",
	)
	return terms.index(academic_term) + 1 if academic_term in terms else None


def highest_block(student):
	"""The furthest block the student has ever been enrolled in, 0 if none."""
	programs = frappe.get_all(
		"Program Enrollment", filters={"student": student, "docstatus": 1}, pluck="program"
	)
	blocks = [b for b in (_program_semester(p) for p in programs) if b is not None]
	return max(blocks) if blocks else 0


def next_block(student, academic_term):
	"""The block this student moves into, as {"block", "reason"}.

	Blocks alternate between the two terms — odd ones run in the first, even in
	the second — so a student who sat a term out has no block to move into this
	time. That is reported rather than silently skipping them a block forward.
	"""
	offered = programs_by_block()
	if not offered:
		return {"block": None, "reason": _("No programme is divided into semester blocks.")}

	candidate = highest_block(student) + 1
	if candidate > max(offered):
		return {"block": None, "reason": _("You have completed every semester of the programme.")}

	ordinal = term_ordinal(academic_term)
	if ordinal in (1, 2):
		wanted_parity = 1 if ordinal == 1 else 0
		if candidate % 2 != wanted_parity:
			return {
				"block": None,
				"reason": _("Your next semester block is {0}, which does not run in this term.").format(
					_semester_label(candidate)
				),
			}

	return {"block": candidate, "reason": None}


def unmet_prerequisites(course, history, alongside, rules):
	"""(blocking, outstanding, unverified) for one module.

	Only a *recorded failure* blocks. A prerequisite with no result on record at
	all does not, because absence of a result is not a failure: this system holds
	one term of history, and most students were enrolled into the middle of the
	programme, so the years they actually passed leave no trace here. Treating
	that silence as failure would block every student from everything.

	The cost is that a student who genuinely never took a prerequisite is not
	stopped either. That is the safer direction to be wrong in while the history
	is this thin, and the unverified list keeps it visible rather than silent.
	Once results accumulate over a few terms this can be tightened.

	Outstanding prerequisites are waiting on a supplementary or aegrotat result —
	enough to register on, but only provisionally. A co-requisite is satisfied by
	having passed it or by taking it in the same term, so it is judged against
	`alongside`.
	"""
	blocking = []
	outstanding = []
	unverified = []

	for other, kind in rules.get(course, ()):
		outcome = history.get(other, NEVER)

		if kind == COREQUISITE:
			# Being taken alongside satisfies it; so does having passed it. No
			# record means it is not being taken and was never passed here, which
			# for a co-requisite is the same unverified silence as above.
			if outcome == PASSED or other in alongside:
				continue
			if outcome == NEVER:
				unverified.append(other)
			else:
				blocking.append(other)
			continue

		if outcome == PASSED:
			continue
		if outcome == PENDING:
			outstanding.append(other)
		elif outcome == NEVER:
			unverified.append(other)
		else:
			blocking.append(other)

	return blocking, outstanding, unverified


def registered_courses(student, academic_year, academic_term):
	"""Modules already on a submitted enrolment for this term."""
	enrollments = frappe.get_all(
		"Program Enrollment",
		filters={
			"student": student,
			"academic_year": academic_year,
			"academic_term": academic_term,
			"docstatus": 1,
		},
		pluck="name",
	)
	if not enrollments:
		return set()
	return set(
		frappe.get_all(
			"Program Enrollment Course",
			filters={"parent": ["in", enrollments], "parenttype": "Program Enrollment"},
			pluck="course",
		)
	)


def options_for(student, on=None):
	"""Everything the registration page needs, in one call."""
	on = getdate(on or nowdate())

	period = open_period(on=on)
	if not period:
		upcoming = next_period(on=on)
		return {
			"state": "closed",
			"opens_on": str(upcoming.opens_on) if upcoming else None,
			"academic_term": upcoming.academic_term if upcoming else None,
		}

	placement = next_block(student, period.academic_term)
	if placement["block"] is None:
		return {"state": "not_offered", "message": placement["reason"], "period": _summary(period)}

	block = placement["block"]
	program = programs_by_block().get(block)
	if not program:
		return {
			"state": "not_offered",
			"message": _("No programme offers {0}.").format(_semester_label(block)),
			"period": _summary(period),
		}

	if not period.covers(program):
		return {
			"state": "closed",
			"message": _("Registration is not open for {0} yet.").format(program),
			"academic_term": period.academic_term,
		}

	history = academic_history(student)
	rules = prerequisite_rules()
	curriculum = courses_by_block()
	already = registered_courses(student, period.academic_year, period.academic_term)

	# This block, plus anything behind it with a result on record that is not a
	# pass. A module with no record at all is left out entirely: for most students
	# here that is their whole first year, passed before this system existed.
	candidates = {course: block for course in curriculum.get(block, ())}
	for earlier in range(1, block):
		for course in curriculum.get(earlier, ()):
			if history.get(course, NEVER) in (FAILED, PENDING):
				candidates.setdefault(course, earlier)

	# A co-requisite can be satisfied by a module taken in the same term, so each
	# module is judged against the whole proposed set rather than one at a time.
	alongside = {c for c in candidates if history.get(c, NEVER) != PASSED}

	rows = [
		_row(course, course_block, block, history, already, rules, alongside)
		for course, course_block in candidates.items()
	]
	rows.sort(key=lambda row: (row["block"], row["course"]))

	return {
		"state": "open",
		"period": _summary(period),
		"block": block,
		"block_label": _semester_label(block),
		"program": program,
		"fee_block": fee_block(student),
		"groups": _grouped(rows),
	}


def _row(course, course_block, block, history, already, rules, alongside):
	blocking, outstanding, unverified = unmet_prerequisites(course, history, alongside, rules)
	outcome = history.get(course, NEVER)

	if course in already:
		status, reason = REGISTERED, _("Already registered for this term.")
	elif outcome == PASSED:
		status, reason = ALREADY_PASSED, _("Already passed.")
	elif outcome == PENDING and course_block < block:
		status, reason = AWAITING, _("Waiting on a supplementary or aegrotat result.")
	elif blocking:
		status = BLOCKED
		reason = _("Not yet passed: {0}.").format(", ".join(_codes(blocking)))
	elif outstanding:
		status = PROVISIONAL
		reason = _("Provisional: {0} has no final result yet.").format(", ".join(_codes(outstanding)))
	elif course_block < block:
		status = CARRIED_OVER
		reason = _("Carried over from {0}.").format(_semester_label(course_block))
	else:
		status, reason = REQUIRED, None

	return {
		"course": course,
		"block": course_block,
		"status": status,
		"reason": reason,
		"selectable": status in SELECTABLE,
		"blocked_by": _codes(blocking),
		"provisional_on": _codes(outstanding),
		# Prerequisites this system has no result for, so it cannot confirm them.
		# Not a block; recorded so the gap can be seen rather than assumed away.
		"unverified": _codes(unverified),
	}


def _codes(courses):
	"""Course docnames shortened to their codes, so a reason line stays readable."""
	return [name.split(" - ")[0] for name in courses]


def _grouped(rows):
	groups = []
	for row in rows:
		if not groups or groups[-1]["block"] != row["block"]:
			groups.append({"block": row["block"], "label": _semester_label(row["block"]), "rows": []})
		groups[-1]["rows"].append(row)
	return groups


def _summary(period):
	return {
		"name": period.name,
		"academic_year": period.academic_year,
		"academic_term": period.academic_term,
		"opens_on": str(period.opens_on),
		"last_date_to_register": str(period.last_date_to_register),
	}


@frappe.whitelist()
def my_options():
	"""The logged-in student view.

	Session-scoped on purpose: accepting a student argument here would let any
	student read another student registration.
	"""
	from education_extension.education_extension.api import _current_user_student

	student = _current_user_student()
	if not student:
		return {"state": "no_student"}
	return options_for(student)
