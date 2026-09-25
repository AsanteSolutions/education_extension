# Copyright (c) 2026, Asante Solutions and Contributors
# See license.txt

"""Tests for the academic standing rule and the registrar's way round it.

Split the same way the registration tests are. `TestTheRule` touches no database
— `assess` is pure, and the decisions worth pinning are all in there. The rest
needs records and skips itself where the education app is absent.

`bench run-tests` cannot bootstrap this site, so these also run from a console:

    from education_extension.education_extension.test_academic_standing import run_tests
    run_tests()
"""

import unittest

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase

from education_extension.education_extension import academic_standing as standing
from education_extension.education_extension.registration import (
	PASS_CODES,
	PENDING_CODES,
	attempts_for,
)

# No IGNORE_TEST_RECORD_DEPENDENCIES here: Frappe only honours it on a test
# module sitting inside a doctype folder, and raises on one that is not.
from education_extension.education_extension.testing import (
	needs_doctype,
	needs_education_app,
)

YEAR = "2025-2026"
EARLIER = "2024-2025"
TERM = "Semester 1 2025-2026"


def rule(most=0, rate=0, window=standing.LATEST_YEAR):
	return frappe._dict({"most": most, "rate": rate, "window": window})


def attempts(*sittings):
	"""{(course, year, term): code} from (code, module number, year) triples.

	Courses are named the way the curriculum names them, because `failed_modules`
	shortens them to their codes and that is worth exercising.
	"""
	return {
		("ANH{0} - Module {0}".format(course), year, TERM): code
		for code, course, year in sittings
	}


