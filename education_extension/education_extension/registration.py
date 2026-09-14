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
from frappe.utils import escape_html, formatdate, getdate, now, nowdate

from education_extension.education_extension.doctype.registration_period.registration_period import (
	next_period,
	open_period,
)
from education_extension.education_extension.doctype.registration_settings.registration_settings import (
	fee_block,
	missing_result_blocks,
	show_unverified_prerequisites,
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


def carry_over_blocks(block):
	"""Earlier blocks whose modules may be retaken alongside `block`.

	A module is taught in its own semester and only there. A failed first-semester
	module cannot be repeated in a second semester — it waits for the next first
	semester. So carry-overs step back in twos rather than covering everything
	behind the student, and the eighteen students already holding two enrolments
	in one term bear this out: every pair is Semester 1 with Semester 3, and none
	mixes a first-semester block with a second-semester one.
	"""
	return list(range(block - 2, 0, -2))


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


def unmet_prerequisites(course, history, alongside, rules, strict=False):
	"""(blocking, outstanding, unverified) for one module.

	A recorded failure always blocks. What a prerequisite with *no result at all*
	means is the institution's call, carried by `strict` — see
	`registration_settings.missing_result_blocks`. Under `strict` it blocks like a
	failure; otherwise it lands in `unverified`, which reports the gap without
	stopping the student.

	`strict` is a parameter rather than a settings lookup so the rule can be
	tested both ways without touching the database.

	Outstanding prerequisites are waiting on a supplementary or aegrotat result —
	enough to register on, but only provisionally. A co-requisite is satisfied by
	having passed it or by taking it in the same term, so it is judged against
	`alongside`.
	"""
	blocking = []
	outstanding = []
	unverified = []

	def unmet(other):
		(blocking if strict else unverified).append(other)

	for other, kind in rules.get(course, ()):
		outcome = history.get(other, NEVER)

		if kind == COREQUISITE:
			# Being taken alongside satisfies it; so does having passed it.
			if outcome == PASSED or other in alongside:
				continue
			if outcome == NEVER:
				unmet(other)
			else:
				blocking.append(other)
			continue

		if outcome == PASSED:
			continue
		if outcome == PENDING:
			outstanding.append(other)
		elif outcome == NEVER:
			unmet(other)
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

	# A student who has already registered sees what they registered for, not an
	# offer to do it again. This has to come before the block calculation, which
	# would otherwise read their new enrolment as progress and advance them past
	# the term they are standing in — reporting the block they are already taking
	# as one that does not run this term.
	registered = _existing_registration(student, period)
	if registered:
		return dict({"state": "registered", "period": _summary(period)}, **registered)

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

	# This block, plus anything behind it the student has not passed. Whether a
	# module with no result counts as unpassed is the same institutional question
	# the prerequisite check asks, so it uses the same answer -- otherwise a
	# student could be blocked by a module that was never offered back to them.
	strict = missing_result_blocks()
	behind = (FAILED, PENDING, NEVER) if strict else (FAILED, PENDING)

	# Only what can actually be taken this term: this block, and unpassed modules
	# from the earlier blocks that run in the same semester. A module taught in
	# the other semester is left off the page entirely -- it cannot be registered
	# now, so listing it only invites the student to try.
	candidates = {course: block for course in curriculum.get(block, ())}
	for earlier in carry_over_blocks(block):
		for course in curriculum.get(earlier, ()):
			if history.get(course, NEVER) in behind:
				candidates.setdefault(course, earlier)

	# A co-requisite is satisfied by a module taken in the same term, and the
	# candidate set is now exactly that, so it is judged against all of it.
	alongside = {c for c in candidates if history.get(c, NEVER) != PASSED}

	rows = [
		_row(course, course_block, block, history, already, rules, alongside, strict)
		for course, course_block in candidates.items()
	]
	rows.sort(key=lambda row: (row["block"], row["course"]))

	# Stripped rather than never computed, so the rule stays in one place and only
	# what leaves the server changes. The field stays present and empty: the page
	# reads its length, and a missing key would be a different kind of bug.
	if not show_unverified_prerequisites():
		for row in rows:
			row["unverified"] = []

	return {
		"state": "open",
		"period": _summary(period),
		"block": block,
		"block_label": _semester_label(block),
		"program": program,
		"fee_block": fee_block(student),
		"groups": _grouped(rows),
		# Sent with the modules so the second step needs no further call, and so
		# the wording the student is shown is the wording that gets recorded.
		"declarations": declarations(student),
	}


def declarations(student=None):
	"""The wording shown at the consent step, from Registration Settings.

	Placeholders are filled in for `student`, so the text reads as a completed
	document rather than a form with blanks in it — which is what the paper
	version becomes once it is signed, and what the recorded consent should say.
	"""
	settings = frappe.get_cached_doc("Registration Settings")
	wording = {
		"prerequisites": settings.prerequisite_declaration or "",
		"popia": settings.popia_consent or "",
	}
	if not student:
		return wording

	values = declaration_values(student)
	return {key: fill_declaration(text, values) for key, text in wording.items()}


def declaration_values(student):
	"""What each placeholder stands for."""
	details = frappe.db.get_value(
		"Student",
		student,
		["student_name", "custom_id_number", "custom_student_number"],
		as_dict=True,
	) or frappe._dict()

	# The docname is the student number, so it is the last resort for both.
	number = details.custom_student_number or student

	return {
		"{student_name}": details.student_name or "",
		# The form asks for an ID number or a student number, so one stands in for
		# the other where it is missing.
		"{id_number}": details.custom_id_number or number,
		"{student_number}": number,
		# The date the consent is given. On the page this is the day it was loaded;
		# on the record it is the day it was agreed, which is the one that counts.
		"{date}": formatdate(nowdate(), "d MMMM yyyy"),
	}


def fill_declaration(text, values):
	"""Replacement rather than `str.format`.

	The wording is HTML that staff can edit, and a single stray brace in it would
	make formatting raise — on a legal declaration, at the moment a student is
	trying to register.
	"""
	for token, value in values.items():
		text = text.replace(token, escape_html(value))
	return text


def _row(course, course_block, block, history, already, rules, alongside, strict=False):
	blocking, outstanding, unverified = unmet_prerequisites(
		course, history, alongside, rules, strict
	)
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
	elif course_block < block:
		# Tested before `outstanding`, because a carry-over stays the student's
		# choice whether or not one of its prerequisites is still pending. The
		# other order made it PROVISIONAL, and PROVISIONAL is mandatory -- so a
		# module the student was free to decline became compulsory because a
		# supplementary result had not landed. It is still registered
		# provisionally; that is `provisional_on` below, not the status.
		status = CARRIED_OVER
		reason = _("Carried over from {0}.").format(_semester_label(course_block))
		if outstanding:
			reason += " " + _("Provisional: {0} has no final result yet.").format(
				", ".join(_codes(outstanding))
			)
	elif outstanding:
		status = PROVISIONAL
		reason = _("Provisional: {0} has no final result yet.").format(", ".join(_codes(outstanding)))
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
		# Prerequisites with no result on record, so they cannot be confirmed
		# either way. Reported rather than assumed away -- and empty when the
		# institution has chosen to treat silence as a failure, because then they
		# are in `blocked_by` instead.
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


def _existing_registration(student, period):
	"""What the student has already registered for this term, or None.

	Provisional rows are named as such: a student is entitled to know that one of
	their modules rests on a result that has not landed.
	"""
	enrollments = frappe.get_all(
		"Program Enrollment",
		filters={
			"student": student,
			"academic_year": period.academic_year,
			"academic_term": period.academic_term,
			"docstatus": 1,
		},
		fields=["name", "program"],
	)
	if not enrollments:
		return None

	program_of = {e.name: e.program for e in enrollments}
	rows = frappe.get_all(
		"Program Enrollment Course",
		filters={"parent": ["in", list(program_of)], "parenttype": "Program Enrollment"},
		fields=["parent", "course", "custom_provisional", "custom_provisional_on"],
		order_by="parent asc, idx asc",
	)

	return {
		"programs": sorted(set(program_of.values())),
		"modules": [
			{
				"course": row.course,
				"program": program_of[row.parent],
				"provisional": bool(row.custom_provisional),
				"provisional_on": row.custom_provisional_on,
			}
			for row in rows
		],
	}


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


# ---------------------------------------------------------------------------
# Registering
# ---------------------------------------------------------------------------

# The student chooses among carry-overs. Their own block is not optional.
MANDATORY = frozenset({REQUIRED, PROVISIONAL})


@frappe.whitelist()
def register(courses, declarations=None, signatures=None):
	"""Register the logged-in student. Final on submission — there is no draft.

	`declarations` carries the two agreements from the consent step, as
	{"prerequisites": true, "popia": true}; both are required. `signatures`
	carries the drawn marks, as {"student": <data URI>, "guardian_name": str,
	"guardian": <data URI>}; the student's is required and the guardian's is not.
	"""
	from education_extension.education_extension.api import _current_user_student

	student = _current_user_student()
	if not student:
		frappe.throw(_("No student record is linked to your account."))

	if isinstance(courses, str):
		courses = frappe.parse_json(courses)
	if isinstance(declarations, str):
		declarations = frappe.parse_json(declarations)
	if isinstance(signatures, str):
		signatures = frappe.parse_json(signatures)

	return register_student(
		student, list(courses or ()), declarations or {}, signatures or {}
	)


def register_student(student, courses, agreed=None, signatures=None):
	"""Create and submit the enrolments for `courses`, returning what was made.

	Eligibility is recomputed here rather than trusted from the request. The page
	that sent it may be minutes or hours stale, and with no approval step this is
	the last point at which anything checks.
	"""
	options = options_for(student)
	if options["state"] == "registered":
		frappe.throw(_("You have already registered for this term."))
	if options["state"] != "open":
		frappe.throw(_("Registration is not open."))

	if options["fee_block"]:
		frappe.throw(
			_("Registration is blocked while {0} is outstanding on your account.").format(
				frappe.utils.fmt_money(options["fee_block"])
			)
		)

	rows = {row["course"]: row for group in options["groups"] for row in group["rows"]}
	chosen = list(dict.fromkeys(courses))

	unknown = [c for c in chosen if c not in rows]
	if unknown:
		frappe.throw(_("Not offered to you this term: {0}.").format(", ".join(_codes(unknown))))

	refused = [c for c in chosen if not rows[c]["selectable"]]
	if refused:
		frappe.throw(
			_("You cannot take {0}. {1}").format(
				", ".join(_codes(refused)),
				" ".join(rows[c]["reason"] or "" for c in refused).strip(),
			)
		)

	missing = [c for c, row in rows.items() if row["status"] in MANDATORY and c not in chosen]
	if missing:
		frappe.throw(
			_("These modules are part of {0} and cannot be left out: {1}.").format(
				options["block_label"], ", ".join(_codes(missing))
			)
		)

	_validate_corequisites(student, chosen, rows)

	programs = programs_by_block()
	grouped = {}
	for course in chosen:
		program = programs.get(rows[course]["block"])
		if not program:
			frappe.throw(_("No programme offers {0}.").format(_codes([course])[0]))
		grouped.setdefault(program, []).append(course)

	# Recorded before anything is enrolled, so a registration cannot exist
	# without the consent that permitted it. Both are in the one transaction, so
	# a failure at either end leaves neither.
	consent = _record_consent(student, options["period"], agreed or {}, signatures or {})

	created = [
		_create_enrollment(student, program, grouped[program], rows, options["period"])
		for program in sorted(grouped)
	]

	return {"enrollments": created, "courses": chosen, "consent": consent}


def unmet_corequisites(chosen, taking, history, rules):
	"""Co-requisites of the chosen modules that are not being taken, as pairs.

	Pure, so the rule can be checked without a site.
	"""
	unmet = []
	for course in chosen:
		for other, kind in rules.get(course, ()):
			if kind != COREQUISITE:
				continue
			if other in taking or history.get(other, NEVER) == PASSED:
				continue
			unmet.append((course, other))

	return unmet


def _validate_corequisites(student, chosen, rows):
	"""A co-requisite has to be among the modules actually taken.

	`options_for` judges co-requisites against everything *offered*, which is
	right for deciding whether a module can be shown as selectable — at that
	point nothing has been chosen yet. It is not enough at submission: a
	co-requisite offered as a carry-over is the student's to decline, so the
	module depending on it could be kept while the module satisfying it was
	unticked, and nothing looked again.
	"""
	# Already on a submitted enrolment for this term counts as taken alongside.
	taking = set(chosen) | {c for c, row in rows.items() if row["status"] == REGISTERED}
	unmet = unmet_corequisites(chosen, taking, academic_history(student), prerequisite_rules())

	if unmet:
		frappe.throw(
			_("These modules must be taken alongside another you have not chosen: {0}.").format(
				"; ".join(
					_("{0} needs {1}").format(_codes([course])[0], _codes([other])[0])
					for course, other in unmet
				)
			)
		)


def _record_consent(student, period, agreed, signatures):
	"""Store what the student agreed to, and refuse to proceed without it."""
	if not agreed.get("prerequisites"):
		frappe.throw(_("You must declare that you meet the pre-requisites of these modules."))
	if not agreed.get("popia"):
		frappe.throw(_("You must consent to your personal information being processed."))

	wording = declarations(student)
	guardian_name = (signatures.get("guardian_name") or "").strip()
	guardian_signature = (signatures.get("guardian") or "").strip()

	consent = frappe.new_doc("Registration Consent")
	consent.update(
		{
			"student": student,
			"academic_year": period["academic_year"],
			"academic_term": period["academic_term"],
			"consented_at": now(),
			"ip_address": frappe.local.request_ip,
			"prerequisites_declared": 1,
			"popia_consented": 1,
			"student_signature": (signatures.get("student") or "").strip(),
			# Taken from whether a guardian actually signed rather than from a
			# separate claim that one did, so the flag cannot disagree with the
			# record it describes.
			"signed_by_guardian": 1 if (guardian_name or guardian_signature) else 0,
			"guardian_name": guardian_name,
			"guardian_signature": guardian_signature,
			# Snapshotted, not referenced: the institution can amend the wording,
			# and this record has to keep saying what this student was shown.
			"declaration_text": wording["prerequisites"],
			"consent_text": wording["popia"],
		}
	)
	consent.flags.ignore_permissions = True
	consent.insert()
	consent.submit()
	return consent.name


def _create_enrollment(student, program, courses, rows, period):
	duplicate = frappe.db.exists(
		"Program Enrollment",
		{
			"student": student,
			"program": program,
			"academic_year": period["academic_year"],
			"academic_term": period["academic_term"],
			"docstatus": ["<", 2],
		},
	)
	if duplicate:
		frappe.throw(_("You are already enrolled for {0} this term.").format(program))

	enrollment = frappe.new_doc("Program Enrollment")
	enrollment.student = student
	enrollment.program = program
	enrollment.academic_year = period["academic_year"]
	enrollment.academic_term = period["academic_term"]
	enrollment.enrollment_date = nowdate()

	for course in courses:
		row = rows[course]
		enrollment.append(
			"courses",
			{
				"course": course,
				# From what it is waiting on rather than from the status. A
				# carry-over can be waiting on a result too, and reading the
				# status would leave that one unflagged and never revisited when
				# the result landed.
				"custom_provisional": 1 if row["provisional_on"] else 0,
				"custom_provisional_on": ", ".join(row["provisional_on"]) or None,
			},
		)

	# Registration is a privileged action taken on the student behalf: the gate is
	# the eligibility check above, not the role. `Document.has_permission` consults
	# only the flag on the document itself -- `frappe.flags.ignore_permissions` is
	# read nowhere in the document write path -- so it goes on the document.
	#
	# Nothing here runs as anyone but the student. It used to have to, because
	# inserting an enrolment fired LMS Server Scripts the student had no rights
	# for; those are queued jobs now and run as their own service user.
	enrollment.flags.ignore_permissions = True
	enrollment.insert()

	_create_course_enrollments(enrollment)
	enrollment.submit()

	return enrollment.name


def _create_course_enrollments(enrollment):
	"""Create the Course Enrollment rows before the enrolment is submitted.

	Submitting runs the education app's own `create_course_enrollments`, which
	builds each one with an unflagged `frappe.get_doc(...).save()` -- a document we
	never touch and so cannot grant permission on. That single call was the last
	thing forcing this whole write to run elevated.

	It is guarded by `db.exists`, though, so creating the rows here first means its
	loop finds them and never reaches that save. Same records, made deliberately
	and owned by the student who registered.

	If the education app ever drops that guard this does not corrupt anything:
	`CourseEnrollment.validate_duplication` throws, so the failure is loud at
	registration rather than silent.
	"""
	for row in enrollment.courses:
		course_enrollment = frappe.get_doc(
			{
				"doctype": "Course Enrollment",
				"student": enrollment.student,
				"course": row.course,
				"program_enrollment": enrollment.name,
				"enrollment_date": enrollment.enrollment_date,
			}
		)
		course_enrollment.flags.ignore_permissions = True
		course_enrollment.insert()


# ---------------------------------------------------------------------------
# Settling provisional registrations
# ---------------------------------------------------------------------------


def provisional_rows(student=None):
	"""[(enrolment, course row)] for every provisional registration in force."""
	filters = {"docstatus": 1}
	if student:
		filters["student"] = student

	enrollments = {
		e.name: e
		for e in frappe.get_all(
			"Program Enrollment",
			filters=filters,
			fields=["name", "student", "program", "academic_year", "academic_term"],
		)
	}
	if not enrollments:
		return []

	rows = frappe.get_all(
		"Program Enrollment Course",
		filters={
			"parent": ["in", list(enrollments)],
			"parenttype": "Program Enrollment",
			"custom_provisional": 1,
		},
		fields=["name", "parent", "course", "custom_provisional_on"],
	)
	return [(enrollments[row.parent], row) for row in rows]


def resolve_provisional_registrations(student=None):
	"""Act on provisional registrations whose result has landed.

	Passed, and the provisional mark comes off. Failed, and the module goes —
	unless it is too late to change the registration, or the student has already
	done work on it, in which case it is left in place and reported instead.
	Removing a module someone has been attending is worse than the wrong
	registration standing.

	Idempotent, so the doc hooks and the daily sweep can both call it.
	"""
	pending = provisional_rows(student)
	if not pending:
		return {"cleared": 0, "removed": 0, "reported": 0}

	rules = prerequisite_rules()
	strict = missing_result_blocks()
	histories = {}
	tally = {"cleared": 0, "removed": 0, "reported": 0}

	for enrollment, row in pending:
		if enrollment.student not in histories:
			histories[enrollment.student] = academic_history(enrollment.student)

		alongside = registered_courses(
			enrollment.student, enrollment.academic_year, enrollment.academic_term
		)
		blocking, outstanding, _unverified = unmet_prerequisites(
			row.course, histories[enrollment.student], alongside, rules, strict
		)

		if outstanding:
			continue

		if not blocking:
			_clear_provisional(row)
			tally["cleared"] += 1
			continue

		if _may_still_change(enrollment) and not _work_started(enrollment, row.course):
			_deregister(enrollment, row, blocking)
			tally["removed"] += 1
		else:
			_report_to_staff(enrollment, row, blocking)
			tally["reported"] += 1

	# No commit here on purpose. Every real caller already provides one -- the
	# background job runner commits on success, and so does the scheduler -- and
	# committing inside the function would break the rollback that test isolation
	# depends on, silently persisting fixtures.
	return tally


def _may_still_change(enrollment, on=None):
	"""Whether this registration may still be altered without a person deciding.

	Bounded by the last date to register: after it, a registration is what it is.
	A term with no period on record is treated as closed, because nothing should
	be deleted on the strength of a window nobody set.
	"""
	last_date = frappe.db.get_value(
		"Registration Period", {"academic_term": enrollment.academic_term}, "last_date_to_register"
	)
	if not last_date:
		return False
	return getdate(on or nowdate()) <= getdate(last_date)


def _work_started(enrollment, course):
	"""Whether the student has any record against this module already."""
	course_enrollments = frappe.get_all(
		"Course Enrollment",
		filters={"program_enrollment": enrollment.name, "course": course},
		pluck="name",
	)
	for name in course_enrollments:
		for doctype in ("Course Activity", "Quiz Activity"):
			if frappe.db.exists(doctype, {"enrollment": name}):
				return True

	return bool(
		frappe.db.exists(
			"Assessment Result",
			{
				"student": enrollment.student,
				"course": course,
				"academic_term": enrollment.academic_term,
			},
		)
	)


def _clear_provisional(row):
	frappe.db.set_value(
		"Program Enrollment Course",
		row.name,
		{"custom_provisional": 0, "custom_provisional_on": None},
		update_modified=False,
	)


def _deregister(enrollment, row, blocking):
	doc = frappe.get_doc("Program Enrollment", enrollment.name)
	doc.courses = [course for course in doc.courses if course.name != row.name]

	# On the document, not `frappe.flags`: the global flag is not consulted in
	# the document write path. This normally runs from a background job as
	# Administrator, where it makes no difference -- but it is also reachable
	# from a request, and then it does.
	doc.flags.ignore_permissions = True
	doc.save()

	for name in frappe.get_all(
		"Course Enrollment",
		filters={"program_enrollment": enrollment.name, "course": row.course},
		pluck="name",
	):
		frappe.delete_doc("Course Enrollment", name, ignore_permissions=True)

	note = _("{0} was removed: {1} was not passed.").format(
		_codes([row.course])[0], ", ".join(_codes(blocking))
	)
	if not doc.courses:
		note += " " + _("This enrolment now has no modules on it.")

	doc.add_comment("Info", note)
	_tell_student(
		enrollment,
		_("A module has been removed from your registration"),
		_(
			"{0} was registered while {1} had no final result. That result is now a "
			"fail, so the module has been removed from your registration for {2}. "
			"Speak to the academic office if you believe this is wrong."
		).format(
			_codes([row.course])[0],
			", ".join(_codes(blocking)),
			enrollment.academic_term,
		),
	)


def _report_to_staff(enrollment, row, blocking):
	"""Leave the registration alone and put the decision in front of a person.

	The comment is the audit trail; the flag is what makes it findable. A comment
	on a submitted enrolment nobody opens is not a queue, so `custom_needs_review`
	carries the case into the Registration Status report. The provisional mark
	comes off at the same time, or the daily sweep would raise it again every day.
	"""
	frappe.get_doc("Program Enrollment", enrollment.name).add_comment(
		"Info",
		_(
			"{0} was registered provisionally and {1} has now failed, but the "
			"registration was not changed automatically — either the last date to "
			"register has passed or there is already work recorded against the "
			"module. Needs a decision."
		).format(_codes([row.course])[0], ", ".join(_codes(blocking))),
	)
	frappe.db.set_value(
		"Program Enrollment Course",
		row.name,
		{"custom_provisional": 0, "custom_provisional_on": None, "custom_needs_review": 1},
		update_modified=False,
	)


def _tell_student(enrollment, subject, message):
	"""In-app notification, and email when the site can send it."""
	user = frappe.db.get_value("Student", enrollment.student, "user")
	if not user:
		return

	frappe.get_doc(
		{
			"doctype": "Notification Log",
			"for_user": user,
			"type": "Alert",
			"document_type": "Program Enrollment",
			"document_name": enrollment.name,
			"subject": subject,
			"email_content": message,
		}
	).insert(ignore_permissions=True)

	if not frappe.db.exists("Email Account", {"enable_outgoing": 1, "default_outgoing": 1}):
		return
	try:
		frappe.sendmail(recipients=[user], subject=subject, message=message)
	except Exception:
		# The in-app notice has already landed; a mail failure must not undo a
		# deregistration that is otherwise correct.
		frappe.log_error(title="Registration notice email failed")


def on_remark_change(doc, method=None):
	"""Re-check this student provisional registrations when a result settles."""
	frappe.enqueue(
		"education_extension.education_extension.registration.resolve_provisional_registrations",
		student=doc.student,
		queue="short",
		enqueue_after_commit=True,
	)
