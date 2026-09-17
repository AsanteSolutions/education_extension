# Copyright (c) 2026, Asante Solutions and contributors
# For license information, please see license.txt

"""Helpers shared by the test suites.

Not named `test_*` on purpose — the runner collects modules by that prefix and
this one holds no tests of its own.
"""

import frappe

# Where Frappe's test-record generation stops.
#
# On an IntegrationTestCase, Frappe builds test records for the doctype under
# test and, recursively, for everything its link fields point at. From this
# app's doctypes that reaches 206 doctypes — 137 of them ERPNext's — and the
# walk imports each one's test module on the way. `erpnext/tests/utils.py`
# builds its master data at import time and needs the setup wizard to have run,
# which on a test site it has not, so the whole run dies on a missing root Item
# Group before a single test of ours executes.
#
# None of these tests want those records. Each either builds its documents in
# memory or skips when the real thing is absent — there is no test_records.json
# anywhere in this app. So the walk is stopped at this app's own boundary: these
# are every doctype from another app that this app's records link to.
#
# Imported into each doctype's test module, where Frappe looks for it.
IGNORE_TEST_RECORD_DEPENDENCIES = [
	"Academic Term",
	"Academic Year",
	"Assessment Group",
	"Course",
	"DocType",
	"Letter Head",
	"Student",
	"Student Group",
	"User",
	"Workflow State",
]


def needs_education_app(case):
	"""Skip unless the education app is installed.

	This app extends education, so most of what the integration tests reach for
	— Student, Course, Academic Year, Academic Term — is that app's. CI installs
	this app on its own, where those doctypes do not exist: a query against one
	raises rather than coming back empty, so a test that only checks for no rows
	errors instead of skipping.
	"""
	if "education" not in frappe.get_installed_apps():
		case.skipTest("the education app is not installed on this site")


def needs_doctype(case, *doctypes):
	"""Skip unless every named doctype is present.

	For the cases that depend on one particular doctype rather than on the whole
	app, so the reason a test skipped names the thing that was missing.
	"""
	for doctype in doctypes:
		if not frappe.db.exists("DocType", doctype):
			case.skipTest("{0} is not installed on this site".format(doctype))
