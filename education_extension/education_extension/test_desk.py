# Copyright (c) 2026, Asante Solutions and Contributors
# See license.txt

"""Tests for the desk page this app ships and the copy of it on Education.

None of this is logic anyone reads; it is a page, and the way a page breaks is
quietly — a link to a doctype that was renamed, a card that stopped being copied
across, a tile pointing at a logo that is not there. Each of those looks fine in
the code and wrong on the screen, so they are checked here instead.

    from education_extension.education_extension.test_desk import run_tests
    run_tests()
"""

import glob
import json
import os
import unittest

import frappe
from frappe.tests import IntegrationTestCase

from education_extension.education_extension import desk
from education_extension.education_extension.testing import needs_doctype


class TestAppPage(IntegrationTestCase):
	"""The workspace, sidebar and apps-screen tile this app ships."""

	def setUp(self):
		if not frappe.db.exists("Workspace", desk.SOURCE):
			self.skipTest("the workspace has not been synced on this site")

	def test_every_link_on_the_page_points_at_something_installed(self):
		"""A link to a doctype that was renamed still renders; it just 404s when
		someone clicks it."""
		workspace = frappe.get_doc("Workspace", desk.SOURCE)
		dangling = [
			row.link_to
			for row in workspace.links
			if row.type == "Link" and not desk._exists(row.link_to, row.link_type)
		]
		self.assertEqual(dangling, [])

	def test_every_card_on_the_page_has_a_block_to_render_it(self):
		"""Cards live in two places on a Workspace: the links table says what is in
		them, and `content` says where they go. A card missing from `content` is
		simply not on the page."""
		import json

		workspace = frappe.get_doc("Workspace", desk.SOURCE)
		cards = {row.label for row in workspace.links if row.type == "Card Break"}
		blocks = {
			block["data"]["card_name"]
			for block in json.loads(workspace.content or "[]")
			if block.get("type") == "card"
		}
		self.assertEqual(cards - blocks, set(), "card with nothing to render it")
		self.assertEqual(blocks - cards, set(), "block for a card that is not there")

	def test_every_shortcut_points_at_a_doctype_on_the_page(self):
		workspace = frappe.get_doc("Workspace", desk.SOURCE)
		linked = {row.link_to for row in workspace.links if row.type == "Link"}
		for shortcut in workspace.shortcuts:
			self.assertTrue(frappe.db.exists("DocType", shortcut.link_to), shortcut.link_to)
			self.assertIn(shortcut.link_to, linked, shortcut.link_to)

	def test_the_sidebar_offers_the_same_links_as_the_page(self):
		"""They are two views of one page, and a link on one and not the other is
		how someone concludes a feature is missing."""
		if not frappe.db.exists("Workspace Sidebar", desk.SOURCE):
			self.skipTest("no sidebar on this site")

		workspace = frappe.get_doc("Workspace", desk.SOURCE)
		sidebar = frappe.get_doc("Workspace Sidebar", desk.SOURCE)
		on_page = {row.link_to for row in workspace.links if row.type == "Link"}
		# Everything the page can also carry. The sidebar has navigation the page
		# has no equivalent of — its own Home link, and the dashboard — so those
		# link types are left out of the comparison rather than the links.
		in_sidebar = {
			row.link_to
			for row in sidebar.items
			if row.type == "Link" and row.link_type in ("DocType", "Report", "Page")
		}
		self.assertEqual(on_page, in_sidebar)

	def test_the_tile_points_at_a_logo_that_is_there(self):
		"""A missing logo is a broken image on the apps screen, and nothing in the
		code says so."""
		self.assertTrue(os.path.exists(self._logo_path(self._tile()["logo"])))

	def test_the_desk_carries_an_icon_for_this_app(self):
		"""The apps screen and the desk are two different places, and a tile on
		one puts nothing on the other. This app had the tile and no desk icon."""
		self._needs_desktop_icons()
		self.assertTrue(frappe.db.exists("Desktop Icon", desk.SOURCE))

		icon = frappe.get_doc("Desktop Icon", desk.SOURCE)
		self.assertEqual(icon.app, "education_extension")
		self.assertEqual(icon.icon_type, "App")
		self.assertTrue(icon.standard)
		self.assertFalse(icon.hidden)

	def test_the_desk_icon_opens_this_app_own_sidebar(self):
		self._needs_desktop_icons()
		icon = frappe.get_doc("Desktop Icon", desk.SOURCE)
		self.assertEqual(icon.link_type, "Workspace Sidebar")
		self.assertTrue(frappe.db.exists("Workspace Sidebar", icon.link_to), icon.link_to)

	def test_the_desk_icon_and_the_tile_share_one_logo(self):
		"""Two records naming the same file, so renaming it has to move both."""
		self._needs_desktop_icons()
		icon = frappe.get_doc("Desktop Icon", desk.SOURCE)
		self.assertEqual(icon.logo_url, self._tile()["logo"])
		self.assertTrue(os.path.exists(self._logo_path(icon.logo_url)), icon.logo_url)

	def test_the_desk_icon_is_shown_to_the_same_people_as_the_page(self):
		self._needs_desktop_icons()
		icon = frappe.get_doc("Desktop Icon", desk.SOURCE)
		self.assertEqual({row.role for row in icon.roles}, set(desk.STAFF_ROLES))

	def _needs_desktop_icons(self):
		if not frappe.db.exists("DocType", "Desktop Icon"):
			self.skipTest("this Frappe has no Desktop Icon doctype")

	def _logo_path(self, url):
		prefix = "/assets/education_extension/"
		self.assertTrue(url.startswith(prefix), url)
		return frappe.get_app_path("education_extension", "public", url[len(prefix) :])

	def test_the_tile_points_at_this_app_own_page(self):
		self.assertEqual(self._tile()["route"], "/app/" + frappe.scrub(desk.SOURCE).replace("_", "-"))

	def test_staff_are_offered_the_tile(self):
		for role in sorted(desk.STAFF_ROLES):
			user = frappe.db.get_value(
				"Has Role",
				{"role": role, "parenttype": "User", "parent": ("not in", ("Administrator", "Guest"))},
				"parent",
			)
			if not user:
				continue
			frappe.set_user(user)
			try:
				self.assertTrue(desk.has_app_permission(), role)
			finally:
				frappe.set_user("Administrator")

	def test_a_student_is_not_offered_the_tile(self):
		needs_doctype(self, "Student")
		user = frappe.db.get_value("Student", {"user": ("is", "set")}, "user")
		if not user:
			self.skipTest("no student with a portal user on this site")
		if desk.STAFF_ROLES & set(frappe.get_roles(user)):
			self.skipTest("this student also holds a staff role")

		frappe.set_user(user)
		try:
			self.assertFalse(desk.has_app_permission())
		finally:
			frappe.set_user("Administrator")

	def test_the_page_is_shown_to_the_same_people_as_the_tile(self):
		"""Otherwise the tile is hidden and the page is still reachable, or the
		other way round, and only one of those is noticed."""
		workspace = frappe.get_doc("Workspace", desk.SOURCE)
		self.assertEqual({row.role for row in workspace.roles}, set(desk.STAFF_ROLES))

	def _tile(self):
		tiles = frappe.get_hooks("add_to_apps_screen", app_name="education_extension")
		self.assertEqual(len(tiles), 1)
		return tiles[0]


