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
LATER_TERM = "Semester 2 2025-2026"

# Two semesters inside one academic year, which is what separates the two
# narrow windows from each other.
TERM_STARTS = {TERM: "2025-01-15", LATER_TERM: "2025-07-15"}
YEAR_STARTS = {EARLIER: "2024-01-15", YEAR: "2025-01-15"}


def rule(most=0, rate=0, window=standing.LATEST_YEAR):
	return frappe._dict({"most": most, "rate": rate, "window": window})


def attempts(*sittings):
	"""{(course, year, term): code} from (code, module number, year[, term]) rows.

	The term defaults, because most of these tests are about the thresholds and
	only the window ones care which semester a sitting fell in.

	Courses are named the way the curriculum names them, because `failed_modules`
	shortens them to their codes and that is worth exercising.
	"""
	return {
		("ANH{0} - Module {0}".format(row[1]), row[2], row[3] if len(row) > 3 else TERM): row[0]
		for row in sittings
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

		latest = standing.assess(taken, rule(most=3), YEAR_STARTS)
		self.assertFalse(latest["excluded"], "last year's failures are behind them")
		self.assertEqual(latest["window"], YEAR)
		self.assertEqual(latest["attempted"], 1)

		whole = standing.assess(taken, rule(most=3, window=standing.WHOLE_RECORD), YEAR_STARTS)
		self.assertTrue(whole["excluded"])
		self.assertIsNone(whole["window"], "the whole record is not a window")
		self.assertEqual(whole["attempted"], 4)

	def test_the_semester_window_sees_one_semester_and_not_the_year_round_it(self):
		"""The three windows differ on the same record, which is the point of
		offering all three."""
		taken = attempts(
			("F", 1, YEAR, TERM),
			("F", 2, YEAR, TERM),
			("F", 3, YEAR, LATER_TERM),
			("P", 4, YEAR, LATER_TERM),
			("P", 5, YEAR, LATER_TERM),
		)

		semester = standing.assess(taken, rule(most=3, window=standing.LATEST_TERM), TERM_STARTS)
		self.assertEqual(semester["window"], LATER_TERM)
		self.assertEqual((semester["failed"], semester["attempted"]), (1, 3))
		self.assertFalse(semester["excluded"])

		year = standing.assess(taken, rule(most=3), YEAR_STARTS)
		self.assertEqual(year["window"], YEAR)
		self.assertEqual((year["failed"], year["attempted"]), (3, 5))
		self.assertTrue(year["excluded"], "the first semester's failures count for the year")

	def test_the_semester_window_is_the_last_one_with_results_in_it(self):
		"""Not the last one on the calendar.

		A student who sat a semester out has nothing in it, and judging them on an
		empty window would mean nought of nought — which is not a failure rate, and
		would quietly excuse the semester they did fail.
		"""
		taken = attempts(("F", 1, YEAR, TERM), ("F", 2, YEAR, TERM))

		assessed = standing.assess(taken, rule(most=2, window=standing.LATEST_TERM), TERM_STARTS)
		self.assertEqual(assessed["window"], TERM)
		self.assertTrue(assessed["excluded"])

	def test_the_latest_semester_is_the_one_that_starts_last(self):
		# Same trap as the year window: these names sort the wrong way round.
		taken = attempts(("F", 1, YEAR, "Autumn"), ("P", 2, YEAR, "Spring"))
		starts = {"Autumn": "2025-07-15", "Spring": "2025-01-15"}

		assessed = standing.assess(taken, rule(most=1, window=standing.LATEST_TERM), starts)
		self.assertEqual(assessed["window"], "Autumn")
		self.assertTrue(assessed["excluded"])

	def test_every_window_the_setting_offers_is_one_the_rule_knows(self):
		"""Or a window could be chosen that silently measures something else.

		An unknown value falls through to the academic year, which is a reasonable
		default and a terrible thing to do quietly.
		"""
		offered = frappe.get_meta("Registration Settings").get_field("failure_window")
		self.assertEqual(
			[option for option in offered.options.split("\n") if option],
			[standing.LATEST_TERM, standing.LATEST_YEAR, standing.WHOLE_RECORD],
		)
		# Every window that narrows the record needs somewhere to read its dates
		# from; the whole record is the one that does not.
		self.assertEqual(
			set(standing.WINDOW_SOURCES), {standing.LATEST_TERM, standing.LATEST_YEAR}
		)

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
			{self.student: standing.CANNOT_REGISTER},
		)

		self.grant().submit()
		self.assertEqual(
			report.standing_labels([self.student], self.term),
			{self.student: standing.ALLOWED_ANYWAY},
		)


