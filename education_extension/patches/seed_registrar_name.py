"""Fill in the registrar named on the Proof of Registration.

The field carries a default, but a default only applies to a new document and
Registration Settings is a Single that already exists on any site that has run a
migrate — so without this the proof prints an unnamed signature line.

Only fills it when empty, so it cannot overwrite a change of registrar.
"""

import frappe

# The registrar named on the institution's current form. Editable in
# Registration Settings; this is only the starting value.
REGISTRAR = "MS N. MOYO"


def execute():
	if not frappe.db.exists("DocType", "Registration Settings"):
		return

	if (frappe.db.get_single_value("Registration Settings", "registrar_name") or "").strip():
		return

	frappe.db.set_single_value("Registration Settings", "registrar_name", REGISTRAR)
	frappe.db.commit()
	print("Seeded registrar name: {0}".format(REGISTRAR))
