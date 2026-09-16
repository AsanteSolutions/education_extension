# Copyright (c) 2026, Asante Solutions and contributors
# For license information, please see license.txt

"""This app's own desk page, and a copy of its links on the Education page.

The page itself is not built here. The app ships a `Workspace`, a
`Workspace Sidebar` and a tile on the apps screen as ordinary standard records,
which Frappe syncs from the files in this app on every migrate.

What needs code is the second place those links appear. Registration and marking
are not a separate job from running the school -- the staff doing them work on
the Education page, and the links belong there too. That `Workspace` and its
`Workspace Sidebar` belong to the education app, which re-syncs both from its own
files on every migrate, overwriting whatever is in the database. The Education
workspace on this site already had a few links added by hand, and the next
migrate would have taken them.

So this re-applies rather than editing once. It runs as an `after_migrate` hook,
which Frappe executes last, after that sync has happened. It only adds what is
missing, so repeated migrates neither duplicate nor fight the education app over
ordering.

What it copies is read off this app's own workspace rather than listed here as
well, so a doctype added to the page turns up in both places.
"""

import json
import os
from contextlib import contextmanager

import frappe

# The page this app ships, and the page its links are copied onto.
SOURCE = "Education Extension"
TARGET = "Education"

# Who is offered the tile on the apps screen. Not a security boundary: every
# page behind it is still governed by the permissions on the doctypes
# themselves. This only keeps the tile off the screen of someone with no reason
# to open it.
STAFF_ROLES = frozenset(
	{"System Manager", "Education Manager", "Academics User", "Instructor"}
)


def has_app_permission():
	"""Whether to show this app on the apps screen."""
	if frappe.session.user == "Administrator":
		return True
	return bool(STAFF_ROLES & set(frappe.get_roles()))


def apply_desk_records():
	"""after_install / after_migrate hook. Safe to call at any time."""
	# The sidebar first: the icon links to it.
	ensure_standard_record("Workspace Sidebar", "workspace_sidebar")
	ensure_standard_record("Desktop Icon", "desktop_icon")
	add_to_education_workspace()


def ensure_standard_record(doctype, folder):
	"""Create a record this app ships that Frappe will not import for itself.

	Two of them sit in that gap, and both were missing from every fresh install.
	`Desktop Icon` is not in Frappe's IMPORTABLE_DOCTYPES at all, so nothing ever
	reads its file. `Workspace Sidebar` is importable, but Frappe looks for
	standard records under the *module* folder as <doctype>/<name>/<name>.json
	while its own exporter writes sidebars to the *app* folder as
	workspace_sidebar/<name>.json — import and export disagree, and the file is
	written where the importer does not look. Moving it to where the importer
	looks only starts a fight with the exporter, so both records are created from
	their files here instead.

	They existed only on sites where somebody had made one by hand, which is why
	this went unnoticed: the desk icon and the sidebar were both absent from a
	clean install, and the sidebar's absence showed up only as a skipped test.

	Create-only. The file stays the description of the record, and anything
	already in the database is left alone rather than being overwritten from the
	app on every migrate.
	"""
	if not frappe.db.exists("DocType", doctype):
		# An older Frappe, or one built without that part of the desk.
		return
	if frappe.db.exists(doctype, SOURCE):
		return

	path = frappe.get_app_path("education_extension", folder, "education_extension.json")
	if not os.path.exists(path):
		return

	with open(path, encoding="utf-8") as handle:
		record = json.load(handle)

	# Left to Frappe, rather than carrying the file's own.
	for stamp in ("creation", "modified", "owner", "modified_by", "idx", "docstatus"):
		record.pop(stamp, None)

	doc = frappe.get_doc(record)
	# What Frappe's own importer does for a standard record — import_file.py sets
	# the same flag before inserting. Without it these validate their links while
	# the site is still being built: the icon points at the sidebar, and the
	# sidebar points at a dashboard that is synced later still. A record arriving
	# a moment early should not take the installation down with it.
	doc.flags.ignore_links = True

	with _without_writing_to_the_source_tree():
		doc.insert(ignore_permissions=True)

	print("Education Extension: created {0} {1}".format(doctype, SOURCE))


