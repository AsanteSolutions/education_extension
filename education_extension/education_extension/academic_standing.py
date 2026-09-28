# Copyright (c) 2026, Asante Solutions and contributors
# For license information, please see license.txt

"""Whether a student has failed too much to be let into another term.

The prerequisite rules next door ask about one module at a time: may this
student take that one. This asks the other question, about the record as a
whole — a student failing most of what they take is not helped by being enrolled
in more of it, and every institution draws that line somewhere.

Where it is drawn is a policy decision and not a fact about the code, so nothing
here is hard-coded. The thresholds and the span of record they are measured over
are in Registration Settings, and the rule is inert until someone turns it on.
It has to be: this app was adopted mid-programme, and a rule counting failures
off an incomplete record would exclude students on the strength of results that
were simply never captured.

The rule is never the last word. A registrar can let any student register
anyway by granting them a Registration Override, which records the decision and
its reason rather than quietly editing the results it was taken against.
"""

import frappe
from frappe import _
from frappe.utils import getdate

# The outcome vocabulary is registration's, including the two private helpers.
# Restating either here would be a second place for the remark codes to be
# interpreted, and the two would eventually disagree about what a code means.
from education_extension.education_extension.registration import (
	_RANK,
	FAILED,
	NEVER,
	PASSED,
	PENDING,
	_codes,
	attempts_for,
	outcome_of,
)

# What span of the record the thresholds are measured over, narrowest first.
LATEST_TERM = "Most recent semester"
LATEST_YEAR = "Most recent academic year"
WHOLE_RECORD = "Whole record"

# Where the dates that order each window are read from. The whole record needs
# no dates, so it is absent rather than mapped to nothing: the absence is what
# says there is no window to pick.
WINDOW_SOURCES = {
	LATEST_TERM: ("Academic Term", "term_start_date"),
	LATEST_YEAR: ("Academic Year", "year_start_date"),
}

# How a student the rule has something to say about is named on a report. Here
# rather than on either report, because both of them say it and two spellings of
# the same state read as two different states.
CANNOT_REGISTER = "Cannot register"
ALLOWED_ANYWAY = "Allowed anyway"

# Sorts a year or term with no start date on record behind every one that has
# a date, rather than raising when the two are compared.
_UNDATED = getdate("1900-01-01")


def rule():
	"""The configured threshold, or None when the institution has set none.

	None is returned for a rule that is switched on but has no threshold on it,
	because the alternative reading — nought failures allowed — excludes every
	student who has ever failed anything, which is not what leaving a field empty
	means.
	"""
	settings = frappe.get_cached_doc("Registration Settings")
	if not settings.block_on_failed_modules:
		return None

	most = int(settings.maximum_failed_modules or 0)
	rate = float(settings.maximum_failure_rate or 0)
	if not most and not rate:
		return None

	return frappe._dict(
		{"most": most, "rate": rate, "window": settings.failure_window or LATEST_YEAR}
	)


def period_starts(window):
	"""period -> the date it starts, for ordering the candidates for `window`.

	Read rather than inferred from the name. Academic years and terms are both
	named freely, and "2025-2026" only happens to sort correctly; the institution
	could rename them tomorrow and the window would silently start picking the
	wrong one.

	Empty for the whole record, which has no window to pick and so needs no dates.
	"""
	source = WINDOW_SOURCES.get(window)
	if not source:
		return {}

	doctype, field = source
	return {
		row.name: getdate(row.get(field)) if row.get(field) else _UNDATED
		for row in frappe.get_all(doctype, fields=["name", field])
	}


def _period_of(rule):
	"""What a sitting is grouped by, for the window this rule measures over.

	None for every sitting where there is no window, which is what stops the
	narrowing below from happening at all rather than being a special case in it.
	"""
	if not rule or rule.window == WHOLE_RECORD:
		return lambda _year, _term: None
	if rule.window == LATEST_TERM:
		return lambda _year, term: term
	return lambda year, _term: year


def _started(starts, period):
	"""When a year or term began, as a date, whatever the caller handed over.

	Coerced rather than assumed, because a period missing from the map would
	otherwise be a date compared against a string, and the window would raise
	instead of picking one.
	"""
	return getdate(starts.get(period)) if starts.get(period) else _UNDATED


