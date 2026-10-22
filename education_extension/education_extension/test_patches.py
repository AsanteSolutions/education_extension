# Copyright (c) 2026, Asante Solutions and Contributors
# See license.txt

"""Tests for the patches, which run once and are hard to watch.

A patch gets one chance on each site and nobody is looking when it takes it, so
the branch that decides *not* to act matters as much as the one that does.

    from education_extension.education_extension.test_patches import run_tests
    run_tests()
"""

import unittest
from unittest import mock

import frappe
from frappe.tests import IntegrationTestCase

from education_extension.education_extension import lms_sync, student_permissions
from education_extension.education_extension.testing import needs_doctype
from education_extension.patches import convert_remark_codes as codes_patch
from education_extension.patches import create_course_mark_sheet_workflow as workflow_patch
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


class TestTheWorkflowPatchLeavesATunedSiteAlone(IntegrationTestCase):
	"""The guard has to be on the document type, not on this workflow's name.

	`Workflow.set_active` clears `is_active` on every workflow sharing a
	`document_type`, so inserting ours switches off whatever was there. Guarding
	on the name let that happen to any site whose workflow is called something
	else -- silently, and with sheets already in flight carrying states the new
	workflow may not define.
	"""

	def setUp(self):
		needs_doctype(self, "Workflow", "Course Mark Sheet")
		self.existing = frappe.db.get_value(
			"Workflow", {"document_type": workflow_patch.DOCUMENT_TYPE}, "name"
		)
		if not self.existing:
			self.skipTest("this site has no Course Mark Sheet workflow to protect")

	def tearDown(self):
		frappe.db.rollback()

	def test_a_differently_named_workflow_is_left_active(self):
		renamed = "Locally Tuned Sheet Approval"
		frappe.rename_doc("Workflow", self.existing, renamed, force=True)
		frappe.db.set_value("Workflow", renamed, "is_active", 1)

		workflow_patch.execute()

		self.assertFalse(
			frappe.db.exists("Workflow", workflow_patch.WORKFLOW),
			"the patch installed its own workflow over a tuned one",
		)
		self.assertEqual(
			frappe.db.get_value("Workflow", renamed, "is_active"),
			1,
			"the site's own workflow was switched off",
		)

	def test_it_still_does_nothing_when_ours_is_the_one_on_file(self):
		"""The case every site already in service is in."""
		workflow_patch.execute()
		self.assertEqual(
			frappe.get_all(
				"Workflow",
				filters={"document_type": workflow_patch.DOCUMENT_TYPE},
				pluck="name",
			),
			[self.existing],
		)


class TestTheRemarkCodePatchChecksTheColumn(IntegrationTestCase):
	"""It runs in pre_model_sync, before the doctypes are migrated.

	A release that adds a field and ships this patch together finds the table
	there and the column not, and a read of the missing column would abort the
	whole migrate at its first patch -- before anything had been synced.
	"""

	def tearDown(self):
		frappe.db.rollback()

	def test_a_field_the_table_does_not_carry_yet_is_skipped(self):
		with mock.patch.object(
			codes_patch, "FIELDS", ((DOCTYPE, "not_added_until_this_release"),)
		):
			codes_patch.execute()

	def test_the_real_fields_are_still_converted(self):
		"""The control: the guard must not be skipping everything."""
		self.assertTrue(frappe.db.has_column(DOCTYPE, "remark"))
		codes_patch.execute()