class TestTheSharedDeskScript(IntegrationTestCase):
	"""The desk script three reports, a page and a form all reach for.

	It is included as a plain path rather than a bundle, which is what lets it
	reach a site without `bench build`: `/assets/education_extension` is a
	symlink to this app's public directory, and Frappe only consults the built
	asset manifest for a path with `.bundle.` in it. That is also what makes
	this worth a test -- a path that no longer resolves breaks five screens at
	once, and nothing else would notice.
	"""

	def test_the_script_the_hook_names_is_on_disk_where_it_is_served_from(self):
		import os

		included = [
			path
			for path in frappe.get_hooks("app_include_js") or []
			if "education_extension" in path
		]
		self.assertTrue(included, "the app includes no desk script")

		for path in included:
			self.assertNotIn(
				".bundle.",
				path,
				"a bundled path would need `bench build` before it resolved",
			)
			served = os.path.join(frappe.local.sites_path, path.lstrip("/"))
			self.assertTrue(
				os.path.isfile(served), "{0} is not served from {1}".format(path, served)
			)

	def test_every_screen_that_uses_it_is_covered_by_the_hook(self):
		"""The five scripts call it; none of them loads it themselves."""
		import os

		app = os.path.dirname(os.path.dirname(os.path.abspath(desk.__file__)))
		callers = [
			"education_extension/report/academic_exclusions/academic_exclusions.js",
			"education_extension/report/registration_status/registration_status.js",
			"education_extension/report/module_registrations/module_registrations.js",
			"education_extension/page/sign_registration_forms/sign_registration_forms.js",
			"education_extension/doctype/registration_override/registration_override.js",
		]
		for relative in callers:
			path = os.path.join(app, relative)
			if not os.path.isfile(path):
				self.skipTest("{0} is not in this checkout".format(relative))
			with open(path) as handle:
				source = handle.read()
			self.assertIn(
				"education_extension.",
				source,
				"{0} does not use the shared script".format(relative),
			)
			self.assertNotIn(
				"opens_on desc",
				source,
				"{0} still has its own copy of the term lookup".format(relative),
			)


