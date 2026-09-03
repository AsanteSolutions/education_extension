# Copyright (c) 2026, Asante Solutions and contributors
# For license information, please see license.txt

"""Institute-wide registration policy.

Policy that holds across terms belongs here rather than being restated on every
Registration Period, where it would drift.
"""

import frappe
from frappe.model.document import Document
from frappe.query_builder.functions import Sum

# What an institution means by a prerequisite with no result on record.
MISSING_IGNORED = "Do not block"
MISSING_BLOCKS = "Treat as not passed"


class RegistrationSettings(Document):
	pass


def missing_result_blocks():
	"""Whether a prerequisite with no result stops a student registering.

	The honest answer depends on whether the institution's results are all in the
	system. Where they are, silence means the module was never passed and should
	block. Where the system was adopted mid-programme -- as here, with one term on
	record and most students enrolled straight into their second or third year --
	silence means only that the result predates the system, and blocking on it
	stops every student from everything.

	Defaults to not blocking, because that failure is recoverable by a registrar
	and the other is not: a cohort that cannot register at all has no way through.
	"""
	return frappe.db.get_single_value("Registration Settings", "missing_result_policy") == MISSING_BLOCKS


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
