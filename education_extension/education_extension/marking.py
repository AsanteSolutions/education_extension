# Copyright (c) 2026, Asante Solutions and contributors
# For license information, please see license.txt

"""Mark calculation driven by a course's Course Mark Scheme.

The one place a final mark is worked out. It replaces the weightings written into
`marks.js` and `calculate_final_results`, which is why it also carries the tools
to prove it agrees with them: nothing should point at this until
`compare_with_legacy` comes back clean for a real term.

A course with no submitted scheme is not computed here at all — callers fall back
to the legacy calculation, which is what lets a term convert on its own.
"""

import re

import frappe

from education_extension.education_extension.doctype.course_mark_scheme.course_mark_scheme import (
	COURSEWORK,
	EXAMINATION,
	get_scheme,
)
from education_extension.education_extension.doctype.student_progress_report.student_progress_report import (
	SUPP_GROUP,
	calculate_final_results,
	get_results,
	round_half_up,
)

# An aegrotat sitting is the normal assessment group prefixed with AEGRO, e.g.
# "AEGRO Theory Exam". Same pattern the portal uses, tolerating the AEGROTAT
# spelling and a missing separator.
AEGROTAT_PREFIX = re.compile(r"^AEGRO(?:TAT)?[\s_-]*", re.IGNORECASE)


def sitting_of(assessment_group):
	"""The assessment a result belongs to, as (group, is_aegrotat). An aegrotat
	paper stands in for the sitting it prefixes, so both resolve to one group."""
	group = (assessment_group or "").strip()
	if AEGROTAT_PREFIX.match(group):
		return AEGROTAT_PREFIX.sub("", group, count=1), True
	return group, False


def resolve_results(results):
	"""One result per assessment, keyed by group.

	The supplementary exam is reported on its own and takes no part in the mark.
	An aegrotat sitting displaces the main one for the same assessment, in either
	order, because the student sat it in place of the original. Among results of
	the same kind the first is kept.
	"""
	resolved = {}

	for result in results:
		if result.get("assessment_group") == SUPP_GROUP:
			continue

		group, is_aegrotat = sitting_of(result.get("assessment_group"))
		kept = resolved.get(group)
		if kept and not (is_aegrotat and not kept["is_aegrotat"]):
			continue
		resolved[group] = {"result": result, "is_aegrotat": is_aegrotat}

	return {group: kept["result"] for group, kept in resolved.items()}


def score_ratio(result):
	"""A result's score as a fraction of its maximum, or None when unmarked."""
	score = result.get("total_score")
	maximum = result.get("maximum_score")
	if score is None or not maximum:
		return None
	return float(score) / float(maximum)


def calculate_course_mark(criteria, results):
	"""The DP and final mark for one course, from its scheme and its results.

	`criteria` is the scheme's rows — anything with assessment_group, component,
	weightage, subminimum and is_required. `results` is that course's Assessment
	Results as dicts.

	Pure, so it can be checked without a site. Returns raw numbers plus the
	completeness flags; formatting and the decision to show a dash belong to the
	caller. `final_mark` is only meaningful once both flags are true.
	"""
	resolved = resolve_results(results)
	# Matched without regard to case, so a group recorded as "theory exam" still
	# counts towards a scheme row named "Theory Exam" rather than going missing.
	by_name = {group.casefold(): group for group in resolved}
	matched = set()

	coursework_weightage = sum(_weightage(row) for row in criteria if _component(row) == COURSEWORK)
	coursework_earned = 0.0
	examination_earned = 0.0
	missing = []
	failed_subminima = []
	unmarked = []

	for row in criteria:
		group = _field(row, "assessment_group")
		key = by_name.get((group or "").casefold())
		if key:
			matched.add(key)
		result = resolved.get(key) if key else None
		ratio = score_ratio(result) if result else None

		if ratio is None:
			if result is not None:
				unmarked.append(group)
			if _field(row, "is_required", default=1):
				missing.append(group)
			continue

		contribution = ratio * _weightage(row)
		if _component(row) == COURSEWORK:
			coursework_earned += contribution
		else:
			examination_earned += contribution

		subminimum = _field(row, "subminimum")
		if subminimum and ratio * 100 < float(subminimum):
			failed_subminima.append(group)

	# The DP is printed out of 100 rather than as its share of the final mark.
	dp = (coursework_earned / coursework_weightage * 100) if coursework_weightage else 0.0

	missing_coursework = [
		_field(row, "assessment_group")
		for row in criteria
		if _component(row) == COURSEWORK and _field(row, "assessment_group") in missing
	]
	missing_examination = [group for group in missing if group not in missing_coursework]

	return {
		"dp": dp,
		"final_mark": coursework_earned + examination_earned,
		"dp_complete": not missing_coursework,
		"exams_complete": not missing_examination,
		"missing": missing,
		"unmarked": unmarked,
		"failed_subminima": failed_subminima,
		# Groups the student has a mark for that the scheme does not weight. They
		# contribute nothing, and are surfaced rather than silently dropped.
		"unscheduled": sorted(set(resolved) - matched),
	}