class TestCopyOntoEducation(IntegrationTestCase):
	"""The links this app adds to the Education page."""

	def setUp(self):
		if not frappe.db.exists("Workspace", desk.TARGET):
			self.skipTest("the education app is not installed on this site")
		if not desk._cards():
			self.skipTest("the workspace has not been synced on this site")

	def test_the_education_page_carries_every_card_this_app_ships(self):
		workspace = frappe.get_doc("Workspace", desk.TARGET)
		rows = sorted(workspace.links, key=lambda row: row.idx or 0)

		for label, _icon, links in desk._cards():
			bounds = desk._group_bounds(rows, label, "Card Break")
			self.assertIsNotNone(bounds, "card {0} was not copied".format(label))
			start, end = bounds
			present = {rows[i].link_to for i in range(start + 1, end)}
			self.assertEqual(
				{row[0] for row in links} - present,
				set(),
				"card {0} is missing links".format(label),
			)

	def test_the_links_keep_the_labels_this_app_gave_them(self):
		"""The page says "Sign Registration Forms", not `sign-registration-forms`.

		The copy used to drop the label and fall back on the link target, which
		reads as the doctype's own name for a DocType and as a raw slug for a
		Page or a Report. The test beside this one compares only `link_to`, so
		nothing caught it.
		"""
		self.addCleanup(frappe.db.rollback)

		# Run the copy, then look at what it left: a site copied before labels
		# were carried across still holds the old ones until the next migrate,
		# and it is the migrate's result being asserted here.
		desk.add_to_education_workspace()
		rows = sorted(frappe.get_doc("Workspace", desk.TARGET).links, key=lambda r: r.idx or 0)

		for label, _icon, links in desk._cards():
			bounds = desk._group_bounds(rows, label, "Card Break")
			if bounds is None:
				continue
			start, end = bounds
			placed = {rows[i].link_to: rows[i].label for i in range(start + 1, end)}
			for target, _kind, wanted in links:
				if target in placed:
					self.assertEqual(
						placed[target],
						wanted,
						"{0} is labelled {1!r} here and {2!r} on our own page".format(
							target, placed[target], wanted
						),
					)

	def test_our_cards_hold_nothing_but_their_own_links(self):
		"""The other half of the previous test, and the half that catches a bad
		insert: these tables are read positionally, so a row put at the end of the
		table joins whichever card happens to be last.

		Only the cards this app adds are checked. A link of ours somewhere else on
		the page was put there by hand -- the Education page on this site has a
		Settings card someone filled in that way -- and this hook neither placed it
		nor should move it.
		"""
		workspace = frappe.get_doc("Workspace", desk.TARGET)
		rows = sorted(workspace.links, key=lambda row: row.idx or 0)

		for label, _icon, links in desk._cards():
			bounds = desk._group_bounds(rows, label, "Card Break")
			if bounds is None:
				continue
			start, end = bounds
			inside = {rows[i].link_to for i in range(start + 1, end)}
			self.assertEqual(
				inside - {row[0] for row in links},
				set(),
				"the {0} card picked up a link that is not its own".format(label),
			)

	def test_the_idx_values_do_not_collide(self):
		"""Card membership is positional, so two rows sharing an idx scramble which
		links belong to which card."""
		for doctype, table in (("Workspace", "links"), ("Workspace Sidebar", "items")):
			if not frappe.db.exists(doctype, desk.TARGET):
				continue
			rows = frappe.get_doc(doctype, desk.TARGET).get(table)
			idxs = [row.idx for row in rows]
			self.assertEqual(len(set(idxs)), len(idxs), "{0} has duplicate idx".format(doctype))

	def test_copying_again_changes_nothing(self):
		"""It runs on every migrate, so a second run has to be a no-op.

		The baseline is taken after one run, not before it. A site can have work
		outstanding -- labels copied before the label was carried across, say --
		and settling that on the next migrate is the point of the hook. What must
		not happen is a run that keeps finding something to do for ever.
		"""
		self.addCleanup(frappe.db.rollback)

		desk.add_to_education_workspace()
		before = self._snapshot()
		desk.add_to_education_workspace()
		self.assertEqual(self._snapshot(), before)

	def test_a_dangling_row_somebody_else_left_does_not_stop_the_migrate(self):
		"""This page is the education app's, and rows get added to it by hand.

		One of them pointing at something that has since gone makes an ordinary
		save refuse -- and this save runs inside an after_migrate hook, so the
		refusal takes `bench migrate` down over a row this app never wrote. The
		sidebar path has always said so; the workspace path did not.
		"""
		self.addCleanup(frappe.db.rollback)

		# Every save here goes through the guard: this is the education app's own
		# page, and on a developer_mode site an unguarded save writes it back out
		# over that app's file.
		with desk._without_writing_to_the_source_tree():
			workspace = frappe.get_doc("Workspace", desk.TARGET)
			workspace.append(
				"links",
				{
					"type": "Link",
					"label": "Left Behind",
					"link_type": "DocType",
					"link_to": "A Doctype That Was Deleted",
				},
			)
			workspace.flags.ignore_permissions = True
			workspace.flags.ignore_links = True
			workspace.save()

			# Forces a save: with nothing to add, `_add_cards` returns early and
			# the dangling row is never put in front of the validator at all.
			desk._add_cards(
				[("Dangling Row Test", "folder", [("Student", "DocType", "Student")])]
			)

	def test_a_link_under_two_cards_is_added_to_the_sidebar_once(self):
		"""`linked` is read once, so it has to be kept up to date as rows go in.

		A target listed under two cards on the source page passed the "not already
		there" test twice and was written into the sidebar twice. `_place_card`
		keeps a per-card set against exactly this.
		"""
		if not frappe.db.exists("Workspace Sidebar", desk.TARGET):
			self.skipTest("this site has no education sidebar")

		target = "Course Mark Scheme"
		if not desk._exists(target, "DocType"):
			self.skipTest("{0} is not installed".format(target))

		self.addCleanup(frappe.db.rollback)

		with desk._without_writing_to_the_source_tree():
			# Out of the sidebar first, so there is something for both to add.
			sidebar = frappe.get_doc("Workspace Sidebar", desk.TARGET)
			sidebar.items = [row for row in sidebar.items if row.link_to != target]
			sidebar.flags.ignore_permissions = True
			sidebar.flags.ignore_links = True
			sidebar.save()

			desk._add_sidebar_items(
				[
					("Twice Listed A", "folder", [(target, "DocType", target)]),
					("Twice Listed B", "folder", [(target, "DocType", target)]),
				],
				desk.TARGET,
			)

		rows = frappe.get_doc("Workspace Sidebar", desk.TARGET).items
		self.assertEqual(
			[row.link_to for row in rows].count(target),
			1,
			"a link listed under two cards was written into the sidebar twice",
		)

	def _snapshot(self):
		state = {}
		for doctype, table in (("Workspace", "links"), ("Workspace Sidebar", "items")):
			if not frappe.db.exists(doctype, desk.TARGET):
				continue
			rows = sorted(frappe.get_doc(doctype, desk.TARGET).get(table), key=lambda r: r.idx or 0)
			state[doctype] = [(row.type, row.label, row.link_to) for row in rows]
		return state


