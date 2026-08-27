# Copyright (c) 2026, Asante Solutions and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from education_extension.education_extension.doctype.student_progress_report.student_progress_report import (
	NO_ORAL_EXAM,
	NO_PRAC_OR_ORAL_EXAM,
	NO_PRAC_TEST,
)

# The two halves of a final mark. Coursework is what the progress report prints as
# the DP; Examination is the exam portion. Rows are weighted as a share of the
# final mark rather than of their own component, so the whole scheme sums to 100.
COURSEWORK = "Coursework"
EXAMINATION = "Examination"

# Percent weightings are floats, so compare totals with a tolerance rather than
# for equality — a scheme split three ways cannot land on exactly 100.
WEIGHTAGE_TOLERANCE = 0.01


class CourseMarkScheme(Document):
	def validate(self):
		self.validate_criteria()
		self.set_totals()
		self.validate_total_weightage()

	def before_submit(self):
		self.validate_no_other_submitted_scheme()

	def validate_criteria(self):
		"""Each assessment appears once, carries a positive weight, and any
		subminimum is a percentage."""
		seen = set()
		for row in self.criteria:
			if row.assessment_group in seen:
				frappe.throw(
					_("Row {0}: {1} appears more than once in this scheme.").format(
						row.idx, frappe.bold(row.assessment_group)
					)
				)
			seen.add(row.assessment_group)

			if not row.weightage or row.weightage <= 0:
				frappe.throw(
					_("Row {0}: {1} needs a weightage greater than zero.").format(
						row.idx, frappe.bold(row.assessment_group)
					)
				)

			if row.subminimum and not 0 < row.subminimum <= 100:
				frappe.throw(
					_("Row {0}: a subminimum must be between 0 and 100, not {1}.").format(
						row.idx, row.subminimum
					)
				)

	def set_totals(self):
		"""Totals are shown on the form so the split is readable without adding
		the rows up by hand."""
		self.coursework_weightage = sum(
			row.weightage or 0 for row in self.criteria if row.component == COURSEWORK
		)
		self.examination_weightage = sum(
			row.weightage or 0 for row in self.criteria if row.component == EXAMINATION
		)
		self.total_weightage = self.coursework_weightage + self.examination_weightage

	def validate_total_weightage(self):
		if abs((self.total_weightage or 0) - 100) > WEIGHTAGE_TOLERANCE:
			frappe.throw(
				_("The weightings total {0}%, and must total 100%.").format(
					frappe.bold(round(self.total_weightage or 0, 2))
				)
			)

	def validate_no_other_submitted_scheme(self):
		"""One submitted scheme per course and year: the calculation has to be able
		to pick a single breakdown without a tie-break."""
		existing = frappe.get_all(
			"Course Mark Scheme",
			filters={
				"course": self.course,
				"academic_year": self.academic_year,
				"docstatus": 1,
				"name": ["!=", self.name],
			},
			pluck="name",
			limit=1,
		)
		if existing:
			frappe.throw(
				_("{0} already has a submitted mark scheme for {1}: {2}. Cancel it before submitting this one.").format(
					frappe.bold(self.course), frappe.bold(self.academic_year), existing[0]
				)
			)


def get_scheme(course, academic_year):
	"""The submitted scheme for a course in a year, or None if it has none.

	This is the lookup the mark calculation will use once it moves server-side:
	a course with a scheme is marked from it, and a course without one falls back
	to the legacy calculation."""
	name = frappe.get_all(
		"Course Mark Scheme",
		filters={"course": course, "academic_year": academic_year, "docstatus": 1},
		pluck="name",
		limit=1,
	)
	return frappe.get_doc("Course Mark Scheme", name[0]) if name else None


# ---------------------------------------------------------------------------
# Deriving schemes from the marking rules that are currently written in code
# ---------------------------------------------------------------------------

