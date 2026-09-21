# Copyright (c) 2026, Asante Solutions and contributors
# For license information, please see license.txt

"""Take the pad's guide line off signatures already stamped onto forms.

Signing trims the mark now, but a form signed before that did is still carrying
the line, and prints with two: the pad's above the page's own rule.

Re-trimmed in place rather than re-signed. Who countersigned a registration and
when are part of the record, and nothing about fixing the look of a line is a
reason to restamp them with today's date.
"""

import frappe

from education_extension.education_extension.registration_forms import trim


def execute():
	signed = frappe.get_all(
		"Registration Consent",
		filters={"registrar_signature": ["is", "set"]},
		fields=["name", "registrar_signature"],
		limit_page_length=0,
	)
	if not signed:
		return

	trimmed = 0
	for row in signed:
		cleaned = trim(row.registrar_signature)
		if not cleaned or cleaned == row.registrar_signature:
			continue

		frappe.db.set_value(
			"Registration Consent",
			row.name,
			"registrar_signature",
			cleaned,
			update_modified=False,
		)
		trimmed += 1

	print(
		"Education Extension: trimmed the pad's line from {0} of {1} signed form(s).".format(
			trimmed, len(signed)
		)
	)