def assess(attempts, rule, starts=None):
	"""How one student's attempts stand against `rule`.

	Pure, so the line an institution draws can be checked without a site.
	`starts` orders the candidates for the window and comes from `period_starts`;
	the whole record needs none.

	A module still waiting on a supplementary or an aegrotat counts as attempted
	and not as failed. That is what the record actually says — the sitting
	happened, the outcome is not known — and it errs in the safe direction: a
	student whose results are late is not excluded on marks that may yet be
	passes. It matters more than it sounds. Supplementary results land close to
	when the next term opens, so without this a student carrying one settled fail
	among five pending modules would read as having failed 100% of them.

	Only the rate needs that care. Counting failures is unaffected either way.
	"""
	starts = starts or {}
	period_of = _period_of(rule)

	# A sitting with no code on it says nothing, so it is neither an attempt nor
	# a failure.
	sittings = [
		(course, period_of(year, term), outcome_of(code))
		for (course, year, term), code in attempts.items()
		if outcome_of(code) != NEVER
	]

	# The latest period this student has results in, not the latest the calendar
	# knows about: a student who sat a semester out is judged on the last one they
	# were there for, rather than on an empty window.
	window = None
	periods = {period for _course, period, _outcome in sittings if period}
	if periods:
		window = max(periods, key=lambda period: (_started(starts, period), period))
		sittings = [row for row in sittings if row[1] == window]

	# Counted per module rather than per sitting, because that is what "failed
	# five of eight modules" means to the person setting the threshold, and
	# because it keeps the two halves of the rate measuring the same thing. The
	# best outcome wins, so a module failed and later passed is a pass: excluding
	# a student over a module they have since passed would be indefensible.
	best = {}
	for course, _period, outcome in sittings:
		if _RANK[outcome] > _RANK.get(best.get(course, NEVER), 0):
			best[course] = outcome

	failed = sorted(course for course, outcome in best.items() if outcome == FAILED)
	attempted = len(best)
	rate = round(100.0 * len(failed) / attempted, 1) if attempted else 0.0

	standing = {
		"window": window,
		"attempted": attempted,
		"passed": len([outcome for outcome in best.values() if outcome == PASSED]),
		"pending": len([outcome for outcome in best.values() if outcome == PENDING]),
		"failed": len(failed),
		"rate": rate,
		"failed_modules": _codes(failed),
		"excluded": False,
		"reason": None,
	}

	if not rule:
		return standing

	by_count = bool(rule.most) and len(failed) >= rule.most
	by_rate = bool(rule.rate) and attempted and rate >= rule.rate
	standing["excluded"] = bool(by_count or by_rate)
	if standing["excluded"]:
		standing["reason"] = _reason(standing)

	return standing


def _reason(standing):
	"""Why the student is being turned away, in their own terms.

	Written to the student, because they are the one who reads it and the one who
	has to do something about it. The figures are spelled out rather than left as
	a verdict: a student told only that they have failed too much cannot tell
	whether the system has counted something wrongly.
	"""
	where = (
		_("in {0}").format(standing["window"]) if standing["window"] else _("on your record")
	)
	reason = _("You have failed {0} of the {1} modules {2} — {3}%.").format(
		standing["failed"], standing["attempted"], where, standing["rate"]
	)

	if standing["failed_modules"]:
		reason += " " + _("Failed: {0}.").format(", ".join(standing["failed_modules"]))

	if standing["pending"]:
		# Named because the arithmetic looks wrong without it, and a student who
		# thinks the count is wrong should be told where the rest of it went.
		reason += " " + _(
			"{0} of them are still waiting on a result and have not been counted as failed."
		).format(standing["pending"])

	return reason + " " + _(
		"Registration is closed to you while that is the case. Speak to the academic "
		"office, who can allow it."
	)


def overrides_for(students, academic_term):
	"""student -> the override letting them register for this term, if any.

	Scoped to one term deliberately. A permission that stood for ever would be
	granted once, on one term's results, and never looked at again — which is the
	opposite of what a registrar is being asked to decide.
	"""
	if not (students and academic_term):
		return {}

	return {
		row.student: row.name
		for row in frappe.get_all(
			"Registration Override",
			filters={
				"student": ["in", list(students)],
				"academic_term": academic_term,
				"docstatus": 1,
			},
			fields=["name", "student"],
			order_by="creation asc",
		)
	}


def standing_for(students, academic_term=None):
	"""student -> how they stand, for a whole cohort in a fixed number of queries.

	Always returns an entry per student, whether or not a rule is configured, so
	a caller never has to ask separately whether the rule is on.

	`override` is only looked up where there is a rule. With none, nobody is being
	stopped and so nobody is being let through — and this runs on every load of
	the registration page, which on most sites has no rule to apply.
	"""
	students = list(dict.fromkeys(students))
	if not students:
		return {}

	configured = rule()
	attempts = attempts_for(students)
	starts = period_starts(configured.window) if configured else {}
	permitted = overrides_for(students, academic_term) if configured else {}

	standings = {}
	for student in students:
		standing = assess(attempts.get(student, {}), configured, starts)
		standing["override"] = permitted.get(student)
		# The verdict the rest of the app acts on. Kept apart from `excluded`,
		# which stays true for a student a registrar has waved through: the
		# registrar needs to see what they allowed, not a record that now reads as
		# though there had been nothing to allow.
		standing["blocked"] = bool(standing["excluded"] and not standing["override"])
		standings[student] = standing

	return standings


def standing(student, academic_term=None):
	"""How one student stands."""
	return standing_for([student], academic_term)[student]


def label(assessed):
	"""What a report calls this standing, or "" for one it has nothing to say about."""
	if not assessed["excluded"]:
		return ""
	return ALLOWED_ANYWAY if assessed["override"] else CANNOT_REGISTER


def registration_block(student, academic_term=None):
	"""What stops this student registering on academic grounds, or None."""
	assessed = standing(student, academic_term)
	return assessed if assessed["blocked"] else None


@frappe.whitelist()
def student_standing(student, academic_term=None):
	"""How a named student stands, for the desk.

	Role-checked rather than student-scoped, unlike the portal's own endpoint.
	This one names a student, so it is for the people whose job is to look at
	other people's results and nobody else.
	"""
	from education_extension.education_extension.dashboard import registrar_only

	registrar_only()
	return standing(student, academic_term)