class TestTheExclusionsReport(IntegrationTestCase):
	"""The queue of students the rule has stopped."""

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

		from education_extension.education_extension.report.academic_exclusions import (
			academic_exclusions as report,
		)

		self.report = report

	def tearDown(self):
		frappe.db.rollback()
		frappe.clear_cache(doctype="Registration Settings")

	def turn_the_rule_on(self, most=1):
		settings = frappe.get_doc("Registration Settings")
		settings.block_on_failed_modules = 1
		settings.maximum_failed_modules = most
		settings.maximum_failure_rate = 0
		settings.failure_window = standing.WHOLE_RECORD
		settings.save()
		frappe.clear_cache(doctype="Registration Settings")

	def run_report(self, **filters):
		result = self.report.execute(dict({"academic_term": self.term}, **filters))
		return result[1], (result[2] if len(result) > 2 else None)

	def find(self, rows, student):
		return next((row for row in rows if row["student"] == student), None)

	def test_it_says_so_rather_than_showing_an_empty_table_when_no_rule_is_set(self):
		"""Nobody excluded and no rule to exclude anybody look identical otherwise,
		and they are very different things to tell a registrar."""
		if frappe.db.get_single_value("Registration Settings", "block_on_failed_modules"):
			self.skipTest("this site has turned the rule on")

		rows, message = self.run_report()
		self.assertEqual(rows, [])
		self.assertTrue(message)
		self.assertIn("Registration Settings", message)

	def test_it_needs_a_term(self):
		with self.assertRaises(frappe.ValidationError):
			self.report.execute({})

	def test_an_excluded_student_appears_with_the_figures_behind_it(self):
		self.turn_the_rule_on()
		rows, _message = self.run_report()

		row = self.find(rows, self.student)
		self.assertIsNotNone(row, "the student the rule is stopping is not on the list")
		self.assertEqual(row["standing"], standing.CANNOT_REGISTER)

		assessed = standing.standing(self.student, self.term)
		self.assertEqual(row["failed"], assessed["failed"])
		self.assertEqual(row["attempted"], assessed["attempted"])
		self.assertEqual(row["rate"], assessed["rate"])
		self.assertEqual(row["failed_modules"], ", ".join(assessed["failed_modules"]))
		self.assertFalse(row["override"], "nobody has permitted this student")

	def test_a_permitted_student_stays_on_the_list_with_the_permission_beside_them(self):
		"""Dropping them would answer "who is excluded" and lose "who was let
		through, by whom, and why" — which is the half an auditor asks about."""
		self.turn_the_rule_on()
		override = frappe.get_doc(
			{
				"doctype": "Registration Override",
				"student": self.student,
				"academic_term": self.term,
				"reason": "Hospitalised for most of the second semester.",
			}
		)
		override.insert()
		override.submit()

		row = self.find(self.run_report()[0], self.student)
		self.assertEqual(row["standing"], standing.ALLOWED_ANYWAY)
		self.assertEqual(row["override"], override.name)
		self.assertEqual(row["granted_by"], frappe.session.user)
		self.assertIn("Hospitalised", row["reason"])

	def test_the_standing_filter_narrows_to_one_state(self):
		self.turn_the_rule_on()

		barred = self.run_report(standing=standing.CANNOT_REGISTER)[0]
		self.assertTrue(self.find(barred, self.student))
		self.assertTrue(all(row["standing"] == standing.CANNOT_REGISTER for row in barred))

		permitted = self.run_report(standing=standing.ALLOWED_ANYWAY)[0]
		self.assertIsNone(self.find(permitted, self.student))

	def test_nobody_the_rule_is_content_with_is_listed(self):
		"""It is a queue, not a roll. Everybody else is on Registration Status."""
		self.turn_the_rule_on()
		rows, _message = self.run_report()

		self.assertTrue(rows, "nothing to check")
		self.assertTrue(all(row["standing"] for row in rows))
		for row in rows:
			self.assertTrue(
				standing.standing(row["student"], self.term)["excluded"], row["student"]
			)

	def test_the_students_still_barred_come_first(self):
		"""The ones needing a decision, ahead of the ones already decided."""
		self.turn_the_rule_on()
		rows = self.run_report()[0]
		if len(rows) < 2:
			self.skipTest("too few excluded students to order")

		# Permit the one the sort has put first, so the two states exist and the
		# permitted one has to move.
		frappe.get_doc(
			{
				"doctype": "Registration Override",
				"student": rows[0]["student"],
				"academic_term": self.term,
				"reason": "Letting this one through.",
			}
		).insert().submit()

		rows = self.run_report()[0]
		barred = [i for i, row in enumerate(rows) if row["standing"] == standing.CANNOT_REGISTER]
		permitted = [i for i, row in enumerate(rows) if row["standing"] == standing.ALLOWED_ANYWAY]

		self.assertTrue(barred and permitted, "both states should be present now")
		self.assertLess(max(barred), min(permitted))

	def test_the_filter_offers_exactly_the_states_the_rule_produces(self):
		"""The Select is written out in the .js, so nothing but this stops the two
		drifting into two spellings of the same state."""
		source = frappe.read_file(
			frappe.get_app_path(
				"education_extension",
				"education_extension",
				"report",
				"academic_exclusions",
				"academic_exclusions.js",
			)
		)
		for state in (standing.CANNOT_REGISTER, standing.ALLOWED_ANYWAY):
			self.assertIn("'{0}'".format(state), source)

	def test_it_asks_for_the_whole_cohort_in_a_fixed_number_of_queries(self):
		"""It runs over every student with results, and a query per student is how
		a report becomes one nobody opens.

		The bound is a little above what it takes today, so ordinary framework
		churn does not fail it. A query per student would be a hundred and eighty
		over, which is the shape this is here to catch.
		"""
		self.turn_the_rule_on()
		with self.assertQueryCount(35):
			self.run_report()