class TestConfiningAStudentWhoAlreadyHasANarrowPermission(IntegrationTestCase):
	"""A narrow User Permission is not the confinement.

	One left `applicable_for` a single doctype -- which is how Frappe's own UI
	offers to make them -- restricts that doctype and nothing else, Student
	included. Treating it as "already confined" left the student able to list
	every other student, and said so in the patch's own report.
	"""

	def setUp(self):
		needs_doctype(self, "Student", "User Permission")
		student = frappe.get_all("Student", limit=1, pluck="name")
		if not student:
			self.skipTest("this site has no students")
		self.student = student[0]
		self.user = "test-narrow-permission@example.invalid"

		if not frappe.db.exists("User", self.user):
			user = frappe.new_doc("User")
			user.update(
				{"email": self.user, "first_name": "Narrow", "send_welcome_email": 0}
			)
			user.flags.ignore_permissions = True
			user.insert()

	def tearDown(self):
		frappe.db.rollback()

	def narrow(self):
		permission = frappe.new_doc("User Permission")
		permission.update(
			{
				"user": self.user,
				"allow": "Student",
				"for_value": self.student,
				"apply_to_all_doctypes": 0,
				"applicable_for": "Fees",
			}
		)
		permission.flags.ignore_permissions = True
		permission.insert()
		return permission.name

	def test_a_narrow_permission_does_not_count_as_confined(self):
		self.narrow()
		self.assertFalse(
			student_permissions.existing_permission(self.user, self.student),
			"a permission covering one doctype was read as confining every one",
		)

	def test_confine_still_creates_the_broad_one_alongside_it(self):
		self.narrow()
		self.assertEqual(student_permissions.confine(self.student, self.user), "created")
		self.assertTrue(
			student_permissions.existing_permission(self.user, self.student),
			"the broad permission was not created",
		)

	def test_a_broad_permission_is_still_recognised(self):
		"""The control: having confined someone, this must not do it twice."""
		self.assertEqual(student_permissions.confine(self.student, self.user), "created")
		self.assertEqual(student_permissions.confine(self.student, self.user), "already")


class TestTheServiceUserIsMadeOnEveryMigrate(IntegrationTestCase):
	"""The patch that made it could only act on the site as it stood that day.

	A site without the LMS had no `Moderator` role to grant, so it made nothing,
	and a one-shot patch is never asked again. Installing the LMS afterwards left
	`enqueue` declining to queue for ever, with nothing to log.
	"""

	def setUp(self):
		if not frappe.db.exists("Role", lms_sync.SERVICE_ROLE):
			self.skipTest("no LMS on this site")

	def tearDown(self):
		frappe.db.rollback()

	def test_it_creates_the_account_when_it_is_missing(self):
		if frappe.db.exists("User", lms_sync.SERVICE_USER):
			frappe.delete_doc(
				"User", lms_sync.SERVICE_USER, force=True, ignore_permissions=True
			)
		self.assertFalse(lms_sync.service_user_ready())

		self.assertTrue(lms_sync.ensure_service_user())
		self.assertTrue(
			lms_sync.service_user_ready(), "the account was not left ready to run jobs"
		)

	def test_it_grants_back_a_role_that_was_taken_away(self):
		lms_sync.ensure_service_user()
		user = frappe.get_doc("User", lms_sync.SERVICE_USER)
		user.roles = [row for row in user.roles if row.role != lms_sync.SERVICE_ROLE]
		user.flags.ignore_permissions = True
		user.save()
		self.assertFalse(lms_sync.service_user_ready())

		lms_sync.ensure_service_user()
		self.assertTrue(lms_sync.service_user_ready())

	def test_it_is_idempotent(self):
		"""It runs on every migrate, so running twice has to be uneventful."""
		self.assertTrue(lms_sync.ensure_service_user())
		self.assertTrue(lms_sync.ensure_service_user())


def run_tests(verbosity=2):
	"""Run these from a console, since bench run-tests cannot bootstrap this site."""
	suite = unittest.TestSuite()
	loader = unittest.TestLoader()
	for case in (
		TestDroppingStalePermissionOverrides,
		TestTheWorkflowPatchLeavesATunedSiteAlone,
		TestTheRemarkCodePatchChecksTheColumn,
		TestConfiningAStudentWhoAlreadyHasANarrowPermission,
		TestTheServiceUserIsMadeOnEveryMigrate,
	):
		suite.addTests(loader.loadTestsFromTestCase(case))
	return unittest.TextTestRunner(verbosity=verbosity).run(suite)
