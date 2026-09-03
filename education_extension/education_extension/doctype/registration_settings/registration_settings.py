# Copyright (c) 2026, Asante Solutions and contributors
# For license information, please see license.txt

"""Institute-wide registration policy.

Only the fee rule lives here so far, and it is off by default. Policy that holds
across terms belongs here rather than being restated on every Registration
Period, where it would drift.
"""

import frappe
from frappe.model.document import Document
from frappe.query_builder.functions import Sum


class RegistrationSettings(Document):
	pass


def outstanding_balance(student):
	"""What the student owes: the outstanding total across their submitted Sales
	Invoices. Zero when they have no linked Customer or no invoices."""
	customer = frappe.db.get_value("Student", student, "customer")
	if not customer:
		return 0.0

	# Query builder rather than an aggregate in get_value: v16 rejects SQL
	# functions passed as strings.
	invoice = frappe.qb.DocType("Sales Invoice")
	total = (
		frappe.qb.from_(invoice)
		.select(Sum(invoice.outstanding_amount))
		.where(invoice.customer == customer)
		.where(invoice.docstatus == 1)
	).run()[0][0]
	return float(total or 0)


def fee_block(student):
	"""The balance that stops this student registering, or 0.0 if none does.

	Returns the amount rather than a boolean so the portal can name the figure --
	being refused without being told how much is owed sends the student to the
	office to find out.
	"""
	settings = frappe.get_cached_doc("Registration Settings")
	if not settings.block_on_outstanding_fees:
		return 0.0

	balance = outstanding_balance(student)
	tolerance = float(settings.outstanding_fee_tolerance or 0)
	return balance if balance > tolerance else 0.0
