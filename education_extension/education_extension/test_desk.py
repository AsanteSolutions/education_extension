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

import os
import unittest

import frappe
from frappe.tests import IntegrationTestCase

from education_extension.education_extension import desk


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
		in_sidebar = {
			row.link_to
			for row in sidebar.items
			if row.type == "Link" and row.link_type != "Workspace"
		}
		self.assertEqual(on_page, in_sidebar)

	def test_the_tile_points_at_a_logo_that_is_there(self):
		"""A missing logo is a broken image on the apps screen, and nothing in the
		code says so."""
		tile = self._tile()
		prefix = "/assets/education_extension/"
		self.assertTrue(tile["logo"].startswith(prefix), tile["logo"])
		path = frappe.get_app_path(
			"education_extension", "public", tile["logo"][len(prefix) :]
		)
		self.assertTrue(os.path.exists(path), path)

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
				{target for target, _kind in links} - present,
				set(),
				"card {0} is missing links".format(label),
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
				inside - {target for target, _kind in links},
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
		"""It runs on every migrate, so a second run has to be a no-op."""
		before = self._snapshot()
		desk.add_to_education_workspace()
		self.assertEqual(self._snapshot(), before)

	def _snapshot(self):
		state = {}
		for doctype, table in (("Workspace", "links"), ("Workspace Sidebar", "items")):
			if not frappe.db.exists(doctype, desk.TARGET):
				continue
			rows = sorted(frappe.get_doc(doctype, desk.TARGET).get(table), key=lambda r: r.idx or 0)
			state[doctype] = [(row.type, row.label, row.link_to) for row in rows]
		return state


def run_tests(verbosity=2):
	"""Run these from a console, since bench run-tests cannot bootstrap this site."""
	suite = unittest.TestSuite()
	loader = unittest.TestLoader()
	for case in (TestAppPage, TestCopyOntoEducation):
		suite.addTests(loader.loadTestsFromTestCase(case))
	return unittest.TextTestRunner(verbosity=verbosity).run(suite)
