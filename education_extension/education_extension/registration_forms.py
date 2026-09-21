# Copyright (c) 2026, Asante Solutions and contributors
# For license information, please see license.txt

"""Signing the printed registration forms.

A student signs their consent on the portal; the Proof of Registration prints
that signature, the modules, and a blank rule for the registrar. Countersigning
was the one part still done on paper, a page at a time, after the fact.

So the registrar's mark is drawn once in Registration Settings and stamped onto
each form as it is signed. Stamped, not referenced: the signature is copied onto
the consent along with the name printed beneath it, the same way the declaration
wording is copied, because the record has to keep saying what was on it at the
time. Changing the settings later leaves signed forms alone.

Nothing here alters what the student agreed to. The consent is submitted by then
and these fields are the only ones on it that may be written afterwards.
"""

import frappe
from frappe import _
from frappe.utils import now_datetime

# The same three roles that may read the cohort through Registration Status and
# the dashboard. Imported rather than repeated: which roles count as the
# registrar is one decision, and this app already has more copies of that kind
# of list than it should.
from education_extension.education_extension.dashboard import REGISTRAR_ROLES

UNSIGNED = "unsigned"
SIGNED = "signed"


def registrar_only():
	frappe.only_for(REGISTRAR_ROLES)


@frappe.whitelist()
def forms(academic_term=None, state=UNSIGNED):
	"""The queue: one light row per consent, without the signatures.

	Deliberately without them. A term is a couple of hundred consents and each
	drawn signature is a data URI of some tens of kilobytes; sending them all to
	build a list of names would make the page slow for no one's benefit. The
	selected form is fetched on its own by `form` below.
	"""
	registrar_only()

	filters = {"docstatus": 1}
	if academic_term:
		filters["academic_term"] = academic_term

	rows = frappe.get_all(
		"Registration Consent",
		filters=filters,
		fields=[
			"name",
			"student",
			"student_name",
			"academic_year",
			"academic_term",
			"consented_at",
			"registrar_name",
			"registrar_signed_at",
		],
		order_by="student_name asc",
		limit_page_length=0,
	)

	for row in rows:
		row["signed"] = bool(row.registrar_signed_at)

	if state == UNSIGNED:
		rows = [row for row in rows if not row["signed"]]
	elif state == SIGNED:
		rows = [row for row in rows if row["signed"]]

	return rows


@frappe.whitelist()
def form(consent):
	"""One consent in full: what the registrar is being asked to countersign."""
	registrar_only()

	doc = frappe.get_doc("Registration Consent", consent)
	return {
		"name": doc.name,
		"student": doc.student,
		"student_name": doc.student_name,
		"academic_year": doc.academic_year,
		"academic_term": doc.academic_term,
		"consented_at": doc.consented_at,
		"prerequisites_declared": doc.prerequisites_declared,
		"popia_consented": doc.popia_consented,
		"student_signature": doc.student_signature,
		"signed_by_guardian": doc.signed_by_guardian,
		"guardian_name": doc.guardian_name,
		"guardian_signature": doc.guardian_signature,
		"registrar_signature": doc.registrar_signature,
		"registrar_name": doc.registrar_name,
		"registrar_signed_at": doc.registrar_signed_at,
		"signed": bool(doc.registrar_signed_at),
		"modules": modules_for(doc),
	}


def modules_for(doc):
	"""The modules this consent was given for.

	Read off the enrolment rather than stored on the consent: the consent
	records what was agreed to, and the enrolment is what was registered. A
	module removed afterwards — a provisional one whose prerequisite failed —
	should not still be on the form the registrar is signing.
	"""
	enrollments = frappe.get_all(
		"Program Enrollment",
		filters={
			"student": doc.student,
			"academic_year": doc.academic_year,
			"academic_term": doc.academic_term,
			"docstatus": 1,
		},
		fields=["name", "program"],
		limit_page_length=0,
	)
	if not enrollments:
		return []

	programs = {row.name: row.program for row in enrollments}
	rows = frappe.get_all(
		"Program Enrollment Course",
		filters={"parent": ["in", list(programs)], "parenttype": "Program Enrollment"},
		fields=["parent", "course", "course_name", "custom_provisional"],
		order_by="parent asc, idx asc",
		limit_page_length=0,
	)

	return [
		{
			"course": row.course,
			"course_name": row.course_name,
			"program": programs[row.parent],
			"provisional": 1 if row.custom_provisional else 0,
		}
		for row in rows
	]


def registrar_mark():
	"""The signature and name to stamp, from Registration Settings."""
	settings = frappe.get_single("Registration Settings")
	return (settings.registrar_signature or "").strip(), (settings.registrar_name or "").strip()


@frappe.whitelist()
def sign(consent):
	"""Countersign one form."""
	registrar_only()

	signature, name = registrar_mark()
	if not signature:
		frappe.throw(
			_("There is no registrar signature to sign with. Draw one in Registration Settings first.")
		)

	return _stamp(consent, signature, name)


@frappe.whitelist()
def sign_all(academic_term=None, names=None):
	"""Countersign every unsigned form in the queue, or a chosen set of them.

	Returns what it signed and what it could not, rather than stopping at the
	first refusal: a form that cannot be signed is a thing to look at, not a
	reason to leave the other two hundred unsigned.
	"""
	registrar_only()

	signature, name = registrar_mark()
	if not signature:
		frappe.throw(
			_("There is no registrar signature to sign with. Draw one in Registration Settings first.")
		)

	if isinstance(names, str):
		names = frappe.parse_json(names)
	if not names:
		names = [row["name"] for row in forms(academic_term, UNSIGNED)]

	signed, problems = [], []
	for consent in names:
		try:
			# Each on its own savepoint: one refusal should not undo the rest.
			frappe.db.savepoint("sign_form")
			if _stamp(consent, signature, name):
				signed.append(consent)
		except frappe.ValidationError as error:
			frappe.db.rollback(save_point="sign_form")
			problems.append({"consent": consent, "reason": str(error)})

	return {"signed": signed, "problems": problems}


@frappe.whitelist()
def unsign(consent):
	"""Take a signature back off, for the one signed by mistake.

	There is otherwise no way back: the fields are written after submission and
	the form is not editable.
	"""
	registrar_only()

	doc = frappe.get_doc("Registration Consent", consent)
	if not doc.registrar_signed_at:
		return False

	frappe.db.set_value(
		"Registration Consent",
		consent,
		{
			"registrar_signature": None,
			"registrar_name": None,
			"signed_by_registrar": None,
			"registrar_signed_at": None,
		},
	)
	doc.add_comment("Comment", _("Registrar signature removed by {0}.").format(frappe.session.user))
	return True


def _stamp(consent, signature, name):
	"""Write the mark onto one consent. False when it was already signed."""
	doc = frappe.get_doc("Registration Consent", consent)

	if doc.docstatus != 1:
		frappe.throw(
			_("{0} is not a submitted consent, so there is nothing to countersign.").format(consent)
		)
	if doc.registrar_signed_at:
		# Not an error. Signing a queue twice should be quiet about the overlap
		# rather than refusing the whole run.
		return False

	frappe.db.set_value(
		"Registration Consent",
		consent,
		{
			"registrar_signature": signature,
			"registrar_name": name,
			"signed_by_registrar": frappe.session.user,
			"registrar_signed_at": now_datetime(),
		},
	)
	return True
