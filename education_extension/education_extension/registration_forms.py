# Copyright (c) 2026, Asante Solutions and contributors
# For license information, please see license.txt

"""Signing the printed registration forms.

A student signs their consent on the portal; the Proof of Registration prints
that signature, the modules, and a blank rule for the registrar. Countersigning
was the one part still done on paper, a page at a time, after the fact.

So the registrar's mark is drawn once in Registration Settings and stamped onto
each form as it is signed. Stamped, not referenced: the image is read into the
consent along with the name printed beneath it, the same way the declaration
wording is copied, because the record has to keep saying what was on it at the
time. Changing the settings later leaves signed forms alone.

The pad draws a guide line across itself for the signer to write on and saves it
as part of the mark, and the form draws its own rule under every signature — so
the line is taken back off on the way through. See `trim`.

Nothing here alters what the student agreed to. The consent is submitted by then
and these fields are the only ones on it that may be written afterwards.
"""

import base64
import io
import mimetypes

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
	return trim(_as_data(settings.registrar_signature)), (settings.registrar_name or "").strip()


# How much of the width a run has to cover before it is a rule rather than part
# of a signature, and how unbroken it has to be. Handwriting reaches this length
# occasionally; it is never solid along it.
RULE_SHARE = 0.5
RULE_SOLIDITY = 0.98


def trim(data_uri):
	"""The mark without the pad's guide line, cropped to what is left.

	The signature pad draws a line across itself for the signer to write on, and
	saves it as part of the image. The form draws its own rule under every
	signature, so a mark carrying one printed with two — a short one from the
	pad above a long one from the page.

	The pad's line gives itself away by being perfectly solid: on a real example
	it was two rows of 300 pixels across a 300 pixel span, while the most inked
	row of actual handwriting on the same mark was 83% of its own span. So rows
	that are long *and* unbroken come off, and the rest is trimmed to its ink so
	the signature sits on the rule rather than floating above it.

	Anything unreadable is returned untouched. A signature that comes through
	unchanged still prints; one that fails to stamp does not.
	"""
	if not data_uri or not data_uri.startswith("data:image"):
		return data_uri

	try:
		from PIL import Image

		head, encoded = data_uri.split(",", 1)
		image = Image.open(io.BytesIO(base64.b64decode(encoded))).convert("RGBA")
		pixels = image.load()
		width, height = image.size

		for y in range(height):
			run = [x for x in range(width) if _inked(pixels[x, y])]
			if not run:
				continue
			span = run[-1] - run[0] + 1
			if span < width * RULE_SHARE or len(run) < span * RULE_SOLIDITY:
				continue
			for x in range(run[0], run[-1] + 1):
				pixels[x, y] = (255, 255, 255, 0)

		box = image.getbbox()
		if box:
			image = image.crop(box)

		out = io.BytesIO()
		image.save(out, format="PNG")
		return "data:image/png;base64,{0}".format(base64.b64encode(out.getvalue()).decode())
	except Exception:
		frappe.log_error(title="Registrar signature could not be trimmed")
		return data_uri


def _inked(pixel):
	red, green, blue, alpha = pixel
	return alpha > 20 and (red + green + blue) / 3 < 200


def _as_data(file_url):
	"""The uploaded signature as a data URI, ready to be copied onto a record.

	Copied rather than linked. A consent that points at a file is only signed
	for as long as that file is there and unchanged, and this is the record of
	who countersigned a registration — it has to keep the mark that was on it.

	Passed through unchanged when it already is a data URI: the field took a
	drawn signature before it took an uploaded one, and a site set up in that
	window has the mark stored directly.
	"""
	file_url = (file_url or "").strip()
	if not file_url or file_url.startswith("data:"):
		return file_url

	name = frappe.db.get_value("File", {"file_url": file_url}, "name")
	if not name:
		frappe.throw(
			_("The registrar signature file is missing: {0}").format(frappe.bold(file_url))
		)

	# Read as bytes, not through `get_content`: with no encoding given that
	# decodes the file as text, and a PNG put through a text decode and back
	# comes out as a different file — the header alone turns from \x89PNG into
	# three bytes of UTF-8.
	path = frappe.get_doc("File", name).get_full_path()
	try:
		with open(path, "rb") as handle:
			content = handle.read()
	except OSError:
		frappe.throw(
			_("The registrar signature file cannot be read: {0}").format(frappe.bold(file_url))
		)

	kind = mimetypes.guess_type(file_url)[0] or "image/png"
	return "data:{0};base64,{1}".format(kind, base64.b64encode(content).decode())


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
