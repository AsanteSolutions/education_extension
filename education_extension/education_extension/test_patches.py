# Copyright (c) 2026, Asante Solutions and Contributors
# See license.txt

"""Tests for the patches, which run once and are hard to watch.

A patch gets one chance on each site and nobody is looking when it takes it, so
the branch that decides *not* to act matters as much as the one that does.

    from education_extension.education_extension.test_patches import run_tests
    run_tests()
"""

import unittest

import frappe
from frappe.tests import IntegrationTestCase

from education_extension.education_extension.testing import needs_doctype
from education_extension.patches import drop_stale_permission_overrides as overrides

DOCTYPE = "Academic Remark"


class TestDroppingStalePermissionOverrides(IntegrationTestCase):
	"""Editing permissions in the UI snapshots them, and the snapshot then hides
	every role the app adds afterwards. Freeing it must not cost a site anything
	it chose."""

	def setUp(self):
		needs_doctype(self, DOCTYPE)
		self.shipped = frappe.get_all(
			"DocPerm",
			filters={"parent": DOCTYPE},
			fields=["role", "permlevel", *overrides.FLAGS],
		)
		if len(self.shipped) < 2:
			self.skipTest("{0} ships fewer than two permission rows".format(DOCTYPE))

		if frappe.db.count("Custom DocPerm", {"parent": DOCTYPE}):
			self.skipTest("this site already overrides the permissions on {0}".format(DOCTYPE))

	def tearDown(self):
		frappe.db.rollback()
		frappe.clear_cache(doctype=DOCTYPE)

	def snapshot(self, omit=None, grant=None):
		"""The state the Role Permissions Manager leaves behind.

		`omit` is a role the snapshot predates — the app added it later, so it is
		in DocPerm and not here. `grant` is (role, flag) somebody turned on, which
		is the thing that must survive.
		"""
		for row in self.shipped:
			if row.role == omit:
				continue
			values = {flag: row.get(flag) for flag in overrides.FLAGS}
			if grant and row.role == grant[0]:
				values[grant[1]] = 1
			frappe.get_doc(
				dict(
					values,
					doctype="Custom DocPerm",
					parent=DOCTYPE,
					parenttype="DocType",
					parentfield="permissions",
					role=row.role,
					permlevel=row.permlevel,
				)
			).insert(ignore_permissions=True)

		return frappe.db.count("Custom DocPerm", {"parent": DOCTYPE})

	def roles_in_force(self):
		"""Whose permissions Frappe actually reads: the overrides if any exist,
		the shipped ones otherwise. That substitution is the whole problem."""
		table = (
			"Custom DocPerm"
			if frappe.db.count("Custom DocPerm", {"parent": DOCTYPE})
			else "DocPerm"
		)
		return set(frappe.get_all(table, filters={"parent": DOCTYPE}, pluck="role"))

	def test_a_snapshot_that_predates_a_role_is_dropped(self):
		withheld = self.shipped[-1].role
		self.snapshot(omit=withheld)
		self.assertNotIn(withheld, self.roles_in_force(), "the test did not reproduce the problem")

		overrides.reconcile(DOCTYPE)

		self.assertEqual(frappe.db.count("Custom DocPerm", {"parent": DOCTYPE}), 0)
		self.assertIn(withheld, self.roles_in_force(), "the role is still being held out")

	def test_a_snapshot_someone_added_to_is_left_alone(self):
		"""The safety property. Another site may have granted something
		deliberately, and this app has no business throwing that away."""
		role = next(row.role for row in self.shipped if not row.get("amend"))
		before = self.snapshot(omit=self.shipped[-1].role, grant=(role, "amend"))

		overrides.reconcile(DOCTYPE)

		self.assertEqual(
			frappe.db.count("Custom DocPerm", {"parent": DOCTYPE}),
			before,
			"a deliberate grant was thrown away",
		)
		self.assertTrue(
			frappe.db.get_value("Custom DocPerm", {"parent": DOCTYPE, "role": role}, "amend")
		)

	def test_a_snapshot_with_an_extra_role_is_left_alone(self):
		"""A role the app does not ship is somebody's decision too.

		A role is omitted as well, so the patch has a reason to act and is being
		stopped by the extra role rather than by having nothing to do. Without
		that this passed with the guard removed.
		"""
		self.snapshot(omit=self.shipped[-1].role)
		frappe.get_doc(
			{
				"doctype": "Custom DocPerm",
				"parent": DOCTYPE,
				"parenttype": "DocType",
				"parentfield": "permissions",
				"role": "Guest",
				"permlevel": 0,
				"read": 1,
			}
		).insert(ignore_permissions=True)
		before = frappe.db.count("Custom DocPerm", {"parent": DOCTYPE})

		overrides.reconcile(DOCTYPE)

		self.assertEqual(frappe.db.count("Custom DocPerm", {"parent": DOCTYPE}), before)

	def test_a_faithful_copy_is_left_where_it_is(self):
		"""Redundant, but not this patch's business — it is here to free a role,
		not to tidy up."""
		before = self.snapshot()

		overrides.reconcile(DOCTYPE)

		self.assertEqual(frappe.db.count("Custom DocPerm", {"parent": DOCTYPE}), before)

	def test_it_does_nothing_where_nothing_was_overridden(self):
		"""The ordinary site, and the state this one is in now that it has run."""
		overrides.reconcile(DOCTYPE)
		self.assertEqual(frappe.db.count("Custom DocPerm", {"parent": DOCTYPE}), 0)

	def test_the_roles_the_remark_endpoint_admits_can_all_write(self):
		"""What the whole exercise was for.

		`set_course_remark` calls `frappe.only_for` with these three, so each of
		them has to be able to file a comment and take it back again.
		"""
		for doctype in overrides.DOCTYPES:
			needs_doctype(self, doctype)
			for role in ("Academics User", "Education Manager", "System Manager"):
				row = frappe.db.get_value(
					"DocPerm",
					{"parent": doctype, "role": role, "permlevel": 0},
					["write", "submit", "cancel"],
					as_dict=True,
				)
				self.assertTrue(row, "{0} has no permission row on {1}".format(role, doctype))
				for flag in ("write", "submit", "cancel"):
					self.assertTrue(
						row.get(flag),
						"{0} cannot {1} a {2}, but the endpoint admits them".format(
							role, flag, doctype
						),
					)


def run_tests(verbosity=2):
	"""Run these from a console, since bench run-tests cannot bootstrap this site."""
	suite = unittest.TestSuite()
	loader = unittest.TestLoader()
	for case in (TestDroppingStalePermissionOverrides,):
		suite.addTests(loader.loadTestsFromTestCase(case))
	return unittest.TextTestRunner(verbosity=verbosity).run(suite)