class TestTheRule(UnitTestCase):
	"""What the thresholds mean, with hand-built records and no site."""

	def test_nobody_is_excluded_without_a_rule(self):
		assessed = standing.assess(
			attempts(("F", 1, YEAR), ("F", 2, YEAR), ("F", 3, YEAR)), None
		)
		self.assertFalse(assessed["excluded"])
		self.assertIsNone(assessed["reason"])
		# The figures are still counted, because a registrar granting a permission
		# wants them on the record whether or not the rule is switched on.
		self.assertEqual((assessed["failed"], assessed["attempted"]), (3, 3))

	def test_the_count_threshold_trips_on_reaching_it(self):
		taken = attempts(("F", 1, YEAR), ("F", 2, YEAR), ("P", 3, YEAR))

		self.assertFalse(standing.assess(taken, rule(most=3))["excluded"])
		self.assertTrue(standing.assess(taken, rule(most=2))["excluded"])

	def test_the_rate_threshold_trips_on_reaching_it(self):
		taken = attempts(("F", 1, YEAR), ("F", 2, YEAR), ("P", 3, YEAR), ("P", 4, YEAR))
		assessed = standing.assess(taken, rule(rate=50))

		self.assertEqual(assessed["rate"], 50.0)
		self.assertTrue(assessed["excluded"])
		self.assertFalse(standing.assess(taken, rule(rate=50.1))["excluded"])

	def test_either_threshold_is_enough_on_its_own(self):
		taken = attempts(("F", 1, YEAR), ("P", 2, YEAR), ("P", 3, YEAR), ("P", 4, YEAR))

		# One of four is 25%: under a 50% rate, and over a one-module count.
		self.assertTrue(standing.assess(taken, rule(most=1, rate=50))["excluded"])
		self.assertFalse(standing.assess(taken, rule(most=2, rate=50))["excluded"])

	def test_a_result_that_has_not_landed_is_not_a_failure(self):
		"""The one that matters most.

		Supplementary results come in around the time the next term opens, so a
		student part-way through a supplementary season is the ordinary case and
		not an edge. Counting those as failures would read one settled fail among
		four pending modules as a 100% failure rate and exclude nearly everybody.
		"""
		taken = attempts(
			("F", 1, YEAR),
			("SUPP", 2, YEAR),
			("SUPP", 3, YEAR),
			("SUPP", 4, YEAR),
			("AEGRO", 5, YEAR),
		)
		assessed = standing.assess(taken, rule(rate=50))

		self.assertEqual((assessed["failed"], assessed["pending"]), (1, 4))
		self.assertEqual(assessed["attempted"], 5, "a pending module was still taken")
		self.assertEqual(assessed["rate"], 20.0)
		self.assertFalse(assessed["excluded"])

	def test_a_module_failed_and_later_passed_is_a_pass(self):
		taken = attempts(("F", 1, EARLIER), ("P", 1, YEAR), ("P", 2, YEAR))
		assessed = standing.assess(taken, rule(most=1, window=standing.WHOLE_RECORD))

		self.assertEqual(assessed["failed"], 0)
		self.assertEqual(assessed["attempted"], 2, "two modules, not three sittings")
		self.assertFalse(assessed["excluded"])

	def test_the_window_holds_a_bad_year_against_the_year_it_was_in(self):
		taken = attempts(
			("F", 1, EARLIER), ("F", 2, EARLIER), ("F", 3, EARLIER), ("P", 4, YEAR)
		)
		starts = {EARLIER: "2024-01-01", YEAR: "2025-01-01"}

		latest = standing.assess(taken, rule(most=3), starts)
		self.assertFalse(latest["excluded"], "last year's failures are behind them")
		self.assertEqual(latest["window"], YEAR)
		self.assertEqual(latest["attempted"], 1)

		whole = standing.assess(taken, rule(most=3, window=standing.WHOLE_RECORD), starts)
		self.assertTrue(whole["excluded"])
		self.assertIsNone(whole["window"], "the whole record is not a window")
		self.assertEqual(whole["attempted"], 4)

	def test_the_latest_year_is_the_one_that_starts_last(self):
		"""Not the one whose name sorts last.

		Academic years are named freely. "2025-2026" happens to sort correctly and
		nothing guarantees the next name will.
		"""
		taken = attempts(("F", 1, "Year A"), ("P", 2, "Year B"))
		starts = {"Year A": "2026-01-01", "Year B": "2024-01-01"}

		assessed = standing.assess(taken, rule(most=1), starts)
		self.assertEqual(assessed["window"], "Year A")
		self.assertTrue(assessed["excluded"])

	def test_a_year_with_no_start_date_does_not_raise(self):
		taken = attempts(("F", 1, "Undated"), ("P", 2, YEAR))
		assessed = standing.assess(taken, rule(most=1), {YEAR: "2025-01-01"})

		self.assertEqual(assessed["window"], YEAR, "a dated year beats an undated one")

	def test_an_empty_record_excludes_nobody(self):
		assessed = standing.assess({}, rule(most=1, rate=1))

		self.assertEqual((assessed["attempted"], assessed["failed"]), (0, 0))
		self.assertEqual(assessed["rate"], 0.0, "no attempts is not a 100% failure rate")
		self.assertFalse(assessed["excluded"])

	def test_a_sitting_with_no_code_on_it_is_not_an_attempt(self):
		taken = attempts(("F", 1, YEAR), ("", 2, YEAR), ("", 3, YEAR))
		assessed = standing.assess(taken, rule(rate=50))

		self.assertEqual(assessed["attempted"], 1, "an empty remark says nothing")
		self.assertTrue(assessed["excluded"])

	def test_the_reason_names_the_figures_and_the_modules(self):
		taken = attempts(("F", 1, YEAR), ("F", 2, YEAR), ("SUPP", 3, YEAR), ("P", 4, YEAR))
		reason = standing.assess(taken, rule(most=2))["reason"]

		self.assertIn("2 of the 4", reason)
		self.assertIn("50.0%", reason)
		# Shortened to codes, and every failed one named: a student told only that
		# they have failed too much cannot tell whether something was miscounted.
		self.assertIn("ANH1", reason)
		self.assertIn("ANH2", reason)
		self.assertIn(YEAR, reason)
		self.assertIn("1 of them are still waiting", reason)

	def test_a_rule_with_no_threshold_on_it_is_not_a_rule(self):
		"""Nought failures allowed is not what an empty field means.

		Read the other way round, turning the rule on and setting nothing would
		exclude every student who has ever failed anything.
		"""
		self.assertFalse(standing.assess(attempts(("F", 1, YEAR)), rule())["excluded"])


