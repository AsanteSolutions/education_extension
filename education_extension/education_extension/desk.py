# Copyright (c) 2026, Asante Solutions and contributors
# For license information, please see license.txt

"""Put this app's doctypes on the Education page and in its sidebar.

Both the Education `Workspace` and its `Workspace Sidebar` are standard records
that Frappe re-syncs from the education app on every migrate, overwriting
whatever is in the database. Adding links by hand therefore does not last — the
Education workspace on this site already had a few added that way, and the next
migrate would have taken them.

So this re-applies instead of editing once. It runs as an `after_migrate` hook,
which Frappe executes last, after that sync has happened. It only ever appends,
and it checks before adding, so repeated migrates neither duplicate nor fight
the education app over ordering.
"""

import json

import frappe

# (card label, [(link target, link type)]) — cards appear in this order, after
# whatever the education app already puts on the page.
CARDS = [
	(
		"Registration",
		[
			("Registration Period", "DocType"),
			("Registration Settings", "DocType"),
			("Registration Status", "Report"),
		],
	),
	(
		"Results and Remarks",
		[
			("Academic Remark", "DocType"),
			("Supplementary Academic Remark", "DocType"),
			("Progress Report Issue Date", "DocType"),
			("Student Progress Report", "DocType"),
			("Student Progress Report Settings", "DocType"),
		],
	),
]

WORKSPACE = "Education"


def add_to_education_workspace():
	"""after_migrate hook. Safe to call at any time."""
	if not frappe.db.exists("Workspace", WORKSPACE):
		# A site without the education app has no page to add to.
		return

	added_links = _add_cards()
	added_items = _add_sidebar_items()

	if added_links or added_items:
		frappe.clear_cache()
		print(
			"Education Extension: added {0} workspace links and {1} sidebar items".format(
				added_links, added_items
			)
		)


def _exists(link_to, link_type):
	"""Whether the target is actually installed, so a link never dangles."""
	doctype = "Report" if link_type == "Report" else "DocType"
	return bool(frappe.db.exists(doctype, link_to))


def _append(doc, table, values, counter):
	"""Append a child row with an explicit idx, continuing past the highest in use.

	`Document.append` numbers a new row from the *count* of rows already in the
	table. The Education links table has gaps in its idx values, so counting
	lands on numbers that are already taken: the first version of this collided
	with nine existing rows and scrambled which links belonged to which card,
	because card membership is positional.
	"""
	row = doc.append(table, values)
	row.idx = next(counter)
	return row


def _idx_counter(rows):
	"""Numbers from one past the highest idx in use."""
	start = max((row.idx or 0) for row in rows) + 1 if rows else 1
	return iter(range(start, start + 1000))


def _add_cards():
	workspace = frappe.get_doc("Workspace", WORKSPACE)
	present = {row.label for row in workspace.links if row.type == "Card Break"}
	content = json.loads(workspace.content or "[]")
	counter = _idx_counter(workspace.links)
	added = blocks = 0

	for label, links in CARDS:
		wanted = [(target, kind) for target, kind in links if _exists(target, kind)]
		if not wanted:
			continue

		# The links and the content block are checked separately. Keying both on
		# the Card Break existing meant a card whose block had gone missing could
		# never be repaired -- the links were there, so it skipped the whole card,
		# and the page rendered nothing.
		if label not in present:
			_append(
				workspace,
				"links",
				{
					"type": "Card Break",
					"label": label,
					# The education app's own cards set this even though a break
					# points at nothing; matching it keeps the rows uniform.
					"link_type": "DocType",
					"link_count": len(wanted),
				},
				counter,
			)
			for target, kind in wanted:
				_append(
					workspace,
					"links",
					{
						"type": "Link",
						"label": target,
						"link_type": kind,
						"link_to": target,
						# Script and Query reports both route through query-report.
						"is_query_report": 1 if kind == "Report" else 0,
					},
					counter,
				)
				added += 1

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

	workspace.content = json.dumps(content)
	workspace.flags.ignore_permissions = True
	workspace.save()
	return added or blocks


def _block_id(label):
	"""A stable id for the content block, since Frappe expects one per block."""
	return "ee-" + label.lower().replace(" ", "-")


def _add_sidebar_items():
	if not frappe.db.exists("Workspace Sidebar", WORKSPACE):
		# Frappe generates one from the workspace shortcuts if it is missing; there
		# is nothing to append to until it does.
		return 0

	sidebar = frappe.get_doc("Workspace Sidebar", WORKSPACE)
	sections = {row.label for row in sidebar.items if row.type == "Section Break"}
	linked = {row.link_to for row in sidebar.items if row.type == "Link"}
	counter = _idx_counter(sidebar.items)
	added = 0

	for label, links in CARDS:
		wanted = [
			(target, kind)
			for target, kind in links
			if _exists(target, kind) and target not in linked
		]
		if not wanted:
			continue

		if label not in sections:
			# Matching the education app's own convention: a section carries the
			# indent, and the links under it are marked as children.
			_append(
				sidebar,
				"items",
				{
					"type": "Section Break",
					"label": label,
					"link_type": "DocType",
					"indent": 1,
					"collapsible": 1,
					"keep_closed": 1,
				},
				counter,
			)

		for target, kind in wanted:
			_append(
				sidebar,
				"items",
				{
					"type": "Link",
					"label": target,
					"link_type": kind,
					"link_to": target,
					"child": 1,
					"indent": 0,
					"collapsible": 1,
				},
				counter,
			)
			added += 1

	if not added:
		return 0

	sidebar.flags.ignore_permissions = True
	sidebar.save()
	return added
