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
from frappe import _

from education_extension.education_extension.doctype.course_mark_scheme.course_mark_scheme import (
	COURSEWORK,
	get_scheme,
)
from education_extension.education_extension.doctype.student_progress_report.student_progress_report import (
	ISSUE_DATE_STANDARD,
	ISSUE_DATE_SUPPLEMENTARY,
	SUPP_GROUP,
	calculate_final_results,
	calculate_final_results_detailed,
	get_results,
	round_half_up,
)

# Which sitting a mark comes from. Carried on the mark itself rather than read
# out of the assessment group's name.
MAIN = "Main"
SUPPLEMENTARY = "Supplementary"
AEGROTAT = "Aegrotat"

# The naming convention the sitting field replaced: an aegrotat paper was the
# normal group prefixed with AEGRO. Still read, because a mark can be recorded
# against one of those groups through the standard Assessment Result form, where
# nothing prompts for the sitting.
AEGROTAT_PREFIX = re.compile(r"^AEGRO(?:TAT)?[\s_-]*", re.IGNORECASE)


def sitting_of(result):
	"""What a mark counts towards, as (assessment, sitting).

	The sitting comes from the mark. Where it says Main but the assessment group
	is named the old way, the name is believed instead — otherwise an aegrotat
	paper entered on the standard form would quietly count as nothing.
	"""
	group = (result.get("assessment_group") or "").strip()
	sitting = result.get("sitting") or MAIN

	if sitting == MAIN:
		if AEGROTAT_PREFIX.match(group):
			return AEGROTAT_PREFIX.sub("", group, count=1), AEGROTAT
		if group == SUPP_GROUP:
			return group, SUPPLEMENTARY
	elif sitting == AEGROTAT:
		# An aegrotat mark that still carries the old name stands in for the
		# assessment the name points at.
		group = AEGROTAT_PREFIX.sub("", group, count=1)

	return group, sitting


def resolve_results(results):
	"""One result per assessment, keyed by group.

	The supplementary exam is reported on its own and takes no part in the mark.
	An aegrotat sitting displaces the main one for the same assessment, in either
	order, because the student sat it in place of the original. Among results of
	the same kind the first is kept.
	"""
	resolved = {}

	for result in results:
		group, sitting = sitting_of(result)
		if sitting == SUPPLEMENTARY:
			continue

		is_aegrotat = sitting == AEGROTAT
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