class TestTheOverride(IntegrationTestCase):
	"""The registrar's way round the rule, against real records."""

	def setUp(self):
		needs_education_app(self)
		needs_doctype(self, "Registration Override", "Academic Term", "Academic Remark")

		terms = frappe.get_all("Academic Term", limit=1, pluck="name")
		if not terms:
			self.skipTest("this site has no academic terms")
		self.term = terms[0]

		self.student = a_student_who_has_failed()
		if not self.student:
			self.skipTest("no student on this site has a failure on record")

	def tearDown(self):
		# Explicitly, not at class teardown. Frappe rolls back once the whole class
		# is done, so without this the records and the settings changed here outlive
		# the test that made them, and the next one starts on a site it did not
		# expect.
		frappe.db.rollback()
		frappe.clear_cache(doctype="Registration Settings")

	def turn_the_rule_on(self, most=1, window=standing.WHOLE_RECORD):
		settings = frappe.get_doc("Registration Settings")
		settings.block_on_failed_modules = 1
		settings.maximum_failed_modules = most
		settings.maximum_failure_rate = 0
		settings.failure_window = window
		settings.save()
		frappe.clear_cache(doctype="Registration Settings")

	def grant(self, **values):
		override = frappe.get_doc(
			dict(
				{
					"doctype": "Registration Override",
					"student": self.student,
					"academic_term": self.term,
					"reason": "Hospitalised for most of the second semester.",
				},
				**values,
			)
		)
		override.insert()
		return override

	def test_granting_records_who_allowed_it_and_when(self):
		override = self.grant()
		self.assertFalse(override.granted_by, "a draft has allowed nothing")

		override.submit()
		self.assertEqual(override.granted_by, frappe.session.user)
		self.assertTrue(override.granted_on)

	def test_it_snapshots_the_standing_it_was_granted_over(self):
		self.turn_the_rule_on()
		override = self.grant()
		assessed = standing.standing(self.student, self.term)

		self.assertEqual(override.modules_failed, assessed["failed"])
		self.assertEqual(override.modules_attempted, assessed["attempted"])
		self.assertEqual(override.failure_rate, assessed["rate"])
		self.assertTrue(override.modules_failed, "the student under test has failed something")

	def test_only_one_permission_stands_per_student_and_term(self):
		self.grant().submit()

		with self.assertRaises(frappe.ValidationError):
			self.grant(reason="Asked again.")

	def test_a_draft_permits_nothing(self):
		self.grant()
		self.assertEqual(standing.overrides_for([self.student], self.term), {})

	def test_a_permission_does_not_carry_into_another_term(self):
		other = [
			term
			for term in frappe.get_all("Academic Term", limit=2, pluck="name")
			if term != self.term
		]
		if not other:
			self.skipTest("this site has only one academic term")

		self.grant().submit()
		self.assertEqual(standing.overrides_for([self.student], other[0]), {})

	def test_it_lets_a_blocked_student_register_and_says_so_afterwards(self):
		"""The whole point, end to end.

		Both halves of the aftermath matter. `blocked` has to go false or the
		student still cannot register, and `excluded` has to stay true or the
		Registration Status report stops showing the registrar what they allowed.
		"""
		self.turn_the_rule_on()
		self.assertIsNotNone(
			standing.registration_block(self.student, self.term),
			"the rule should be stopping this student",
		)

		override = self.grant()
		override.submit()

		self.assertIsNone(standing.registration_block(self.student, self.term))
		assessed = standing.standing(self.student, self.term)
		self.assertEqual(assessed["override"], override.name)
		self.assertFalse(assessed["blocked"])
		self.assertTrue(assessed["excluded"], "the reason it was needed has gone missing")

	def test_cancelling_takes_the_permission_back(self):
		self.turn_the_rule_on()
		override = self.grant()
		override.submit()
		self.assertIsNone(standing.registration_block(self.student, self.term))

		override.cancel()
		self.assertIsNotNone(
			standing.registration_block(self.student, self.term),
			"a cancelled permission still permitted",
		)

	def test_the_report_names_both_states(self):
		from education_extension.education_extension.report.registration_status import (
			registration_status as report,
		)

		self.turn_the_rule_on()
		self.assertEqual(
			report.standing_labels([self.student], self.term),
			{self.student: report.CANNOT_REGISTER},
		)

		self.grant().submit()
		self.assertEqual(
			report.standing_labels([self.student], self.term),
			{self.student: report.ALLOWED_ANYWAY},
		)