class TestTheWindowsReadRealDates(IntegrationTestCase):
	"""`period_starts` against the doctypes it actually names.

	The pure tests above hand it dates, so a wrong doctype or a misspelt date
	field would sail past every one of them and only show up as a window that
	silently picks whichever period sorts last by name.
	"""

	def setUp(self):
		needs_education_app(self)
		needs_doctype(self, "Academic Year", "Academic Term")

	def test_each_window_reads_dates_off_its_own_doctype(self):
		for window, doctype in (
			(standing.LATEST_TERM, "Academic Term"),
			(standing.LATEST_YEAR, "Academic Year"),
		):
			starts = standing.period_starts(window)
			names = frappe.get_all(doctype, pluck="name")
			self.assertEqual(set(starts), set(names), window)
			if names:
				self.assertTrue(
					any(date != standing._UNDATED for date in starts.values()),
					"every {0} came back undated, which means the date field is wrong".format(
						doctype
					),
				)

	def test_the_whole_record_reads_no_dates_at_all(self):
		self.assertEqual(standing.period_starts(standing.WHOLE_RECORD), {})


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
	for case in (
		TestTheRule,
		TestTheOverride,
		TestTheExclusionsReport,
		TestTheWindowsReadRealDates,
		TestTheRuleIsOffUntilSomebodyTurnsItOn,
	):
		suite.addTests(loader.loadTestsFromTestCase(case))
	return unittest.TextTestRunner(verbosity=verbosity).run(suite)
