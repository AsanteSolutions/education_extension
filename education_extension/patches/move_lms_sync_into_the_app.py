"""Create the service account the LMS sync jobs run as.

The six Server Scripts these jobs replace are disabled by hand, per site.
This patch used to disable them itself; that came out once it had been done on
production, so nothing here writes to Server Script any more. It still looks,
and says what it found: a site running both the scripts and the jobs mirrors
every enrolment twice, and the only sign of it is duplicate LMS members.

The account holds `Moderator` and nothing else. That is the role
`LMS Enrollment.is_admin` actually checks for, so it is exactly enough to mirror
an enrolment and no more -- narrower than the Administrator the synchronous
version had to use.
"""

import frappe

from education_extension.education_extension.lms_sync import SERVICE_ROLE, ensure_service_user

# The doctypes the mirroring binds together. A document event script on any of
# these is a candidate whatever it is called, which is the point: checking by
# name would miss a renamed script and report the site as clean.
BOUND_DOCTYPES = ["Program Enrollment", "Course Enrollment", "LMS Program", "LMS Course"]


def execute():
	create_service_user()
	report_server_scripts()
	frappe.db.commit()


def create_service_user():
	"""Make the account now, and leave it to the migrate hook to keep making it.

	The work itself lives in `lms_sync` and runs on every migrate. It has to:
	this patch can only act on the site as it stands today, and a site that
	installs the LMS tomorrow would otherwise never be asked again -- the account
	would never exist, and `enqueue` would go on declining to queue anything with
	nothing anywhere saying why.
	"""
	if not ensure_service_user():
		print("LMS sync: no {0} role on this site, service user not created".format(SERVICE_ROLE))


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


def report_server_scripts():
	"""Say whether the scripts these jobs replace are still live. Never act.

	Disabling them is a decision taken per site and made by hand. All this can
	usefully do is make sure a site that has not had it done does not look like
	one that has.
	"""
	if not frappe.db.exists("DocType", "Server Script"):
		return

	still_enabled = [
		script
		for script in frappe.get_all(
			"Server Script",
			filters={
				"script_type": "DocType Event",
				"reference_doctype": ["in", BOUND_DOCTYPES],
				"disabled": 0,
			},
			fields=["name", "reference_doctype", "doctype_event", "script"],
		)
		if mirrors_the_lms(script)
	]

	if not still_enabled:
		print("LMS sync: no mirroring Server Scripts are enabled, the jobs are the only path")
		return

	print(
		"LMS sync: {0} mirroring Server Script(s) are still enabled and will now run "
		"alongside the jobs, mirroring twice. Disable them:".format(len(still_enabled))
	)
	for script in still_enabled:
		print(
			"  {0} ({1} / {2})".format(
				script.name, script.reference_doctype, script.doctype_event
			)
		)