class TestTheRuleIsOffUntilSomebodyTurnsItOn(IntegrationTestCase):
	"""The shipped default, which is what a site runs on until someone changes it."""

	def tearDown(self):
		frappe.db.rollback()
		frappe.clear_cache(doctype="Registration Settings")

	def test_no_rule_is_configured_out_of_the_box(self):
		needs_doctype(self, "Registration Settings")
		if frappe.db.get_single_value("Registration Settings", "block_on_failed_modules"):
			self.skipTest("this site has turned the rule on")

		self.assertIsNone(standing.rule())

	def test_turning_it_on_without_a_threshold_still_blocks_nobody(self):
		needs_doctype(self, "Registration Settings")
		settings = frappe.get_doc("Registration Settings")
		settings.block_on_failed_modules = 1
		settings.maximum_failed_modules = 0
		settings.maximum_failure_rate = 0
		settings.save()
		frappe.clear_cache(doctype="Registration Settings")

		self.assertIsNone(standing.rule())

	def test_the_report_column_stays_empty_while_the_rule_is_off(self):
		"""And costs nothing to leave empty.

		It runs over the whole cohort on a report staff keep open, so it is skipped
		outright rather than computed and thrown away.
		"""
		from education_extension.education_extension.report.registration_status import (
			registration_status as report,
		)

		needs_education_app(self)
		if frappe.db.get_single_value("Registration Settings", "block_on_failed_modules"):
			self.skipTest("this site has turned the rule on")

		students = frappe.get_all("Student", limit=5, pluck="name")
		self.assertEqual(report.standing_labels(students, None), {})


def a_student_who_has_failed():
	"""A student whose record actually trips the rule, or None.

	Found rather than made. Building one would mean submitting an Academic Remark
	against a real Course and Academic Term, and on a site that has neither, the
	test would be constructing the very records it is meant to be reading.

	Checked through `assess` rather than off the remark code, because a module
	failed and later passed is not a failure — that student would give these tests
	someone the rule has nothing to say about.
	"""
	candidates = frappe.get_all(
		"Academic Remark",
		filters={"docstatus": 1, "remark": ["not in", sorted(PASS_CODES | PENDING_CODES)]},
		pluck="student",
		limit=50,
	)
	for student in dict.fromkeys(candidates):
		if standing.assess(attempts_for([student])[student], None)["failed"]:
			return student
	return None


def run_tests(verbosity=2):
	"""Run these from a console, since bench run-tests cannot bootstrap this site."""
	suite = unittest.TestSuite()
	loader = unittest.TestLoader()
	for case in (TestTheRule, TestTheOverride, TestTheRuleIsOffUntilSomebodyTurnsItOn):
		suite.addTests(loader.loadTestsFromTestCase(case))
	return unittest.TextTestRunner(verbosity=verbosity).run(suite)
