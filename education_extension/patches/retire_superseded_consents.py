# Copyright (c) 2026, Asante Solutions and contributors
# For license information, please see license.txt

"""Leave one consent standing per student per term.

Registering recorded a consent without looking for one already on record, so a
student whose enrolment was cancelled or removed and who registered again was
left with both submitted. Registering retires the old one now; this clears up
the terms that collected more than one before it did.

The most recent is the one kept: it is the consent the standing registration was
made under. The others are cancelled rather than deleted -- what the student
agreed to on the day is still what they agreed to -- and a registrar who had
countersigned one of them is asked for the one that now stands, which is the
point of doing this at all.
"""

import frappe


def execute():
	consents = frappe.get_all(
		"Registration Consent",
		filters={"docstatus": 1},
		fields=["name", "student", "academic_year", "academic_term"],
		order_by="creation asc",
		limit_page_length=0,
	)

	terms = {}
	for row in consents:
		terms.setdefault((row.student, row.academic_year, row.academic_term), []).append(row.name)

	superseded = [name for names in terms.values() for name in names[:-1]]
	if not superseded:
		return

	for name in superseded:
		doc = frappe.get_doc("Registration Consent", name)
		doc.flags.ignore_permissions = True
		doc.cancel()
		doc.add_comment(
			"Comment",
			"Superseded: the registration this consent was given for is no longer in force.",
		)

	print(
		"Education Extension: retired {0} superseded consent(s) across {1} term(s).".format(
			len(superseded), sum(1 for names in terms.values() if len(names) > 1)
		)
	)
