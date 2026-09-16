# Copyright (c) 2026, Asante Solutions and contributors
# For license information, please see license.txt

"""The numbers behind the registration dashboard.

Every one of them is counted off `Registration Status`, the report someone opens
to act on any of it. That is the point: a dashboard that works out its own
version of "registered" will eventually disagree with the list underneath it,
and the number is the thing people repeat in meetings.

Nothing here takes a term as a filter. Dashboard filters are evaluated in the
browser, so a Python answer to "which term is this about" cannot reach one --
and it should not have to be picked every week in any case. Each of these
chooses the term itself: the period open now, the one opening next, or the last
one that ran.

They are whitelisted and they count the whole cohort, so each checks the caller
first. On a Frappe site a student holds Desk User, which makes that guard real
rather than a formality.
"""

from collections import Counter

import frappe
from frappe import _
from frappe.utils import date_diff, getdate, nowdate
from frappe.utils.caching import request_cache

from education_extension.education_extension.doctype.registration_period.registration_period import (
	next_period,
	open_period,
)
from education_extension.education_extension.report.registration_status.registration_status import (
	NOT_REGISTERED,
	NOT_THIS_TERM,
	REGISTERED,
)
from education_extension.education_extension.report.registration_status.registration_status import (
	rows as status_rows,
)

# The order they are worth reading in: who still needs chasing first.
STATUSES = (NOT_REGISTERED, REGISTERED, NOT_THIS_TERM)


def period_in_focus(on=None):
	"""The period the dashboard is about.

	The one open now, then the one opening next, then the last one that ran. A
	dashboard that empties the day registration closes is no use to the person
	whose work starts exactly there — chasing whoever did not register.
	"""
	period = open_period(on=on) or next_period(on=on)
	if period:
		return period

	previous = frappe.get_all(
		"Registration Period", order_by="last_date_to_register desc", limit=1, pluck="name"
	)
	return frappe.get_cached_doc("Registration Period", previous[0]) if previous else None


def term_in_focus(on=None):
	period = period_in_focus(on)
	return period.academic_term if period else None


@request_cache
def rows_in_focus(term):
	"""The report's own rows. Cached, because six cards and three charts each
	ask for them and the answer cannot change between two of them."""
	return status_rows(frappe._dict({"academic_term": term}))


# Who may see cohort-wide registration figures. Deliberately the Registration
# Status report's own roles, not the wider set that decides whether to show the
# app tile: these numbers are that report counted up, and reading them off a
# longer list would hand out through the dashboard exactly what the report
# refuses. Held to the report's list by a test, since the two live apart.
REGISTRAR_ROLES = ("Academics User", "Education Manager", "System Manager")


def registrar_only():
	frappe.only_for(REGISTRAR_ROLES)


def chosen_term(filters=None):
	"""The term a chart's own filter names, or the one in focus.

	The filter is there so a registrar can look back at a window that has
	already closed. Leaving it empty is the ordinary case and means "the one
	that matters now", which is why nothing here requires it.
	"""
	if isinstance(filters, str):
		filters = frappe.parse_json(filters)
	if isinstance(filters, list):
		# The chart widget sends a list when nothing has been picked.
		filters = {}
	return (filters or {}).get("academic_term") or term_in_focus()


def _rows(term=None):
	registrar_only()
	term = term or term_in_focus()
	return rows_in_focus(term) if term else []


def period_for(term):
	"""The window a term was registered in. One period per term, named for it."""
	if term and frappe.db.exists("Registration Period", term):
		return frappe.get_cached_doc("Registration Period", term)
	return period_in_focus()


# --- the number cards ------------------------------------------------------
#
# Each returns a `route` as well as a number. Without one the card is still
# clickable — the widget binds the handler regardless — and clicking does
# nothing at all, which reads as a broken card rather than as a card that does
# not drill down. Every one of these lands on the report the number came from,
# filtered to the rows it counted.


def _report_route(term, status=None):
	options = {"academic_term": term}
	if status:
		options["status"] = status
	return {"route": ["query-report", "Registration Status"], "route_options": options}


@frappe.whitelist()
def students_registered(filters=None):
	term = term_in_focus()
	return dict(
		{"value": sum(1 for row in _rows(term) if row["status"] == REGISTERED)},
		**_report_route(term, REGISTERED),
	)


@frappe.whitelist()
def students_still_to_register(filters=None):
	"""Due to take a block this term and have not registered for it. The one
	number the window is actually run against."""
	term = term_in_focus()
	return dict(
		{"value": sum(1 for row in _rows(term) if row["status"] == NOT_REGISTERED)},
		**_report_route(term, NOT_REGISTERED),
	)


@frappe.whitelist()
def provisional_modules(filters=None):
	"""Taken on a prerequisite whose result had not landed. They settle
	themselves when it does, so this is a count to watch, not a queue."""
	term = term_in_focus()
	return dict(
		{"value": sum(row["provisional"] for row in _rows(term))},
		**_report_route(term, REGISTERED),
	)


@frappe.whitelist()
def modules_needing_review(filters=None):
	"""The cases the resolution job refused to decide — a prerequisite that
	failed after the window shut, or after work was recorded against the module.
	Unlike the rest of these, this one is a queue, and it needs a person.

	It lands on the same report, which sorts the flagged rows to the top.
	"""
	term = term_in_focus()
	return dict(
		{"value": sum(row["needs_review"] for row in _rows(term))},
		**_report_route(term, REGISTERED),
	)


