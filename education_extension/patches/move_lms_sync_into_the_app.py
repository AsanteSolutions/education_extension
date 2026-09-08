"""Retire the LMS Server Scripts in favour of queued jobs in the app.

Creates the service account the jobs run as, then disables the six Server
Scripts they replace. Disabled rather than deleted: they are the record of how
the integration used to behave, and re-enabling one is how you would compare if
a mirror ever looks wrong. Nothing reads a disabled script.

The account holds `Moderator` and nothing else. That is the role
`LMS Enrollment.is_admin` actually checks for, so it is exactly enough to mirror
an enrolment and no more — narrower than the Administrator the synchronous
version had to use.
"""

import frappe

from education_extension.education_extension.lms_sync import SERVICE_ROLE, SERVICE_USER

# The names these scripts have on the site they were written from. Used to
# report on, never to decide by: a script renamed anywhere would be skipped
# silently, stay enabled, and fire inline on before_insert as the student again
# -- which is the exact failure this patch exists to remove, quietly reinstated.
EXPECTED = [
	"Add LMS Program Enrollment From Education Program Enrollment",
	"Remove From LMS Program Enrollment From Education Program Enrollment",
	"Create LMS Course Enrollment From Education Course Enrollment",
	"Delete LMS Program Enrollment From Education Program Enrollment",
	"Create Education Program From LMS Program",
	"LMS to Education Course Linking",
]

# The doctypes the mirroring binds together. A document event script on any of
# these is a candidate whatever it is called.
BOUND_DOCTYPES = ["Program Enrollment", "Course Enrollment", "LMS Program", "LMS Course"]


def execute():
	create_service_user()
	disable_server_scripts()
	frappe.db.commit()


def create_service_user():
	if not frappe.db.exists("Role", SERVICE_ROLE):
		# No LMS on this site, so nothing to mirror into and no role to hold.
		print("LMS sync: no {0} role on this site, service user not created".format(SERVICE_ROLE))
		return

	if not frappe.db.exists("User", SERVICE_USER):
		user = frappe.new_doc("User")
		user.update(
			{
				"email": SERVICE_USER,
				"first_name": "LMS Sync",
				"user_type": "System User",
				"send_welcome_email": 0,
				# No password is ever set, so it cannot be signed in to. It exists
				# only to be the user a background job runs as.
				"enabled": 1,
			}
		)
		user.flags.ignore_permissions = True
		user.insert()
		print("LMS sync: created service user {0}".format(SERVICE_USER))

	user = frappe.get_doc("User", SERVICE_USER)
	if SERVICE_ROLE not in [row.role for row in user.roles]:
		user.append("roles", {"role": SERVICE_ROLE})
		user.flags.ignore_permissions = True
		user.save()
		print("LMS sync: granted {0} to {1}".format(SERVICE_ROLE, SERVICE_USER))


def mirrors_the_lms(script):
	"""Whether a document event script is part of the LMS mirroring.

	Identified by what it is bound to and what it touches rather than by its
	name. Either end counts: a script on an LMS doctype is mirroring by
	definition, and one on an education doctype gives itself away by mentioning
	the LMS in its body.
	"""
	if (script.reference_doctype or "").startswith("LMS "):
		return True
	return "LMS" in (script.script or "")


def disable_server_scripts():
	if not frappe.db.exists("DocType", "Server Script"):
		return

	candidates = frappe.get_all(
		"Server Script",
		filters={
			"script_type": "DocType Event",
			"reference_doctype": ["in", BOUND_DOCTYPES],
		},
		fields=["name", "reference_doctype", "doctype_event", "script", "disabled"],
	)

	disabled = set()
	for script in candidates:
		if not mirrors_the_lms(script):
			continue
		if script.disabled:
			disabled.add(script.name)
			continue
		frappe.db.set_value("Server Script", script.name, "disabled", 1)
		disabled.add(script.name)
		print(
			"LMS sync: disabled Server Script {0} ({1} / {2})".format(
				script.name, script.reference_doctype, script.doctype_event
			)
		)

	# Reported, not acted on. A name that is not here has been renamed or removed,
	# and one that was disabled without being expected is worth a second look.
	for name in EXPECTED:
		if name not in disabled:
			print("LMS sync: expected script not found, check it by hand -- {0}".format(name))
	for name in sorted(disabled - set(EXPECTED)):
		print("LMS sync: also disabled an unlisted mirroring script -- {0}".format(name))

	still_running = [
		script.name
		for script in candidates
		if script.name not in disabled and not script.disabled
	]
	if still_running:
		print(
			"LMS sync: these event scripts are still enabled on the mirrored "
			"doctypes and were left alone: {0}".format(", ".join(still_running))
		)
