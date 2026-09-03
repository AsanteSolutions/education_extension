# Copyright (c) 2026, Asante Solutions and contributors
# For license information, please see license.txt

"""The window in which students may register themselves for a term.

One period per term -- the docname is the term, so a second one cannot be
created by accident. A period governs every programme unless it names some,
which lets one cohort be opened ahead of another without inventing a second
window for the same term.

`last_date_to_register` is the boundary for the whole registration, not only for
starting one: after it nothing about a registration changes by itself, which is
what stops a supplementary result landing mid-term from quietly removing a
module the student has been attending.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import formatdate, getdate, nowdate


class RegistrationPeriod(Document):
	def validate(self):
		self.validate_dates()
		self.validate_term_matches_year()
		self.validate_programmes_are_distinct()

	def validate_dates(self):
		if getdate(self.last_date_to_register) < getdate(self.opens_on):
			frappe.throw(
				_("Registration cannot close on {0}, before it opens on {1}.").format(
					formatdate(self.last_date_to_register), formatdate(self.opens_on)
				)
			)

	def validate_term_matches_year(self):
		year = frappe.db.get_value("Academic Term", self.academic_term, "academic_year")
		if year and year != self.academic_year:
			frappe.throw(
				_("{0} belongs to {1}, not to {2}.").format(
					frappe.bold(self.academic_term), frappe.bold(year), frappe.bold(self.academic_year)
				)
			)

	def validate_programmes_are_distinct(self):
		seen = set()
		for row in self.programs:
			if row.program in seen:
				frappe.throw(_("{0} is listed twice.").format(frappe.bold(row.program)))
			seen.add(row.program)

	def covers(self, program):
		"""Whether this period governs `program`. Naming none covers them all."""
		chosen = [row.program for row in self.programs]
		return not chosen or program in chosen

	def accepting_registrations(self, on=None):
		"""Whether a student may register, or change a registration, on `on`."""
		if not self.is_open:
			return False
		on = getdate(on or nowdate())
		return getdate(self.opens_on) <= on <= getdate(self.last_date_to_register)


def open_period(program=None, on=None):
	"""The period accepting registrations on `on`, for `program` if given.

	None when registration is shut, which the portal renders as its closed state
	rather than as an error.
	"""
	on = getdate(on or nowdate())
	candidates = frappe.get_all(
		"Registration Period",
		filters={
			"is_open": 1,
			"opens_on": ["<=", on],
			"last_date_to_register": [">=", on],
		},
		order_by="opens_on desc",
		pluck="name",
	)
	for name in candidates:
		period = frappe.get_cached_doc("Registration Period", name)
		if program is None or period.covers(program):
			return period
	return None


def next_period(program=None, on=None):
	"""The period that opens next, so a closed portal can say when to come back."""
	on = getdate(on or nowdate())
	upcoming = frappe.get_all(
		"Registration Period",
		filters={"is_open": 1, "opens_on": [">", on]},
		order_by="opens_on asc",
		pluck="name",
	)
	for name in upcoming:
		period = frappe.get_cached_doc("Registration Period", name)
		if program is None or period.covers(program):
			return period
	return None
