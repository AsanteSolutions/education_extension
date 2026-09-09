# Copyright (c) 2026, Asante Solutions and contributors
# For license information, please see license.txt

"""Create the workflow a Course Mark Sheet moves through.

Shipped as a patch rather than a fixture so it can be created without exporting
every other app's workflows alongside it. Idempotent: an existing workflow is
left alone, so a site that has tuned the transitions keeps them.
"""

import frappe

WORKFLOW = "Course Mark Sheet Approval"

# state, docstatus, the role that may act while the sheet sits here
STATES = [
	("Awaiting Entry", 0, "Instructor"),
	("In Entry", 0, "Instructor"),
	("Submitted for Checking", 0, "Academics User"),
	("Checked", 0, "Academics User"),
	("Moderated", 0, "Education Manager"),
	("Approved", 1, "Education Manager"),
	("Released", 1, "Education Manager"),
]

# from state, action, to state, the role allowed to take it
TRANSITIONS = [
	("Awaiting Entry", "Start Entering", "In Entry", "Instructor"),
	("In Entry", "Submit for Checking", "Submitted for Checking", "Instructor"),
	("Submitted for Checking", "Return for Correction", "In Entry", "Academics User"),
	("Submitted for Checking", "Mark as Checked", "Checked", "Academics User"),
	("Checked", "Return for Correction", "In Entry", "Academics User"),
	("Checked", "Record Moderation", "Moderated", "Academics User"),
	# A cohort that needs no adjustment goes straight from checked to approved.
	("Checked", "Approve", "Approved", "Education Manager"),
	("Moderated", "Return for Correction", "In Entry", "Education Manager"),
	("Moderated", "Approve", "Approved", "Education Manager"),
	("Approved", "Release", "Released", "Education Manager"),
]


def execute():
	if frappe.db.exists("Workflow", WORKFLOW):
		return

	for state, _docstatus, _role in STATES:
		if not frappe.db.exists("Workflow State", state):
			frappe.get_doc({"doctype": "Workflow State", "workflow_state_name": state}).insert(
				ignore_permissions=True
			)

	for _from_state, action, _to_state, _role in TRANSITIONS:
		if not frappe.db.exists("Workflow Action Master", action):
			frappe.get_doc(
				{"doctype": "Workflow Action Master", "workflow_action_name": action}
			).insert(ignore_permissions=True)

	workflow = frappe.get_doc(
		{
			"doctype": "Workflow",
			"workflow_name": WORKFLOW,
			"document_type": "Course Mark Sheet",
			"workflow_state_field": "workflow_state",
			"is_active": 1,
			# Marks are entered against the sheet, so the entry states have to stay
			# editable by the role that holds them.
			"send_email_alert": 0,
			"states": [
				{
					"state": state,
					"doc_status": docstatus,
					"allow_edit": role,
					"update_field": None,
				}
				for state, docstatus, role in STATES
			],
			"transitions": [
				{
					"state": from_state,
					"action": action,
					"next_state": to_state,
					"allowed": role,
					"allow_self_approval": 1,
				}
				for from_state, action, to_state, role in TRANSITIONS
			],
		}
	)
	workflow.insert(ignore_permissions=True)
