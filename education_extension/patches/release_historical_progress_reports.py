# Copyright (c) 2026, Asante Solutions and contributors
# For license information, please see license.txt

"""Grandfather the terms whose results were already out.

Publication became a decision someone makes: `is_released` answers no unless a
Progress Report Issue Date says otherwise, which is right for every term from
here on. It is retroactive, though, and there was nothing to be retroactive
about -- before this, a mark was visible to the student the moment it was
submitted. Without a backfill the first migrate takes every historical term off
the Grades page at once, and each one has to be re-published by hand before
marks that have been visible for years come back.

So: a record per year, term and sitting that already has results, released at
the moment the last of those results was submitted. That is as close to the
truth as the data gets -- they were visible from about then -- and it is a date
someone can audit rather than the date of the migration.

Only terms that have already ended are touched. A term still running is a live
decision about whether its marks are ready, and this patch has no business
making it.
"""

import frappe

from education_extension.education_extension.doctype.student_progress_report.student_progress_report import (
	ISSUE_DATE_AEGROTAT,
	ISSUE_DATE_STANDARD,
	ISSUE_DATE_SUPPLEMENTARY,
)

# The sitting a result was recorded under, and the kind of issue date that
# governs it. A result with no sitting is from before the field existed and is
# a main-sitting mark.
KIND_FOR_SITTING = {
	"Main": ISSUE_DATE_STANDARD,
	"": ISSUE_DATE_STANDARD,
	None: ISSUE_DATE_STANDARD,
	"Supplementary": ISSUE_DATE_SUPPLEMENTARY,
	"Aegrotat": ISSUE_DATE_AEGROTAT,
}


def execute():
	finished = terms_that_have_ended()
	if not finished:
		print("No finished academic terms, so there is nothing to grandfather.")
		return

	created, already = 0, 0

	for row in results_awaiting_release():
		if row.academic_term not in finished:
			continue

		kind = KIND_FOR_SITTING.get(row.sitting)
		if not kind:
			print("  {0} / {1}: unknown sitting {2!r}, left alone".format(
				row.academic_year, row.academic_term, row.sitting
			))
			continue

		if already_published(row.academic_year, row.academic_term, kind):
			already += 1
			continue

		publish(row.academic_year, row.academic_term, kind, row.last_submitted)
		created += 1
		print("  {0} / {1} / {2}: released as of {3}".format(
			row.academic_year, row.academic_term, kind, row.last_submitted
		))

	print(
		"Grandfathered {0} run(s) of marks; {1} already had a release date.".format(created, already)
	)
	if created:
		print(
			"These are the terms that were already visible to students. Cancel any that should not be."
		)


def terms_that_have_ended():
	"""Terms whose end date has passed. A term with no end date is not assumed
	to be over, because the whole point of the guard is to leave live decisions
	alone."""
	return set(
		frappe.get_all(
			"Academic Term",
			filters={"term_end_date": ["<", frappe.utils.nowdate()]},
			pluck="name",
			limit_page_length=0,
		)
	)


def results_awaiting_release():
	"""One row per year, term and sitting that has submitted results, carrying
	the moment the last of them was submitted."""
	return frappe.db.sql(
		"""
		select academic_year, academic_term,
		       coalesce(custom_sitting, 'Main') as sitting,
		       max(modified) as last_submitted
		from `tabAssessment Result`
		where docstatus = 1
		  and academic_year is not null
		  and academic_term is not null
		group by academic_year, academic_term, coalesce(custom_sitting, 'Main')
		""",
		as_dict=True,
	)


def already_published(academic_year, academic_term, kind):
	"""Any record at all, submitted or not -- a draft is somebody part-way
	through the decision, and writing a second one would tread on it."""
	return bool(
		frappe.db.exists(
			"Progress Report Issue Date",
			{
				"academic_year": academic_year,
				"academic_term": academic_term,
				"issue_date_for": kind,
				"docstatus": ["<", 2],
			},
		)
	)


def publish(academic_year, academic_term, kind, released_at):
	record = frappe.get_doc(
		{
			"doctype": "Progress Report Issue Date",
			"academic_year": academic_year,
			"academic_term": academic_term,
			"issue_date_for": kind,
			"issue_date": frappe.utils.getdate(released_at),
			"released_to_students_at": released_at,
		}
	)
	record.insert(ignore_permissions=True)
	record.submit()