def add_to_education_workspace():
	"""after_migrate hook. Safe to call at any time."""
	if not frappe.db.exists("Workspace", TARGET):
		# A site without the education app has no page to add to.
		return

	cards = _cards()
	if not cards:
		# Our own workspace has not synced yet, so there is nothing to copy.
		return

	with _without_writing_to_the_source_tree():
		added_links = _add_cards(cards)
		added_items = _add_sidebar_items(cards)

	if added_links or added_items:
		frappe.clear_cache()
		print(
			"Education Extension: added {0} workspace links and {1} sidebar items".format(
				added_links, added_items
			)
		)


def _cards():
	"""(label, icon, [(link target, link type)]) read off this app's own workspace.

	Defined there and not here as well. The page is the thing being copied, so a
	second list could only ever be a way for the two to disagree -- and the way
	that would show is a doctype reachable from one page and not the other.
	"""
	if not frappe.db.exists("Workspace", SOURCE):
		return []

	cards = []
	for row in frappe.get_doc("Workspace", SOURCE).links:
		if row.type == "Card Break":
			cards.append((row.label, row.icon, []))
		elif row.type == "Link" and cards and row.link_to:
			cards[-1][2].append((row.link_to, row.link_type))

	return [card for card in cards if card[2]]


@contextmanager
def _without_writing_to_the_source_tree():
	"""Keep these saves out of anyone's source tree.

	On a developer_mode site, saving a standard record writes it back to the app
	that owns it. Two things here need that suppressed. The Workspace and
	Workspace Sidebar being edited are the education app's own, so without this
	every migrate rewrites files under apps/education -- on this site that was
	over a thousand lines of churn in a repository this app has no business
	touching. The desk icon is this app's own file, and re-exporting it on every
	migrate restamps its timestamps and leaves a diff nobody made.

	`Workspace` checks a set of flags before exporting and `Workspace Sidebar`
	checks `in_import`, so both are set. They are the flags Frappe itself uses to
	mark a save as machinery rather than as someone editing the page.
	"""
	before = (frappe.flags.in_patch, frappe.flags.in_import)
	frappe.flags.in_patch = True
	frappe.flags.in_import = True
	try:
		yield
	finally:
		frappe.flags.in_patch, frappe.flags.in_import = before


def _exists(link_to, link_type):
	"""Whether the target is actually installed, so a link never dangles."""
	doctype = "Report" if link_type == "Report" else "DocType"
	return bool(frappe.db.exists(doctype, link_to))


def _insert(doc, table, position, values):
	"""Add a child row at a chosen position rather than at the end.

	Both of these tables are read positionally -- a link belongs to the card or
	section above it -- so a row added to an existing group has to go inside that
	group. Appending it to the end of the table would file it under whichever
	group happens to be last.
	"""
	row = doc.append(table, values)
	rows = doc.get(table)
	rows.remove(row)
	rows.insert(position, row)
	return row


def _resequence(rows):
	"""Number the table 1..n in list order.

	`Document.append` numbers a new row from the *count* of rows already in the
	table, and the Education links table has gaps in its idx values, so counting
	lands on numbers already taken: an early version of this collided with nine
	existing rows and scrambled which links belonged to which card. Renumbering
	the whole table in the order it is already in removes that class of bug --
	nothing moves, the numbers just stop colliding.
	"""
	for position, row in enumerate(rows, start=1):
		row.idx = position


def _group_bounds(rows, label, break_type):
	"""Where a card or section starts and ends, or None if it is not there.

	The group runs from its break to the next one, which is what makes these
	tables positional.
	"""
	start = next(
		(i for i, row in enumerate(rows) if row.type == break_type and row.label == label),
		None,
	)
	if start is None:
		return None

	end = start + 1
	while end < len(rows) and rows[end].type != break_type:
		end += 1
	return start, end


