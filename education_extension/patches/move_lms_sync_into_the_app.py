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

# Every Server Script that bound the LMS to the education records.
RETIRED = [
	"Add LMS Program Enrollment From Education Program Enrollment",
	"Remove From LMS Program Enrollment From Education Program Enrollment",
	"Create LMS Course Enrollment From Education Course Enrollment",
	"Delete LMS Program Enrollment From Education Program Enrollment",
	"Create Education Program From LMS Program",
	"LMS to Education Course Linking",
]


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


def disable_server_scripts():
	if not frappe.db.exists("DocType", "Server Script"):
		return

	for name in RETIRED:
		if not frappe.db.exists("Server Script", name):
			continue
		if frappe.db.get_value("Server Script", name, "disabled"):
			continue
		frappe.db.set_value("Server Script", name, "disabled", 1)
		print("LMS sync: disabled Server Script {0}".format(name))