# Weightings as a share of the final mark. Coursework is worth 50 and the exam
# sittings the other 50; where a course has a practical test it takes half the
# coursework, and the written tests and assignments halve to make room for it.
COURSEWORK_WITH_PRACTICAL_TEST = [
	("Test 1", 7.5),
	("Test 2", 7.5),
	("Assignment 1", 5),
	("Assignment 2", 5),
	("Practical Test", 25),
]
COURSEWORK_WITHOUT_PRACTICAL_TEST = [
	("Test 1", 15),
	("Test 2", 15),
	("Assignment 1", 10),
	("Assignment 2", 10),
]

# Exam papers. A course examined on theory alone puts the whole exam portion on
# that paper; without an oral, the practical absorbs the oral's share.
EXAM_THEORY_ONLY = [("Theory Exam", 50)]
EXAM_WITHOUT_ORAL = [("Theory Exam", 20), ("Practical Exam", 30)]
EXAM_FULL = [("Theory Exam", 20), ("Practical Exam", 25), ("Oral Exam", 5)]


def _matches(course, codes):
	"""Course names are "CODE - Course Name", and the rule sets hold bare codes."""
	return any(code in course for code in codes)


def legacy_criteria_for_course(course):
	"""The scheme rows equivalent to how this course is marked today, as
	(assessment group, component, weightage).

	Pure: takes the course name and returns rows, so the derivation can be checked
	without a site. The rule sets come from the progress report rather than a
	second copy of them."""
	if _matches(course, NO_PRAC_TEST):
		coursework = COURSEWORK_WITHOUT_PRACTICAL_TEST
	else:
		coursework = COURSEWORK_WITH_PRACTICAL_TEST

	if _matches(course, NO_PRAC_OR_ORAL_EXAM):
		exams = EXAM_THEORY_ONLY
	elif _matches(course, NO_ORAL_EXAM):
		exams = EXAM_WITHOUT_ORAL
	else:
		exams = EXAM_FULL

	return [(group, COURSEWORK, weightage) for group, weightage in coursework] + [
		(group, EXAMINATION, weightage) for group, weightage in exams
	]


@frappe.whitelist()
def generate_legacy_schemes(academic_year, courses=None, submit=False):
	"""Create a draft Course Mark Scheme for each course, matching how it is
	marked today.

	Transcription, not judgement: the weightings come from the rules already in
	code. Re-runnable — a course that already has a scheme for the year is left
	alone. Returns what it created, skipped, and could not build.
	"""
	frappe.only_for(("Academics User", "Education Manager", "System Manager"))

	if isinstance(courses, str):
		courses = frappe.parse_json(courses)
	if not courses:
		courses = frappe.get_all("Course", pluck="name")

	created, skipped, problems = [], [], []

	for course in courses:
		if frappe.db.exists(
			"Course Mark Scheme",
			{"course": course, "academic_year": academic_year, "docstatus": ["<", 2]},
		):
			skipped.append(course)
			continue

		rows = legacy_criteria_for_course(course)
		missing = [
			group
			for group, _component, _weightage in rows
			if not frappe.db.exists("Assessment Group", group)
		]
		if missing:
			problems.append({"course": course, "missing_assessment_groups": missing})
			continue

		scheme = frappe.get_doc(
			{
				"doctype": "Course Mark Scheme",
				"course": course,
				"academic_year": academic_year,
				"criteria": [
					{
						"assessment_group": group,
						"component": component,
						"weightage": weightage,
					}
					for group, component, weightage in rows
				],
			}
		)
		scheme.insert()
		if submit:
			scheme.submit()
		created.append(scheme.name)

	return {"created": created, "skipped": skipped, "problems": problems}


@frappe.whitelist()
def copy_to_academic_year(name, academic_year):
	"""Copy a scheme into another year as a draft, so a new year starts from the
	last one rather than from an empty table."""
	source = frappe.get_doc("Course Mark Scheme", name)

	if frappe.db.exists(
		"Course Mark Scheme",
		{"course": source.course, "academic_year": academic_year, "docstatus": ["<", 2]},
	):
		frappe.throw(
			_("{0} already has a mark scheme for {1}.").format(
				frappe.bold(source.course), frappe.bold(academic_year)
			)
		)

	copy = frappe.copy_doc(source)
	copy.academic_year = academic_year
	copy.amended_from = None
	copy.insert()
	return copy.name
