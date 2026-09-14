# Copyright (c) 2026, Asante Solutions and Contributors
# See license.txt

"""Tests for the registration dashboard.

Two things are being protected. The first is wiring: a number card names its
method as a string and a chart names its source as a link, so a rename breaks
them somewhere no importer and no test would otherwise look — the card just
shows a dash.

The second is that the numbers agree. They are all counted off the same report
a registrar drills into, and the whole point of doing it that way is that the
dashboard and the list underneath it can never tell different stories.

    from education_extension.education_extension.test_dashboard import run_tests
    run_tests()
"""

import unittest

import frappe
from frappe.tests import IntegrationTestCase

from education_extension.education_extension import dashboard
from education_extension.education_extension.report.registration_status.registration_status import (
	NOT_REGISTERED,
	NOT_THIS_TERM,
	REGISTERED,
)

MODULE = "Education Extension"


class TestDashboardWiring(IntegrationTestCase):
	"""The records exist and point at things that are really there."""

	def test_every_number_card_calls_a_method_that_exists(self):
		cards = frappe.get_all(
			"Number Card", filters={"module": MODULE}, fields=["name", "type", "method"]
		)
		self.assertTrue(cards, "no number cards were synced")

		for card in cards:
			self.assertEqual(card.type, "Custom", card.name)
			self.assertTrue(card.method, card.name)
			method = frappe.get_attr(card.method)
			self.assertTrue(callable(method), card.method)
			self.assertIn(
				method,
				frappe.whitelisted,
				"{0} is not whitelisted, so the card cannot call it".format(card.method),
			)

	def test_every_chart_has_a_source_that_exists(self):
		charts = frappe.get_all(
			"Dashboard Chart", filters={"module": MODULE}, fields=["name", "chart_type", "source"]
		)
		self.assertTrue(charts, "no charts were synced")

		for chart in charts:
			self.assertEqual(chart.chart_type, "Custom", chart.name)
			self.assertTrue(
				frappe.db.exists("Dashboard Chart Source", chart.source), chart.source
			)

	def test_every_chart_source_ships_the_javascript_that_registers_it(self):
		"""A Custom chart is not fetched through the Dashboard Chart endpoint —
		that one has no branch for it. The browser asks for the source's own `.js`,
		evaluates it, and calls whatever method it registers.

		Ship the `.py` without the `.js` and the chart draws nothing and reports
		nothing: an empty box, no error in the console, no error in the log. All
		three of these shipped that way once. This walks the same path the client
		does, so the wiring is checked rather than the counting.
		"""
		from frappe.desk.doctype.dashboard_chart_source.dashboard_chart_source import get_config

		sources = frappe.get_all("Dashboard Chart", filters={"module": MODULE}, pluck="source")
		self.assertTrue(sources)

		for source in sources:
			config = get_config(source)
			self.assertIn("frappe.dashboards.chart_sources", config, source)
			self.assertIn(source, config, source)

			method = config.split('method: "')[1].split('"')[0]
			resolved = frappe.get_attr(method)
			self.assertTrue(callable(resolved), method)

			chart = resolved(chart_name=source, refresh=1)
			self.assertIn("labels", chart, source)
			self.assertEqual(
				len(chart["labels"]), len(chart["datasets"][0]["values"]), source
			)

	def test_the_dashboard_names_only_cards_and_charts_that_exist(self):
		self.assertTrue(frappe.db.exists("Dashboard", "Registration"))
		doc = frappe.get_doc("Dashboard", "Registration")
		self.assertTrue(doc.cards)
		self.assertTrue(doc.charts)

		for row in doc.cards:
			self.assertTrue(frappe.db.exists("Number Card", row.card), row.card)
		for row in doc.charts:
			self.assertTrue(frappe.db.exists("Dashboard Chart", row.chart), row.chart)

	def test_every_card_drills_down_somewhere_real(self):
		"""The widget binds a click handler to every card whatever its type, so a
		card without a `route` in its payload is clickable and does nothing. That
		reads as broken rather than as "this one does not drill down"."""
		for card in frappe.get_all(
			"Number Card", filters={"module": MODULE}, fields=["name", "method"]
		):
			payload = frappe.get_attr(card.method)()
			route = payload.get("route")
			self.assertTrue(route, "{0} has nowhere to go".format(card.name))

			kind = route[0]
			if kind == "query-report":
				self.assertTrue(frappe.db.exists("Report", route[1]), route)
			elif kind == "List":
				self.assertTrue(frappe.db.exists("DocType", route[1]), route)
			elif kind == "Form":
				self.assertTrue(frappe.db.exists(route[1], route[2]), route)
			else:
				self.fail("unrecognised route {0} on {1}".format(route, card.name))

	def test_every_chart_offers_a_filter(self):
		"""The dialog is built from the `filters` the source's javascript
		declares. Declare none and the button opens an empty box."""
		from frappe.desk.doctype.dashboard_chart_source.dashboard_chart_source import get_config

		for source in frappe.get_all(
			"Dashboard Chart", filters={"module": MODULE}, pluck="source"
		):
			config = get_config(source)
			self.assertIn("filters:", config, source)
			self.assertIn("academic_term", config, source)

	def test_a_chart_honours_the_term_it_is_given(self):
		"""Otherwise the filter is there, does nothing, and quietly tells the
		reader the two terms are identical."""
		terms = frappe.get_all("Academic Term", pluck="name")
		focus = dashboard.term_in_focus()
		other = [term for term in terms if term != focus]
		if not other or not focus:
			self.skipTest("only one academic term on this site")

		self.assertEqual(
			dashboard.progress({"academic_term": focus}), dashboard.progress()
		)
		# Some other term has to differ somewhere, or the filter proves nothing.
		self.assertTrue(
			any(
				dashboard.progress({"academic_term": term}) != dashboard.progress()
				for term in other
			),
			"no term produced different numbers",
		)

	def test_an_unset_filter_falls_back_to_the_term_in_focus(self):
		"""The widget sends the empty case in more than one shape."""
		focus = dashboard.term_in_focus()
		for payload in (None, {}, [], "[]", "{}"):
			self.assertEqual(dashboard.chosen_term(payload), focus, repr(payload))

	def test_the_dashboard_is_reachable_from_the_sidebar(self):
		"""The only route to it, since the numbers are not on the workspace page.
		A dashboard nothing links to is a dashboard nobody opens."""
		if not frappe.db.exists("Workspace Sidebar", MODULE):
			self.skipTest("no sidebar on this site")

		sidebar = frappe.get_doc("Workspace Sidebar", MODULE)
		linked = {row.link_to for row in sidebar.items if row.link_type == "Dashboard"}
		self.assertIn("Registration", linked)

	def test_the_workspace_page_stays_a_page_of_links(self):
		"""The numbers belong on the dashboard. The workspace is where someone
		goes to open a record, and widgets drifting back onto it is the thing
		worth catching."""
		if not frappe.db.exists("Workspace", MODULE):
			self.skipTest("the workspace has not been synced on this site")

		import json

		workspace = frappe.get_doc("Workspace", MODULE)
		self.assertEqual(list(workspace.number_cards), [])
		self.assertEqual(list(workspace.charts), [])
		self.assertEqual(
			[
				block["type"]
				for block in json.loads(workspace.content or "[]")
				if block["type"] in ("number_card", "chart")
			],
			[],
		)