@frappe.whitelist()
def days_left_to_register(filters=None):
	"""What decides whether chasing anyone is still worth doing.

	Opens the period itself, since the only thing to do about this number is
	change the date or close the window early.
	"""
	registrar_only()
	period = period_in_focus()
	if not period:
		# Still somewhere to go. A card with no route is clickable and does
		# nothing, and "no window is open" is exactly when a registrar wants the
		# list of periods.
		return {"value": 0, "route": ["List", "Registration Period"]}
	return {
		"value": max(date_diff(period.last_date_to_register, getdate(nowdate())), 0),
		"route": ["Form", "Registration Period", period.name],
	}


@frappe.whitelist()
def consent_forms_signed(filters=None):
	"""Should track the registered count. A gap means a registration was written
	without the consent that is supposed to accompany it."""
	registrar_only()
	term = term_in_focus()
	if not term:
		return {"value": 0, "route": ["List", "Registration Consent"]}
	return {
		"value": frappe.db.count(
			"Registration Consent", {"academic_term": term, "docstatus": 1}
		),
		"route": ["List", "Registration Consent"],
		"route_options": {"academic_term": term, "docstatus": 1},
	}


# --- the charts ------------------------------------------------------------


def empty(name):
	return {"labels": [], "datasets": [{"name": name, "values": []}]}


def progress(filters=None):
	"""Registered against still to register, for the term in focus."""
	rows = _rows(chosen_term(filters))
	if not rows:
		return empty(_("Students"))

	counted = Counter(row["status"] for row in rows)
	return {
		"labels": [_(status) for status in STATUSES],
		"datasets": [{"name": _("Students"), "values": [counted[status] for status in STATUSES]}],
	}


def by_programme(filters=None):
	"""Where the cohort went. A programme far below the others is usually a
	prerequisite problem rather than a quiet cohort."""
	rows = _rows(chosen_term(filters))
	counted = Counter()
	for row in rows:
		for programme in filter(None, (row["programs"] or "").split(", ")):
			counted[programme] += 1

	if not counted:
		return empty(_("Students"))

	ordered = counted.most_common()
	return {
		"labels": [programme for programme, _count in ordered],
		"datasets": [{"name": _("Students"), "values": [count for _programme, count in ordered]}],
	}


def per_year(filters=None):
	"""Registration progress by year of study, first years through final years.

	The one breakdown that says where to go rather than only how far along the
	whole thing is. A cohort that is behind is behind for a reason — a
	prerequisite most of them failed, a programme whose modules are not on
	offer, a group nobody told — and it is invisible in a single total.

	Blocks come in pairs, one year to a pair: semesters 1 and 2 are the first
	years, 3 and 4 the second. Students with no block are left out rather than
	bundled into a year they are not in; there is nothing to chase there, since
	they are not due to register this term at all.
	"""
	years = {}
	for row in _rows(chosen_term(filters)):
		if row["status"] == NOT_THIS_TERM or not row.get("block"):
			continue
		bucket = years.setdefault((row["block"] + 1) // 2, {REGISTERED: 0, NOT_REGISTERED: 0})
		bucket[row["status"]] = bucket.get(row["status"], 0) + 1

	if not years:
		return empty(_("Students"))

	ordered = sorted(years)
	return {
		"labels": [_("Year {0}").format(year) for year in ordered],
		"datasets": [
			{"name": _("Registered"), "values": [years[year][REGISTERED] for year in ordered]},
			{
				"name": _("Still to register"),
				"values": [years[year][NOT_REGISTERED] for year in ordered],
			},
		],
	}


def per_day(filters=None):
	"""Registrations by the day they were made, across the whole window.

	Every day in the window is plotted, including the ones nobody registered on.
	Dropping them would compress the quiet fortnight in the middle and hide the
	shape everyone already suspects, which is that most of it happens at the end.

	Anything dated outside the window gets a bucket of its own rather than being
	left off. A cohort enrolled administratively before registration opened is
	the ordinary case at the start of a term — 69 of the 70 on this site — and a
	chart that quietly dropped them would total 1 beside a card reading 70 and
	look broken. The bucket is worth seeing in its own right: it is the
	difference between students who registered and students who were registered.
	"""
	registrar_only()
	term = chosen_term(filters)
	period = period_for(term)
	if not period:
		return empty(_("Registrations"))

	counted = Counter(
		getdate(row["registered_on"])
		for row in _rows(term or period.academic_term)
		if row["registered_on"]
	)

	opens, closes = getdate(period.opens_on), getdate(period.last_date_to_register)
	today = getdate(nowdate())
	last = min(closes, today) if today >= opens else closes

	labels, values = [], []

	before = sum(count for day, count in counted.items() if day < opens)
	if before:
		labels.append(_("Before {0}").format(frappe.utils.formatdate(opens, "d MMM")))
		values.append(before)

	if last >= opens:
		for offset in range(date_diff(last, opens) + 1):
			day = getdate(frappe.utils.add_days(opens, offset))
			labels.append(frappe.utils.formatdate(day, "d MMM"))
			values.append(counted.get(day, 0))

	after = sum(count for day, count in counted.items() if day > closes)
	if after:
		labels.append(_("After {0}").format(frappe.utils.formatdate(closes, "d MMM")))
		values.append(after)

	if not labels:
		return empty(_("Registrations"))

	return {"labels": labels, "datasets": [{"name": _("Registrations"), "values": values}]}