def get_assessment_results(student, academic_term):
	"""Every mark for a student in a term, grouped by course.

	A course with an approved Course Mark Sheet is read from that sheet, which is
	the record for the marks it carries. Everything else comes from Assessment
	Result, so a term captured before the sheets existed still reads correctly.
	"""
	results = frappe.get_all(
		"Assessment Result",
		fields=[
			"course",
			"assessment_group",
			"custom_sitting as sitting",
			"total_score",
			"maximum_score",
		],
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

	# The sheet wins for its own course, wholesale rather than row by row: half a
	# course's marks from one source and half from another would be nobody's
	# answer.
	by_course.update(get_sheet_marks(student, academic_term))
	return by_course


def get_sheet_marks(student, academic_term):
	"""A student's marks from approved Course Mark Sheets, grouped by course.

	Moderation is applied here rather than by the reader: a moderated sheet
	reports the moderated score, and the raw one stays on the sheet untouched.
	"""
	rows = frappe.db.sql(
		"""
		select sheet.course, entry.assessment_group, entry.raw_score, entry.moderated_score,
		       entry.maximum_score, sheet.moderation_method, sheet.sitting
		from `tabCourse Mark Sheet Entry` entry
		join `tabCourse Mark Sheet` sheet on sheet.name = entry.parent
		where sheet.docstatus = 1
		  and sheet.academic_term = %(academic_term)s
		  and entry.student = %(student)s
		  and entry.status = 'Marked'
		""",
		{"student": student, "academic_term": academic_term},
		as_dict=True,
	)

	by_course = {}
	for row in rows:
		moderated = row.moderation_method in ("Linear Scale", "Flat Adjustment")
		by_course.setdefault(row.course, []).append(
			{
				"course": row.course,
				"assessment_group": row.assessment_group,
				"sitting": row.sitting,
				"total_score": row.moderated_score if moderated else row.raw_score,
				"maximum_score": row.maximum_score or 100,
			}
		)
	return by_course


def get_course_marks(student, academic_year, academic_term):
	"""Every scheme-marked course for a student in a term, keyed by course.

	Courses whose scheme is missing are absent from the result entirely — the
	caller decides what to do about them, which during the changeover means
	falling back to the legacy calculation.
	"""
	marks = {}
	for course, course_results in get_assessment_results(student, academic_term).items():
		scheme = get_scheme(course, academic_year)
		if not scheme:
			continue
		marks[course] = calculate_course_mark(scheme.criteria, course_results)
		marks[course]["scheme"] = scheme.name

	return marks


def student_marks(student, academic_year, academic_term):
	"""The DP and final mark for every course a student has results in.

	The one entry point both the portal and the printed report read. A course
	with a submitted Course Mark Scheme is marked from it; a course without one
	falls back to the calculation whose weightings are written into
	student_progress_report, so a term converts on its own without a mode to set
	anywhere.

	Each course reports `scheme` — the scheme that produced the mark, or None
	where the legacy calculation did.
	"""
	by_course = get_assessment_results(student, academic_term)

	marks = {}
	legacy_results = []

	for course, course_results in by_course.items():
		scheme = get_scheme(course, academic_year)
		if scheme:
			computed = calculate_course_mark(scheme.criteria, course_results)
			computed["scheme"] = scheme.name
			marks[course] = computed
		else:
			legacy_results.extend(course_results)

	if legacy_results:
		for course, computed in calculate_final_results_detailed(legacy_results).items():
			computed["scheme"] = None
			computed.setdefault("missing", [])
			computed.setdefault("failed_subminima", [])
			computed.setdefault("unscheduled", [])
			marks[course] = computed

	return marks


# The comments QA can put against a result. A fixed list rather than free text:
# they are read off the printed report's legend, and a typo makes one invisible.
REMARK_CODES = [
	"P",
	"PD",
	"C",
	"F",
	"FSUB",
	"NSM",
	"DISC",
	"SUPP",
	"AEGRO",
	"PS",
	"FS",
	"PSE",
	"FSE",
]


@frappe.whitelist()
def get_remark_codes():
	"""So the QA view offers the same list the report legend explains."""
	return REMARK_CODES


def get_course_results(course, academic_term):
	"""Every student's marks for one course in a term, grouped by student.

	The by-course counterpart of get_assessment_results, and it resolves the same
	way: an approved Course Mark Sheet is the record for the course it covers, and
	Assessment Result answers for everything else.
	"""
	results = frappe.get_all(
		"Assessment Result",
		fields=[
			"student",
			"assessment_group",
			"custom_sitting as sitting",
			"total_score",
			"maximum_score",
		],
		filters={"course": course, "academic_term": academic_term, "docstatus": 1},
		limit_page_length=0,
	)

	by_student = {}
	for result in results:
		row = dict(result)
		row["course"] = course
		by_student.setdefault(result.student, []).append(row)

	sheet_rows = frappe.db.sql(
		"""
		select entry.student, entry.assessment_group, entry.raw_score, entry.moderated_score,
		       entry.maximum_score, sheet.moderation_method, sheet.sitting
		from `tabCourse Mark Sheet Entry` entry
		join `tabCourse Mark Sheet` sheet on sheet.name = entry.parent
		where sheet.docstatus = 1
		  and sheet.course = %(course)s
		  and sheet.academic_term = %(academic_term)s
		  and entry.status = 'Marked'
		""",
		{"course": course, "academic_term": academic_term},
		as_dict=True,
	)

	# Wholesale per student, for the same reason the by-student version does it:
	# half a course's marks from each source would be nobody's answer.
	from_sheet = {}
	for row in sheet_rows:
		moderated = row.moderation_method in ("Linear Scale", "Flat Adjustment")
		from_sheet.setdefault(row.student, []).append(
			{
				"course": course,
				"assessment_group": row.assessment_group,
				"sitting": row.sitting,
				"total_score": row.moderated_score if moderated else row.raw_score,
				"maximum_score": row.maximum_score or 100,
			}
		)
	by_student.update(from_sheet)
	return by_student


def course_marks(course, academic_year, academic_term):
	"""One row per student for a whole course, as a QA reviewer needs to read it.

	Returns the scheme's assessments in the order the scheme lists them, so the
	columns follow the course rather than a fixed set, and a row per student
	carrying each score, the semester mark, the final mark, the supplementary
	mark and the stored comments.
	"""
	from education_extension.education_extension.doctype.course_mark_scheme.course_mark_scheme import (
		get_scheme,
	)
	from education_extension.education_extension.doctype.marking_settings.marking_settings import (
		order_students,
	)

	scheme = get_scheme(course, academic_year)
	criteria = list(scheme.criteria) if scheme else []
	by_student = get_course_results(course, academic_term)

	comments = _course_remarks(course, academic_term, "Academic Remark", "remark")
	supp_comments = _course_remarks(
		course, academic_term, "Supplementary Academic Remark", "supp_remark"
	)
	names = _student_names(by_student)

	rows = []
	for student in order_students(list(by_student)):
		results = by_student[student]
		resolved = resolve_results(results)
		by_name = {group.casefold(): group for group in resolved}

		scores = {}
		for row in criteria:
			group = row.assessment_group
			matched = by_name.get(group.casefold())
			ratio = score_ratio(resolved[matched]) if matched else None
			scores[group] = round_half_up(ratio * 100) if ratio is not None else "-"

		computed = (
			calculate_course_mark(criteria, results)
			if criteria
			else calculate_final_results_detailed(results).get(course)
		)
		complete = computed and computed["dp_complete"] and computed["exams_complete"]
		supplementary = _supplementary_for(results)

		rows.append(
			{
				"student": student,
				"student_name": names.get(student, student),
				"scores": scores,
				"dp": round_half_up(computed["dp"]) if computed and computed["dp_complete"] else "-",
				"final_mark": round_half_up(computed["final_mark"]) if complete else "-",
				"supplementary": supplementary,
				"remark": comments.get(student, ""),
				"supp_remark": supp_comments.get(student, ""),
				"missing": computed["missing"] if computed else [],
				"failed_subminima": (computed or {}).get("failed_subminima") or [],
			}
		)

	return {"criteria": criteria, "rows": rows, "scheme": scheme.name if scheme else None}


def _supplementary_for(results):
	"""The supplementary mark among a student's results, as a percentage."""
	for result in results:
		_group, sitting = sitting_of(result)
		if sitting != SUPPLEMENTARY:
			continue
		ratio = score_ratio(result)
		if ratio is not None:
			return round_half_up(ratio * 100)
	return "-"


def _course_remarks(course, academic_term, doctype, fieldname):
	rows = frappe.get_all(
		doctype,
		fields=["student", fieldname],
		filters={"course": course, "academic_term": academic_term, "docstatus": 1},
		limit_page_length=0,
	)
	return {row.student: row.get(fieldname) for row in rows if row.get(fieldname)}


def _student_names(by_student):
	"""Surname first, the way a mark sheet is read. Built from the name fields
	rather than by splitting the full name, which guesses wrong on a double
	surname."""
	names = {}
	for row in frappe.get_all(
		"Student",
		fields=["name", "student_name", "first_name", "last_name"],
		filters={"name": ["in", list(by_student)]},
		limit_page_length=0,
	):
		if row.last_name and row.first_name:
			names[row.name] = f"{row.last_name}, {row.first_name}"
		else:
			names[row.name] = row.student_name or row.name
	return names


def final_marks(student, academic_year, academic_term):
	"""Final mark per course in the form the printed report shows it: a whole
	percentage, or a dash while the marks are incomplete."""
	return {
		course: format_mark(marks["final_mark"], marks["dp_complete"] and marks["exams_complete"])
		for course, marks in student_marks(student, academic_year, academic_term).items()
	}


@frappe.whitelist()
def get_student_grades(academic_year, academic_term):
	"""The grades table for the logged-in student, ready to render.

	The portal used to fetch raw results and work the marks out in the browser,
	which meant the weightings existed a second time in JavaScript. It now asks
	for the finished rows, so there is one calculation and a student cannot see a
	mark the server did not produce.

	The student is taken from the session, never from the caller.
	"""
	from education_extension.education_extension.api import _current_user_student
	from education_extension.education_extension.doctype.progress_report_issue_date.progress_report_issue_date import (
		is_released,
	)

	student = _current_user_student()
	if not student:
		return _nothing_to_show(False, _("Your student details could not be loaded."))

	# Approved is not the same as published. Marks wait here until the term's
	# release moment, however far through checking and approval they are.
	if not is_released(academic_year, academic_term, ISSUE_DATE_STANDARD):
		return _nothing_to_show(
			False, _("Results for {0} have not been published yet.").format(academic_term)
		)

	marks = student_marks(student, academic_year, academic_term)
	comments = _remarks(student, academic_term, "Academic Remark", "remark")

	# The supplementary sitting is released on its own date, so a student can be
	# looking at their main marks while the supplementary ones are still held.
	if is_released(academic_year, academic_term, ISSUE_DATE_SUPPLEMENTARY):
		supplementary = _supplementary_marks(student, academic_term)
		supplementary_comments = _remarks(
			student, academic_term, "Supplementary Academic Remark", "supp_remark"
		)
	else:
		supplementary, supplementary_comments = {}, {}

	rows = []
	for course in sorted(marks):
		computed = marks[course]
		complete = computed["dp_complete"] and computed["exams_complete"]
		rows.append(
			{
				# The table keys rows by id; a course appears once per term.
				"id": course,
				"course": course,
				"dp": f"{round_half_up(computed['dp'])}%" if computed["dp_complete"] else "-",
				"final_mark": f"{round_half_up(computed['final_mark'])}%" if complete else "-",
				"remark": comments.get(course, "-"),
				"supp_exam": supplementary.get(course, "-"),
				"supp_remark": supplementary_comments.get(course, "-"),
			}
		)

	return {
		"rows": rows,
		# The supplementary columns only appear when the student has something in
		# them, which most do not.
		"has_supplementary": bool(supplementary or supplementary_comments),
		"released": True,
		"message": None,
	}


def _nothing_to_show(released, message):
	"""An empty table with the reason attached, so the portal can say why rather
	than implying the student has no marks."""
	return {"rows": [], "has_supplementary": False, "released": released, "message": message}


def _supplementary_marks(student, academic_term):
	"""The supplementary exam mark per course, as a percentage. Reported on its
	own and never folded into the final mark."""
	rows = frappe.get_all(
		"Assessment Result",
		fields=["course", "assessment_group", "custom_sitting as sitting", "total_score", "maximum_score"],
		filters={"student": student, "academic_term": academic_term, "docstatus": 1},
		# Either the sitting says so, or the group is named the way it was said
		# before the sitting existed.
		or_filters={"custom_sitting": SUPPLEMENTARY, "assessment_group": SUPP_GROUP},
		limit_page_length=0,
	)

	marks = {}
	for row in rows:
		ratio = score_ratio(dict(row))
		if ratio is not None:
			marks[row.course] = f"{round_half_up(ratio * 100)}%"
	return marks


def _remarks(student, academic_term, doctype, fieldname):
	"""Stored comments per course. Never derived from the mark — a course with
	no comment on file shows nothing."""
	rows = frappe.get_all(
		doctype,
		fields=["course", fieldname],
		filters={"student": student, "academic_term": academic_term, "docstatus": 1},
		limit_page_length=0,
	)
	return {row.course: row.get(fieldname) for row in rows if row.get(fieldname)}


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
