"""Give every existing student a User Permission for their own record.

New students get one from a hook; this is the backfill for those already here.

Before it runs, a logged-in student can list every other student record and
every assessment result on the site. Role permissions cannot express "only your
own", so nothing short of this closes it.

Idempotent, and it reports what it skipped rather than passing over it quietly:
a student with no portal user cannot be confined, and one whose user holds a
staff role must not be.
"""

import frappe

from education_extension.education_extension.student_permissions import confine


def execute():
	if not frappe.db.exists("DocType", "Student"):
		return

	tally = {}
	staff = []
	for student in frappe.get_all("Student", fields=["name", "user"], order_by="name"):
		outcome = confine(student.name, student.user)
		tally[outcome] = tally.get(outcome, 0) + 1
		if outcome == "staff":
			staff.append("{0} ({1})".format(student.name, student.user))

	frappe.db.commit()

	print(
		"Student records confined: {0} created, {1} already had one, "
		"{2} have no portal user, {3} skipped as staff".format(
			tally.get("created", 0),
			tally.get("already", 0),
			tally.get("no user", 0),
			tally.get("staff", 0),
		)
	)
	for who in staff:
		print("  left unconfined because the account holds a staff role: {0}".format(who))