def _field(row, name, default=None):
	"""Scheme rows arrive either as child documents or as plain dicts."""
	value = row.get(name) if isinstance(row, dict) else getattr(row, name, None)
	return default if value is None else value


def _component(row):
	return _field(row, "component", default=COURSEWORK)


def _weightage(row):
	return float(_field(row, "weightage", default=0) or 0)


def get_course_marks(student, academic_year, academic_term):
	"""Every scheme-marked course for a student in a term, keyed by course.

	Courses whose scheme is missing are absent from the result entirely — the
	caller decides what to do about them, which during the changeover means
	falling back to the legacy calculation.
	"""
	results = frappe.get_all(
		"Assessment Result",
		fields=["course", "assessment_group", "total_score", "maximum_score"],
		filters={
			"student": student,
			"academic_term": academic_term,
			"docstatus": 1,
		},
		limit_page_length=0,
	)

	by_course = {}
	for result in results:
		by_course.setdefault(result.course, []).append(dict(result))

	marks = {}
	for course, course_results in by_course.items():
		scheme = get_scheme(course, academic_year)
		if not scheme:
			continue
		marks[course] = calculate_course_mark(scheme.criteria, course_results)
		marks[course]["scheme"] = scheme.name

	return marks


def format_mark(mark, complete):
	"""The report's convention: a whole percentage, or a dash when incomplete."""
	return round_half_up(mark) if complete else "-"


# ---------------------------------------------------------------------------
# Proving the new calculation against the old one
# ---------------------------------------------------------------------------


@frappe.whitelist()
def compare_with_legacy(academic_year, academic_term, students=None):
	"""Run both calculations over a whole term and report every disagreement.

	Read-only. This is the gate for step 3: until it comes back with no
	disagreements for a real term, nothing should be pointed at the scheme.

	    bench --site <site> execute \\
	        education_extension.education_extension.marking.compare_with_legacy \\
	        --kwargs "{'academic_year': '2026-2027', 'academic_term': '2026-2027 (Semester 1)'}"
	"""
	frappe.only_for(("Academics User", "Education Manager", "System Manager"))

	if isinstance(students, str):
		students = frappe.parse_json(students)
	if not students:
		students = frappe.get_all(
			"Assessment Result",
			filters={"academic_term": academic_term, "docstatus": 1},
			distinct=True,
			pluck="student",
			limit_page_length=0,
		)

	report = {
		"academic_year": academic_year,
		"academic_term": academic_term,
		"students": len(students),
		"compared": 0,
		"agreed": 0,
		"disagreements": [],
		"courses_without_a_scheme": set(),
		"notes": [],
	}

	non_percentage_courses = set()

	for student in students:
		doc = frappe._dict(
			{"student": student, "academic_year": academic_year, "academic_term": academic_term}
		)
		legacy_marks = calculate_final_results(get_results(doc))
		scheme_marks = get_course_marks(student, academic_year, academic_term)

		for course, legacy in legacy_marks.items():
			computed = scheme_marks.get(course)
			if not computed:
				report["courses_without_a_scheme"].add(course)
				continue

			scheme_mark = format_mark(
				computed["final_mark"], computed["dp_complete"] and computed["exams_complete"]
			)
			report["compared"] += 1

			if scheme_mark == legacy:
				report["agreed"] += 1
			else:
				report["disagreements"].append(
					{
						"student": student,
						"course": course,
						"legacy": legacy,
						"scheme": scheme_mark,
						"missing": computed["missing"],
						"unscheduled": computed["unscheduled"],
					}
				)

	# The legacy calculation reads a score as a percentage outright; this one
	# divides by the assessment's maximum. They only agree where that maximum is
	# 100, so anywhere it is not is worth seeing before reading the disagreements.
	for row in frappe.get_all(
		"Assessment Result",
		fields=["course", "maximum_score"],
		filters={"academic_term": academic_term, "docstatus": 1},
		limit_page_length=0,
	):
		if row.maximum_score and float(row.maximum_score) != 100:
			non_percentage_courses.add(row.course)

	if non_percentage_courses:
		report["notes"].append(
			"These courses have results marked out of something other than 100, which the "
			"legacy calculation ignores: " + ", ".join(sorted(non_percentage_courses))
		)

	report["courses_without_a_scheme"] = sorted(report["courses_without_a_scheme"])
	if report["courses_without_a_scheme"]:
		report["notes"].append(
			"{0} course(s) have no submitted scheme for {1} and were not compared. Run "
			"generate_legacy_schemes for that year first.".format(
				len(report["courses_without_a_scheme"]), academic_year
			)
		)

	report["clean"] = report["compared"] > 0 and not report["disagreements"]
	return report
