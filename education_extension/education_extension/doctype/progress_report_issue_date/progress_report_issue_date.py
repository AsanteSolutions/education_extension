# Copyright (c) 2026, Asante Solutions and contributors
# For license information, please see license.txt

"""When a term's marks were issued, and when students may see them.

One record per academic year, term and kind of run, carrying both dates: the
issue date printed on the progress report, and the moment the marks appear on
the portal. They are the same decision made twice if kept apart, which is why
they live on one document.
"""

import frappe
from frappe.model.document import Document
from frappe.utils import get_datetime, now_datetime


class ProgressReportIssueDate(Document):
	def validate(self):
		self.validate_release_is_not_before_issue()

	def validate_release_is_not_before_issue(self):
		"""Publishing to students before the marks were issued would mean the
		report and the portal disagree about when results existed."""
		if not self.released_to_students_at or not self.issue_date:
			return

		if get_datetime(self.released_to_students_at).date() < frappe.utils.getdate(self.issue_date):
			frappe.throw(
				frappe._("Results cannot reach students on {0}, before they were issued on {1}.").format(
					frappe.bold(frappe.utils.format_datetime(self.released_to_students_at)),
					frappe.bold(frappe.utils.format_date(self.issue_date)),
				)
			)


def release_moment(academic_year, academic_term, issue_date_for):
	"""When this run of marks reaches students, or None if it never has been.

	A record with no release time falls back to its issue date, from the start of
	that day — that date is what the institution has been treating as the marks
	being out, so a record written before there was a release time still means
	what it meant.
	"""
	record = frappe.get_all(
		"Progress Report Issue Date",
		fields=["released_to_students_at", "issue_date"],
		filters={
			"academic_year": academic_year,
			"academic_term": academic_term,
			"issue_date_for": issue_date_for,
			"docstatus": 1,
		},
		order_by="issue_date desc",
		limit=1,
	)
	if not record:
		return None

	released_at = record[0].released_to_students_at
	if released_at:
		return get_datetime(released_at)

	return get_datetime(record[0].issue_date) if record[0].issue_date else None


def is_released(academic_year, academic_term, issue_date_for):
	"""Whether students may see this run of marks yet.

	No record means not released. Marks become visible because someone decided
	they should, not because nobody has said otherwise — which is the whole point
	of having a release date.
	"""
	moment = release_moment(academic_year, academic_term, issue_date_for)
	return bool(moment and moment <= now_datetime())