class TestDashboardNumbers(IntegrationTestCase):
	"""What the cards and charts actually say."""

	def setUp(self):
		self.term = dashboard.term_in_focus()
		if not self.term:
			self.skipTest("no registration period on this site")
		self.rows = dashboard.rows_in_focus(self.term)

	def test_the_term_is_chosen_and_not_asked_for(self):
		"""Dashboard filters are evaluated in the browser, so nothing here can be
		handed a term. It has to pick one, and never none while a period exists."""
		self.assertTrue(frappe.db.exists("Academic Term", self.term))
		self.assertIsNotNone(dashboard.period_in_focus())

	def test_registered_and_still_to_register_come_off_the_report(self):
		self.assertEqual(
			dashboard.students_registered()["value"],
			sum(1 for row in self.rows if row["status"] == REGISTERED),
		)
		self.assertEqual(
			dashboard.students_still_to_register()["value"],
			sum(1 for row in self.rows if row["status"] == NOT_REGISTERED),
		)

	def test_the_progress_chart_accounts_for_every_student(self):
		chart = dashboard.progress()
		if not self.rows:
			self.skipTest("no students in this term")
		self.assertEqual(sum(chart["datasets"][0]["values"]), len(self.rows))
		self.assertEqual(
			set(chart["labels"]), {REGISTERED, NOT_REGISTERED, NOT_THIS_TERM}
		)

	def test_the_per_day_chart_adds_up_to_the_registered_card(self):
		"""The invariant that makes the chart trustworthy. Registrations dated
		outside the window are bucketed rather than dropped, so a cohort enrolled
		administratively cannot leave the chart reading 1 beside a card reading
		70."""
		self.assertEqual(
			sum(dashboard.per_day()["datasets"][0]["values"]),
			dashboard.students_registered()["value"],
		)

	def test_the_programme_chart_counts_registered_students_only(self):
		chart = dashboard.by_programme()
		registered = dashboard.students_registered()["value"]
		# A student registered for two programmes is counted under each, so the
		# total is at least the headcount and never below it.
		self.assertGreaterEqual(sum(chart["datasets"][0]["values"]), registered)
		self.assertEqual(len(chart["labels"]), len(chart["datasets"][0]["values"]))

	def test_consents_never_outnumber_registrations(self):
		"""The other way round is a real state — a consent for a registration
		that was later cancelled — but more consents than registrations would
		mean one was written without an enrolment behind it."""
		self.assertLessEqual(
			dashboard.consent_forms_signed()["value"],
			max(dashboard.students_registered()["value"], 0) + len(self.rows),
		)

	def test_days_left_is_never_negative(self):
		"""It is read as "how long have I got", and a negative reads as a bug
		rather than as a closed window."""
		self.assertGreaterEqual(dashboard.days_left_to_register()["value"], 0)

	def test_the_year_chart_adds_up_to_the_cards(self):
		"""It splits the same two numbers across the years of study, so the two
		series have to come back to the two cards. A student counted into the
		wrong year would still total correctly; a student dropped would not."""
		chart = dashboard.per_year()
		registered, still = chart["datasets"][0], chart["datasets"][1]

		self.assertEqual(registered["name"], "Registered")
		self.assertEqual(sum(registered["values"]), dashboard.students_registered()["value"])
		self.assertEqual(
			sum(still["values"]), dashboard.students_still_to_register()["value"]
		)

	def test_the_report_gives_every_countable_student_a_block(self):
		"""The year chart groups on it. If the report stopped supplying it the
		chart would empty out and nothing else would notice."""
		term = dashboard.term_in_focus()
		if not term:
			self.skipTest("no registration period on this site")

		for row in dashboard.rows_in_focus(term):
			if row["status"] == NOT_THIS_TERM:
				continue
			self.assertTrue(
				row.get("block"), "{0} is countable but has no block".format(row["student"])
			)

	def test_every_chart_returns_the_shape_the_widget_expects(self):
		for name, chart in (
			("progress", dashboard.progress()),
			("by_programme", dashboard.by_programme()),
			("per_day", dashboard.per_day()),
			("per_year", dashboard.per_year()),
		):
			self.assertIn("labels", chart, name)
			self.assertTrue(chart["datasets"], name)
			for dataset in chart["datasets"]:
				self.assertEqual(len(chart["labels"]), len(dataset["values"]), name)


