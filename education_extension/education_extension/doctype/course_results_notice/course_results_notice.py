# Copyright (c) 2026, Asante Solutions and contributors
# For license information, please see license.txt

"""Why a module's results are not out, in the words a student should read.

The Grades page can work out *which* of a student's modules have no marks — it
is the difference between what they registered for and what they have results
in. It cannot work out *why*, and the reasons differ: still being marked, the
lecturer is away, the paper is under review. Somebody in the academic office
knows, and until this there was nowhere for them to write it down.

So it was written into the page instead, as a sentence naming one module, shown
to every student on every term and true only until somebody remembered to take
it out. This is that sentence with an owner and an expiry.

The expiry is structural rather than a date: a notice is only ever shown to a
student who has no results for the module, so it stops appearing of its own
accord the moment their marks land. Forgetting to delete one costs nothing.
"""

import frappe
from frappe import _
from frappe.model.document import Document


class CourseResultsNotice(Document):
	def validate(self):
		self.validate_only_one_per_module_and_term()

	def validate_only_one_per_module_and_term(self):
		"""Two live notices for one module would both be shown, and a student
		reading two reasons for one absence has been told nothing."""
		if self.disabled:
			return

		existing = frappe.db.exists(
			"Course Results Notice",
			{
				"course": self.course,
				"academic_term": self.academic_term,
				"disabled": 0,
				"name": ["!=", self.name or ""],
			},
		)
		if existing:
			frappe.throw(
				_("{0} already has a notice for {1}: {2}.").format(
					frappe.bold(self.course),
					self.academic_term,
					frappe.utils.get_link_to_form("Course Results Notice", existing),
				)
			)


def notices_for(academic_term, courses):
	"""course -> what students are told about it, for the modules asked about.

	Only the live ones, and only the modules handed in — the caller has already
	worked out which of this student's modules have nothing recorded, and a
	notice for anything else is not this student's business.
	"""
	if not (academic_term and courses):
		return {}

	return {
		row.course: row.reason
		for row in frappe.get_all(
			"Course Results Notice",
			filters={
				"academic_term": academic_term,
				"course": ["in", list(courses)],
				"disabled": 0,
			},
			fields=["course", "reason"],
		)
	}
