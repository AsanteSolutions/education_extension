# Copyright (c) 2026, Asante Solutions and contributors
# For license information, please see license.txt

"""Fill in the sitting on marks recorded before there was a field for it.

The sitting used to be inferred from the assessment group's name: an aegrotat
paper was one prefixed with AEGRO, and the supplementary exam was a group called
exactly that. This reads those names once and records what they meant, so the
calculation can stop parsing them.

An aegrotat mark also moves onto the assessment it stands in for — "AEGRO Theory
Exam" becomes "Theory Exam" with the sitting saying how it was sat — because the
sitting is now what carries that, not the name.
"""

import re

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_field

AEGROTAT_PREFIX = re.compile(r"^AEGRO(?:TAT)?[\s_-]*", re.IGNORECASE)
SUPP_GROUP = "Supplementary Exam"


def execute():
	# Customisations are synced after post-model-sync patches run, so on the
	# migration that introduces the field the column is not there yet. Creating it
	# here rather than waiting means the backfill happens on the same migration
	# instead of being skipped and marked done.
	if not frappe.db.has_column("Assessment Result", "custom_sitting"):
		create_custom_field(
			"Assessment Result",
			{
				"fieldname": "custom_sitting",
				"label": "Sitting",
				"fieldtype": "Select",
				"options": "Main\nSupplementary\nAegrotat",
				"default": "Main",
				"insert_after": "assessment_group",
				"in_list_view": 1,
				"in_standard_filter": 1,
				"search_index": 1,
			},
		)
		frappe.db.commit()

	frappe.db.sql(
		"""update `tabAssessment Result`
		   set custom_sitting = 'Main'
		   where custom_sitting is null or custom_sitting = ''"""
	)

	frappe.db.sql(
		"""update `tabAssessment Result`
		   set custom_sitting = 'Supplementary'
		   where assessment_group = %s""",
		(SUPP_GROUP,),
	)

	# Aegrotat papers move onto the assessment they replace. Done row by row
	# because the group each one lands on depends on its own name, and there are
	# few enough of them that a statement per row costs nothing.
	aegrotat = [
		row
		for row in frappe.get_all(
			"Assessment Result",
			fields=["name", "assessment_group"],
			limit_page_length=0,
		)
		if AEGROTAT_PREFIX.match((row.assessment_group or "").strip())
	]

	for row in aegrotat:
		stands_in_for = AEGROTAT_PREFIX.sub("", row.assessment_group.strip(), count=1)
		# Only move the mark if the assessment it stands in for actually exists;
		# otherwise leave the name alone and let it show up as unscheduled rather
		# than pointing at a group that is not there.
		updates = {"custom_sitting": "Aegrotat"}
		if frappe.db.exists("Assessment Group", stands_in_for):
			updates["assessment_group"] = stands_in_for

		frappe.db.set_value("Assessment Result", row.name, updates, update_modified=False)

	frappe.db.commit()
