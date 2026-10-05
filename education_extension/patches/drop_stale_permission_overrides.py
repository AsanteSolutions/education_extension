# Copyright (c) 2026, Asante Solutions and contributors
# For license information, please see license.txt

"""Let the app's own permissions govern its remark doctypes again.

Editing permissions through the Role Permissions Manager copies every DocPerm a
doctype has into Custom DocPerm and works on the copy from then on. The copy is
a snapshot: a role the app adds to its own JSON afterwards is synced into
DocPerm, where nothing reads it any more, because the presence of *any* Custom
DocPerm makes Frappe ignore the lot.

That is what happened here. Someone granted System Manager cancel and amend on
the two remark doctypes, which snapshotted them; Education Manager was added to
this app's JSON later and never reached the snapshot. The result is a role the
app's own endpoints admit -- `marking.set_course_remark` calls `frappe.only_for`
with it -- holding no permission at all on the records it is being asked to
write. Nothing anywhere said so.

The snapshot is dropped so the shipped permissions apply again, and the grant
that caused it is now in the shipped permissions too, so nothing is lost by
dropping it.

Conservative on purpose. Another site may have customised these deliberately, and
this app has no business throwing that away: the snapshot goes only where it
grants nothing the shipped permissions do not already grant. Anywhere else it is
left alone and reported, for a person to look at.
"""

import frappe

DOCTYPES = ("Academic Remark", "Supplementary Academic Remark")

# Every flag a DocPerm row carries. Compared in full rather than on the few that
# prompted this, so a customisation anywhere on the row is still noticed.
FLAGS = (
	"read",
	"write",
	"create",
	"delete",
	"submit",
	"cancel",
	"amend",
	"report",
	"export",
	"share",
	"print",
	"email",
	"if_owner",
)


def execute():
	for doctype in DOCTYPES:
		if not frappe.db.exists("DocType", doctype):
			continue
		reconcile(doctype)


def reconcile(doctype):
	custom = _rows("Custom DocPerm", doctype)
	if not custom:
		return

	shipped = _rows("DocPerm", doctype)
	granted = _extra_grants(custom, shipped)
	if granted:
		print(
			"Education Extension: left the permission overrides on {0} alone -- they "
			"grant {1}, which the app's own permissions do not.".format(
				doctype, ", ".join(granted)
			)
		)
		return

	withheld = sorted(key[0] for key in shipped if key not in custom)
	if not withheld:
		# A faithful copy. Harmless, and not this patch's business.
		return

	frappe.permissions.reset_perms(doctype)
	frappe.clear_cache(doctype=doctype)
	print(
		"Education Extension: dropped the stale permission overrides on {0}; "
		"{1} can act on it again.".format(doctype, ", ".join(withheld))
	)


def _rows(table, doctype):
	"""(role, permlevel) -> the flags that row sets."""
	return {
		(row.role, row.permlevel): {flag: row.get(flag) for flag in FLAGS}
		for row in frappe.get_all(
			table, filters={"parent": doctype}, fields=["role", "permlevel", *FLAGS]
		)
	}


def _extra_grants(custom, shipped):
	"""What the overrides allow that the shipped permissions do not.

	Only ever one direction. A row the overrides are *missing* is the thing being
	repaired; a row or a flag they *add* is somebody's decision.
	"""
	extra = []
	for key, flags in sorted(custom.items()):
		role, permlevel = key
		where = "{0} (level {1})".format(role, permlevel) if permlevel else role

		if key not in shipped:
			extra.append(where)
			continue

		added = sorted(flag for flag, value in flags.items() if value and not shipped[key][flag])
		if added:
			extra.append("{0}: {1}".format(where, "/".join(added)))

	return extra