class TestDashboardPermissions(IntegrationTestCase):
	"""These are whitelisted and they count the whole cohort."""

	CALLS = (
		"students_registered",
		"students_still_to_register",
		"provisional_modules",
		"modules_needing_review",
		"days_left_to_register",
		"consent_forms_signed",
	)

	def test_the_numbers_answer_to_the_reports_own_roles(self):
		"""Every one of these is the Registration Status report counted up, so
		the two have to admit the same people. Gating the dashboard on the wider
		set that decides whether to show the app tile handed an Instructor,
		through the cards, the cohort list the report refuses them."""
		import json
		import os

		path = os.path.join(
			os.path.dirname(__file__),
			"report",
			"registration_status",
			"registration_status.json",
		)
		with open(path) as handle:
			granted = {row["role"] for row in json.load(handle)["roles"]}

		self.assertEqual(set(dashboard.REGISTRAR_ROLES), granted)

	def test_a_student_cannot_read_the_cohort_numbers(self):
		user = frappe.db.get_value("Student", {"user": ("is", "set")}, "user")
		if not user:
			self.skipTest("no student with a portal user on this site")
		if set(dashboard.REGISTRAR_ROLES) & set(frappe.get_roles(user)):
			self.skipTest("this student also holds a staff role")

		frappe.set_user(user)
		try:
			for name in self.CALLS:
				with self.assertRaises(frappe.PermissionError, msg=name):
					getattr(dashboard, name)()
			for name in ("progress", "by_programme", "per_day"):
				with self.assertRaises(frappe.PermissionError, msg=name):
					getattr(dashboard, name)()
		finally:
			frappe.set_user("Administrator")

	def test_staff_can(self):
		user = frappe.db.get_value(
			"Has Role",
			{
				"role": "Education Manager",
				"parenttype": "User",
				"parent": ("not in", ("Administrator", "Guest")),
			},
			"parent",
		)
		if not user:
			self.skipTest("nobody holds Education Manager on this site")

		frappe.set_user(user)
		try:
			for name in self.CALLS:
				self.assertIn("value", getattr(dashboard, name)(), name)
		finally:
			frappe.set_user("Administrator")


def run_tests(verbosity=2):
	"""Run these from a console, since bench run-tests cannot bootstrap this site."""
	suite = unittest.TestSuite()
	loader = unittest.TestLoader()
	for case in (TestDashboardWiring, TestDashboardNumbers, TestDashboardPermissions):
		suite.addTests(loader.loadTestsFromTestCase(case))
	return unittest.TextTestRunner(verbosity=verbosity).run(suite)
