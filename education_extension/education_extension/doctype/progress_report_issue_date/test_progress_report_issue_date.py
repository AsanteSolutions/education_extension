# Copyright (c) 2026, Asante Solutions and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

from education_extension.education_extension.doctype.progress_report_issue_date.progress_report_issue_date import (
	is_released,
	release_moment,
)

UNKNOWN_TERM = "no-such-term-for-tests"
UNKNOWN_YEAR = "no-such-year-for-tests"


class TestProgressReportIssueDate(FrappeTestCase):
	def test_nothing_on_file_is_not_released(self):
		"""Marks reach students because someone said so, not because nobody said
		otherwise."""
		self.assertIsNone(release_moment(UNKNOWN_YEAR, UNKNOWN_TERM, "Standard"))
		self.assertFalse(is_released(UNKNOWN_YEAR, UNKNOWN_TERM, "Standard"))

	def test_a_record_without_a_release_time_falls_back_to_its_issue_date(self):
		record = self._record(issue_date="2026-01-15", released_to_students_at=None)
		moment = release_moment(record.academic_year, record.academic_term, record.issue_date_for)
		self.assertIsNotNone(moment)
		self.assertEqual(moment.date(), frappe.utils.getdate("2026-01-15"))

	def test_a_release_time_in_the_future_holds_the_marks_back(self):
		record = self._record(
			issue_date=frappe.utils.today(),
			released_to_students_at=add_to_date(now_datetime(), days=1),
		)
		self.assertFalse(
			is_released(record.academic_year, record.academic_term, record.issue_date_for)
		)

	def test_a_release_time_in_the_past_lets_them_through(self):
		record = self._record(
			issue_date=frappe.utils.today(),
			released_to_students_at=add_to_date(now_datetime(), hours=-1),
		)
		self.assertTrue(
			is_released(record.academic_year, record.academic_term, record.issue_date_for)
		)

	def test_each_kind_of_run_is_released_on_its_own(self):
		"""A student can be reading their main marks while the supplementary ones
		are still held."""
		record = self._record(
			issue_date=frappe.utils.today(),
			released_to_students_at=add_to_date(now_datetime(), hours=-1),
		)
		self.assertTrue(is_released(record.academic_year, record.academic_term, "Standard"))
		self.assertFalse(is_released(record.academic_year, record.academic_term, "Supplementary"))

	def test_results_cannot_reach_students_before_they_were_issued(self):
		with self.assertRaises(frappe.ValidationError):
			self._record(
				issue_date="2026-06-30",
				released_to_students_at="2026-06-01 09:00:00",
			)

	def _record(self, issue_date, released_to_students_at):
		"""A submitted record against a year and term the site does not use, so
		nothing real is affected."""
		year = frappe.get_all("Academic Year", pluck="name", limit=1)
		term = frappe.get_all("Academic Term", pluck="name", limit=1)
		if not year or not term:
			self.skipTest("site has no Academic Year or Term to file a release against")

		# Cleared first so a rerun does not trip the one-per-term rule.
		for existing in frappe.get_all(
			"Progress Report Issue Date",
			filters={"academic_year": year[0], "academic_term": term[0], "issue_date_for": "Standard"},
			pluck="name",
		):
			doc = frappe.get_doc("Progress Report Issue Date", existing)
			if doc.docstatus == 1:
				doc.cancel()
			frappe.delete_doc("Progress Report Issue Date", existing, force=True)

		record = frappe.get_doc(
			{
				"doctype": "Progress Report Issue Date",
				"academic_year": year[0],
				"academic_term": term[0],
				"issue_date_for": "Standard",
				"issue_date": issue_date,
				"released_to_students_at": released_to_students_at,
			}
		)
		record.insert()
		record.submit()
		return record