class TestTheDashboardTheSidebarPointsAt(IntegrationTestCase):
	"""The sidebar links to this app's dashboard, and Frappe makes that dashboard.

	Not this app: `sync_dashboards` creates the Dashboard, the four charts and the
	six cards from the files this app ships them in, on install and again on every
	migrate. Which is the trap. On an install it runs *after* the `after_install`
	hooks, so while `apply_desk_records` is running the dashboard does not exist
	yet, and saving a sidebar that links to it would be refused.

	The wipes use `frappe.db.delete` rather than `delete_doc`, and the saves go
	through `_without_writing_to_the_source_tree`. Both matter on a developer_mode
	site, where deleting a standard record deletes the file the app ships it in
	and saving one exports it back over that file. Before the guard was added
	these tests rewrote the shipped sidebar from the database mid-run, which
	quietly repaired the very drift one of them is here to detect.
	"""

	SHIPPED = (
		("Number Card", "number_card"),
		("Dashboard Chart", "dashboard_chart"),
		("Dashboard", "education_extension_dashboard"),
	)

	def setUp(self):
		needs_doctype(self, "Dashboard", "Dashboard Chart", "Number Card")
		if not frappe.db.exists("Workspace Sidebar", desk.SOURCE):
			self.skipTest("no sidebar on this site")

	def tearDown(self):
		frappe.db.rollback()
		frappe.clear_cache()

	def shipped_names(self, folder):
		pattern = os.path.join(
			frappe.get_app_path("education_extension", "education_extension", folder), "*", "*.json"
		)
		return {json.load(open(path, encoding="utf-8"))["name"] for path in glob.glob(pattern)}

	def unlink(self, link_to):
		"""Take one row out of the sidebar, so the hook has work to do.

		Without this the hook finds nothing to add, never saves, and a test of
		what happens when it saves passes without doing anything. Which is exactly
		how the install broke: the shipped sidebar listed everything the workspace
		did, so the save had not run in months.
		"""
		frappe.db.delete("Workspace Sidebar Item", {"parent": desk.SOURCE, "link_to": link_to})
		frappe.clear_cache()

	def wipe(self):
		"""The state a fresh install is in when `after_install` hooks run."""
		dashboards = list(self.shipped_names("education_extension_dashboard"))
		for table in ("Dashboard Chart Link", "Number Card Link"):
			frappe.db.delete(table, {"parent": ["in", dashboards]})
		for doctype, _folder in self.SHIPPED:
			frappe.db.delete(doctype, {"module": "Education Extension"})
		frappe.clear_cache()

	def test_the_shipped_sidebar_file_lists_what_the_shipped_page_file_does(self):
		"""Read off the files, not the database.

		`fill_in_our_own_sidebar` repairs a sidebar record that has fallen behind
		the page, which is why the two files drifting apart went unnoticed for as
		long as it did -- every site looked right. The files are what a fresh
		install starts from, so they are what this checks.
		"""

		def read(*parts):
			with open(frappe.get_app_path("education_extension", *parts), encoding="utf-8") as f:
				return json.load(f)

		page = read(
			"education_extension", "workspace", "education_extension", "education_extension.json"
		)
		sidebar = read("workspace_sidebar", "education_extension.json")

		on_page = {row["link_to"] for row in page["links"] if row["type"] == "Link"}
		# The sidebar carries navigation the page has no equivalent of -- its own
		# Home link and the dashboard -- so those link types are left out rather
		# than those links.
		in_sidebar = {
			row["link_to"]
			for row in sidebar["items"]
			if row["type"] == "Link" and row["link_type"] in ("DocType", "Report", "Page")
		}
		self.assertEqual(on_page, in_sidebar)

	def test_frappe_makes_every_record_this_app_ships_for_its_dashboard(self):
		"""If this ever stops being true, the sidebar link goes nowhere and the
		dashboard is empty. Nothing else in this app would notice."""
		from frappe.utils.dashboard import sync_dashboards

		self.wipe()
		with desk._without_writing_to_the_source_tree():
			sync_dashboards("education_extension")

		for doctype, folder in self.SHIPPED:
			present = set(
				frappe.get_all(doctype, filters={"module": "Education Extension"}, pluck="name")
			)
			self.assertEqual(present, self.shipped_names(folder), doctype)

	def test_the_hook_survives_the_dashboard_not_existing_yet(self):
		"""The install failure, reproduced.

		`developer_mode` is turned off for the duration because that is how a real
		install runs, and several of the records involved validate differently
		under it -- a standard Dashboard Chart refuses to be written at all. With
		it left on, this passes for the wrong reason.
		"""
		self.wipe()
		self.unlink("Academic Exclusions")

		developer_mode = frappe.conf.developer_mode
		in_install = frappe.flags.in_install
		try:
			frappe.conf.developer_mode = 0
			frappe.flags.in_install = "education_extension"
			with desk._without_writing_to_the_source_tree():
				desk.apply_desk_records()
		finally:
			frappe.conf.developer_mode = developer_mode
			frappe.flags.in_install = in_install

		sidebar = frappe.get_doc("Workspace Sidebar", desk.SOURCE)
		links = [row.link_to for row in sidebar.items if row.type == "Link"]
		self.assertIn("Academic Exclusions", links, "the hook did not put the link back")

	def test_nothing_dangles_once_frappe_has_caught_up(self):
		"""The two halves in the order an install runs them."""
		from frappe.utils.dashboard import sync_dashboards

		self.wipe()
		self.unlink("Academic Exclusions")

		in_install = frappe.flags.in_install
		try:
			frappe.flags.in_install = "education_extension"
			with desk._without_writing_to_the_source_tree():
				desk.apply_desk_records()
		finally:
			frappe.flags.in_install = in_install

		with desk._without_writing_to_the_source_tree():
			sync_dashboards("education_extension")

		sidebar = frappe.get_doc("Workspace Sidebar", desk.SOURCE)
		self.assertEqual(desk._dangling_links(sidebar), [])

	def test_a_dangling_row_is_reported_rather_than_fatal(self):
		"""Surviving the ordering is not the same as hiding a real breakage.

		A sidebar row pointing at something absent must not stop an install, so the
		save ignores links -- and then says what dangled, once an install is not
		what is running.
		"""
		self.wipe()

		sidebar = frappe.get_doc("Workspace Sidebar", desk.SOURCE)
		sidebar.flags.ignore_permissions = True
		# Without the guard this is the failure, which is the proof the guard is
		# doing something.
		with desk._without_writing_to_the_source_tree():
			with self.assertRaises(frappe.LinkValidationError):
				sidebar.save()

		sidebar = frappe.get_doc("Workspace Sidebar", desk.SOURCE)
		sidebar.flags.ignore_permissions = True
		sidebar.flags.ignore_links = True
		with desk._without_writing_to_the_source_tree():
			sidebar.save()
		self.assertTrue(desk._dangling_links(sidebar), "the dashboard should be reported missing")


def run_tests(verbosity=2):
	"""Run these from a console, since bench run-tests cannot bootstrap this site."""
	suite = unittest.TestSuite()
	loader = unittest.TestLoader()
	for case in (
		TestAppPage,
		TestTheSharedDeskScript,
		TestCopyOntoEducation,
		TestTheDashboardTheSidebarPointsAt,
	):
		suite.addTests(loader.loadTestsFromTestCase(case))
	return unittest.TextTestRunner(verbosity=verbosity).run(suite)