def _add_cards(cards):
	workspace = frappe.get_doc("Workspace", TARGET)
	content = json.loads(workspace.content or "[]")
	added = blocks = 0

	for label, icon, links in cards:
		wanted = [(target, kind) for target, kind in links if _exists(target, kind)]
		added += _place_card(workspace, label, icon, wanted)
		if not (wanted or _group_bounds(workspace.links, label, "Card Break")):
			# Nothing in the card is installed on this site, so there is no card.
			continue

		# The page renders from `content`; a card in `links` with no block here
		# simply would not show. Checked separately from the links, because the two
		# can fall out of step -- links removed by hand would otherwise leave the
		# block behind and this would add a second one.
		if not any(
			block.get("type") == "card" and block.get("data", {}).get("card_name") == label
			for block in content
		):
			content.append(
				{"id": _block_id(label), "type": "card", "data": {"card_name": label, "col": 4}}
			)
			blocks += 1

	if not (added or blocks):
		return 0

	_resequence(workspace.links)
	workspace.content = json.dumps(content)
	workspace.flags.ignore_permissions = True
	workspace.save()
	return added or blocks


def _place_card(workspace, label, icon, wanted):
	"""Add the card if it is absent, or fill in what it is missing if it is not.

	The second half matters as much as the first: this app gains doctypes, and a
	card built once by an earlier version would otherwise never hear about them.
	"""
	rows = workspace.links
	bounds = _group_bounds(rows, label, "Card Break")
	added = 0

	if bounds is None:
		if not wanted:
			return 0
		position = len(rows)
		_insert(
			workspace,
			"links",
			position,
			{
				"type": "Card Break",
				"label": label,
				"icon": icon,
				# The education app's own cards set this even though a break
				# points at nothing; matching it keeps the rows uniform.
				"link_type": "DocType",
				"link_count": len(wanted),
			},
		)
		start, end = position, position + 1
	else:
		start, end = bounds
		# A card left by an earlier version has no icon. Filling it in keeps the
		# three looking like one set rather than two generations of this hook.
		if icon and not rows[start].icon:
			rows[start].icon = icon
			added += 1

	present = {rows[i].link_to for i in range(start + 1, end)}
	for target, kind in wanted:
		if target in present:
			continue
		_insert(
			workspace,
			"links",
			end,
			{
				"type": "Link",
				"label": target,
				"link_type": kind,
				"link_to": target,
				# Script and Query reports both route through query-report.
				"is_query_report": 1 if kind == "Report" else 0,
			},
		)
		end += 1
		added += 1

	rows[start].link_count = end - start - 1
	return added


def _block_id(label):
	"""A stable id for the content block, since Frappe expects one per block."""
	return "ee-" + label.lower().replace(" ", "-")


def _add_sidebar_items(cards):
	if not frappe.db.exists("Workspace Sidebar", TARGET):
		# Frappe generates one from the workspace shortcuts if it is missing; there
		# is nothing to append to until it does.
		return 0

	sidebar = frappe.get_doc("Workspace Sidebar", TARGET)
	# A link already somewhere in the sidebar is left where it is, so this never
	# competes with the education app over where something belongs.
	linked = {row.link_to for row in sidebar.items if row.type == "Link"}
	added = 0

	for label, icon, links in cards:
		wanted = [
			(target, kind)
			for target, kind in links
			if _exists(target, kind) and target not in linked
		]
		added += _place_section(sidebar, label, icon, wanted)

	if not added:
		return 0

	_resequence(sidebar.items)
	sidebar.flags.ignore_permissions = True
	sidebar.save()
	return added


def _place_section(sidebar, label, icon, wanted):
	rows = sidebar.items
	bounds = _group_bounds(rows, label, "Section Break")
	added = 0

	if bounds is None:
		if not wanted:
			return 0
		position = len(rows)
		# Matching the education app's own convention: a section carries the
		# indent, and the links under it are marked as children.
		_insert(
			sidebar,
			"items",
			position,
			{
				"type": "Section Break",
				"label": label,
				"icon": icon,
				"link_type": "DocType",
				"indent": 1,
				"collapsible": 1,
				"keep_closed": 1,
			},
		)
		end = position + 1
	else:
		# A section left by an earlier version has no icon, the same repair the
		# cards get.
		if icon and not rows[bounds[0]].icon:
			rows[bounds[0]].icon = icon
			added += 1
		end = bounds[1]

	for target, kind in wanted:
		_insert(
			sidebar,
			"items",
			end,
			{
				"type": "Link",
				"label": target,
				"link_type": kind,
				"link_to": target,
				"child": 1,
				"indent": 0,
				"collapsible": 1,
			},
		)
		end += 1
		added += 1

	return added
