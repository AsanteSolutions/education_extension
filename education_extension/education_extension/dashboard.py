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

from education_extension.education_extension.desk import STAFF_ROLES
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


def registrar_only():
	frappe.only_for(tuple(sorted(STAFF_ROLES)))


def _rows():
	registrar_only()
	term = term_in_focus()
	return rows_in_focus(term) if term else []


# --- the number cards ------------------------------------------------------


@frappe.whitelist()
def students_registered(filters=None):
	return {"value": sum(1 for row in _rows() if row["status"] == REGISTERED)}


@frappe.whitelist()
def students_still_to_register(filters=None):
	"""Due to take a block this term and have not registered for it. The one
	number the window is actually run against."""
	return {"value": sum(1 for row in _rows() if row["status"] == NOT_REGISTERED)}


@frappe.whitelist()
def provisional_modules(filters=None):
	"""Taken on a prerequisite whose result had not landed. They settle
	themselves when it does, so this is a count to watch, not a queue."""
	return {"value": sum(row["provisional"] for row in _rows())}


@frappe.whitelist()
def modules_needing_review(filters=None):
	"""The cases the resolution job refused to decide — a prerequisite that
	failed after the window shut, or after work was recorded against the module.
	Unlike the rest of these, this one is a queue, and it needs a person."""
	return {"value": sum(row["needs_review"] for row in _rows())}


@frappe.whitelist()
def days_left_to_register(filters=None):
	"""What decides whether chasing anyone is still worth doing."""
	registrar_only()
	period = period_in_focus()
	if not period:
		return {"value": 0}
	return {"value": max(date_diff(period.last_date_to_register, getdate(nowdate())), 0)}


@frappe.whitelist()
def consent_forms_signed(filters=None):
	"""Should track the registered count. A gap means a registration was written
	without the consent that is supposed to accompany it."""
	registrar_only()
	term = term_in_focus()
	if not term:
		return {"value": 0}
	return {
		"value": frappe.db.count(
			"Registration Consent", {"academic_term": term, "docstatus": 1}
		)
	}


# --- the charts ------------------------------------------------------------


def empty(name):
	return {"labels": [], "datasets": [{"name": name, "values": []}]}


def progress():
	"""Registered against still to register, for the term in focus."""
	rows = _rows()
	if not rows:
		return empty(_("Students"))

	counted = Counter(row["status"] for row in rows)
	return {
		"labels": [_(status) for status in STATUSES],
		"datasets": [{"name": _("Students"), "values": [counted[status] for status in STATUSES]}],
	}


def by_programme():
	"""Where the cohort went. A programme far below the others is usually a
	prerequisite problem rather than a quiet cohort."""
	rows = _rows()
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


def per_day():
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
	period = period_in_focus()
	if not period:
		return empty(_("Registrations"))

	counted = Counter(
		getdate(row["registered_on"])
		for row in rows_in_focus(period.academic_term)
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
