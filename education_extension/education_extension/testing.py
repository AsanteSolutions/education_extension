# Copyright (c) 2026, Asante Solutions and contributors
# For license information, please see license.txt

"""Helpers shared by the test suites.

Not named `test_*` on purpose — the runner collects modules by that prefix and
this one holds no tests of its own.
"""

import frappe


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
