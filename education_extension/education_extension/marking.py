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

# What a mark that cannot be worked out yet is shown as. A dash rather than a
# zero, which would read as a mark of nought.
NO_MARK = "-"


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


# The lists calculate_course_mark reports and the legacy calculation does not.
# It answered a narrower question -- the printed report only ever needed the two
# marks and their completeness flags.
LEGACY_EMPTY_KEYS = ("missing", "unmarked", "failed_subminima", "unscheduled")


def legacy_course_marks(results):
	"""The legacy calculation, in the shape `calculate_course_mark` returns.

	Two differences are reconciled here rather than at each call site, because
	the call sites had started reconciling them one at a time and disagreeing:
	`student_marks` widened the result and `review_rows` did not, so the Course
	Results report died on any course the fallback was there to serve.

	The weightings read every score as a percentage outright, so a mark out of
	anything other than 100 is restated before it is handed over. The missing
	keys are added empty, since an absent key reads as a crash rather than as
	nothing to report.
	"""
	computed = calculate_final_results_detailed([_out_of_a_hundred(row) for row in results])

	for marks in computed.values():
		marks["scheme"] = None
		for key in LEGACY_EMPTY_KEYS:
			marks.setdefault(key, [])

	return computed


def _out_of_a_hundred(result):
	"""A result with its score restated out of 100.

	The scheme calculation divides by the mark's own maximum; the legacy one
	assumes every mark is already a percentage. A test marked 45 out of 50 is 90,
	and was reaching the legacy weightings as 45.
	"""
	ratio = score_ratio(result)
	if ratio is None:
		return result

	return dict(result, total_score=ratio * 100, maximum_score=100)


def get_assessment_results(student, academic_term):
	"""Every mark for a student in a term, grouped by course.

	An approved Course Mark Sheet is the record for the marks it carries, which
	means one course and one sitting. Everything else comes from Assessment
	Result, so a term captured before the sheets existed still reads correctly,
	and a course marked that way keeps its main marks once a supplementary sheet
	is approved alongside them.
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

	return _merge_sheet_marks(by_course, get_sheet_marks(student, academic_term))


def _merge_sheet_marks(stored, from_sheet):
	"""Let each sheet replace the sittings it covers, and only those.

	A sheet is the record for the marks it carries, but it carries one sitting.
	Replacing a course's marks wholesale would let a supplementary sheet answer
	for the main sitting it says nothing about, and the main marks would vanish
	-- a term marked through Assessment Result would lose its DP and final mark
	the moment one supplementary sheet was approved.

	Keyed by course or by student depending on the caller; either way a key's
	rows all belong to one course, which is what makes the sitting the only thing
	that has to be told apart.
	"""
	for key, sheet_rows in from_sheet.items():
		covered = {sitting_of(row)[1] for row in sheet_rows}
		kept = [row for row in stored.get(key, []) if sitting_of(row)[1] not in covered]
		stored[key] = kept + sheet_rows

	return stored


# A missed coursework assessment scores nothing, because there is no re-sitting
# for one — only exams are sat again. A missed exam is left out entirely, so the
# course stays incomplete until an aegrotat paper answers for it.
COURSEWORK_COMPONENT = "Coursework"


def _sheet_mark_rows(condition, params):
	"""Marks from approved Course Mark Sheets, with absences resolved.

	The component comes from the scheme the sheet was stamped with, because
	whether an absence scores zero or leaves a hole depends on which half of the
	mark the assessment belongs to.
	"""
	return frappe.db.sql(
		"""
		select entry.student, sheet.course, entry.assessment_group, entry.status,
		       entry.raw_score, entry.moderated_score, entry.maximum_score,
		       sheet.moderation_method, sheet.sitting, criterion.component
		from `tabCourse Mark Sheet Entry` entry
		join `tabCourse Mark Sheet` sheet on sheet.name = entry.parent
		left join `tabCourse Mark Scheme Criterion` criterion
		       on criterion.parent = sheet.mark_scheme
		      and criterion.assessment_group = entry.assessment_group
		where sheet.docstatus = 1
		  and entry.status in ('Marked', 'Absent')
		  and {condition}
		""".format(condition=condition),
		params,
		as_dict=True,
	)


def _sheet_mark(row):
	"""The score a sheet row contributes, or None where it contributes nothing."""
	if row.status == "Marked":
		moderated = row.moderation_method in ("Linear Scale", "Flat Adjustment")
		return row.moderated_score if moderated else row.raw_score
	return 0 if row.component == COURSEWORK_COMPONENT else None


def get_sheet_marks(student, academic_term):
	"""A student's marks from approved Course Mark Sheets, grouped by course.

	Moderation is applied here rather than by the reader: a moderated sheet
	reports the moderated score, and the raw one stays on the sheet untouched.
	"""
	by_course = {}
	for row in _sheet_mark_rows(
		"sheet.academic_term = %(academic_term)s and entry.student = %(student)s",
		{"student": student, "academic_term": academic_term},
	):
		score = _sheet_mark(row)
		if score is None:
			continue
		by_course.setdefault(row.course, []).append(
			{
				"course": row.course,
				"assessment_group": row.assessment_group,
				"sitting": row.sitting,
				"total_score": score,
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


def student_marks(student, academic_year, academic_term, by_course=None):
	"""The DP and final mark for every course a student has results in.

	The one entry point both the portal and the printed report read. A course
	with a submitted Course Mark Scheme is marked from it; a course without one
	falls back to the calculation whose weightings are written into
	student_progress_report, so a term converts on its own without a mode to set
	anywhere.

	Each course reports `scheme` — the scheme that produced the mark, or None
	where the legacy calculation did.

	`by_course` is the resolved marks, for a caller that needs them too; it is
	fetched here when not supplied. The portal passes its own so the term is read
	once rather than once for the marks and again for the supplementary column.
	"""
	if by_course is None:
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
		marks.update(legacy_course_marks(legacy_results))

	return marks


# The two remark doctypes are the same field under two names, one per sitting.
REMARK_FIELD = {
	"Academic Remark": "remark",
	"Supplementary Academic Remark": "supp_remark",
}


def remark_codes(doctype="Academic Remark"):
	"""The comments QA can put against a result, read off the field that stores them.

	A fixed list rather than free text: they are read off the printed report's
	legend, and a typo makes one invisible. The list is not repeated here, though.
	Frappe refuses a value outside the Select options, so a copy in Python could
	only ever agree with the field or be wrong, and wrong is quiet in both
	directions -- a code on the field but not in the copy cannot be picked, and one
	in the copy but not on the field is offered and then refused on save.
	"""
	options = frappe.get_meta(doctype).get_field(REMARK_FIELD[doctype]).options or ""
	return [code.strip() for code in options.splitlines() if code.strip()]


@frappe.whitelist()
def get_remark_codes(supplementary=0):
	"""So the QA view offers the same list the report legend explains."""
	supplementary = frappe.parse_json(supplementary) if isinstance(supplementary, str) else supplementary
	return remark_codes("Supplementary Academic Remark" if supplementary else "Academic Remark")


@frappe.whitelist()
def set_course_remark(student, course, academic_year, academic_term, comment, supplementary=0):
	"""Record QA's comment on a result, creating it or replacing what was there.

	Server-side because the client cannot do it correctly: these records are
	submittable, so inserting one leaves a draft that nothing reads, and writing
	to a submitted one needs the field to allow it. Both are handled here so a
	comment either lands where the reports look or fails loudly.
	"""
	frappe.only_for(("Academics User", "Education Manager", "System Manager"))

	supplementary = frappe.parse_json(supplementary) if isinstance(supplementary, str) else supplementary
	doctype = "Supplementary Academic Remark" if supplementary else "Academic Remark"
	fieldname = "supp_remark" if supplementary else "remark"

	comment = (comment or "").strip()
	if comment and comment not in remark_codes(doctype):
		frappe.throw(_("{0} is not a comment code.").format(frappe.bold(comment)))

	keys = {
		"student": student,
		"course": course,
		"academic_year": academic_year,
		"academic_term": academic_term,
	}
	existing = frappe.get_all(
		doctype,
		fields=["name", "docstatus"],
		filters=dict(keys, docstatus=["<", 2]),
		# A submitted record is the one the reports read, so it is the one to
		# write to when a draft happens to exist alongside it.
		order_by="docstatus desc",
		limit=1,
	)

	if not existing:
		if not comment:
			return None
		# These doctypes require the comment, so there is no such thing as an
		# empty one to create.
		record = frappe.get_doc(dict(keys, doctype=doctype, **{fieldname: comment}))
		record.insert()
		record.submit()
		return record.name

	record = existing[0]

	if record.docstatus == 0:
		# A draft is invisible to every reader — they all filter on submitted —
		# so writing to one and reporting success would leave the comment
		# nowhere, while the sheet went on refusing approval for want of it.
		# Fill the draft in and file it properly instead.
		if not comment:
			# Nothing was ever filed, so there is nothing to clear.
			return None
		draft = frappe.get_doc(doctype, record.name)
		draft.set(fieldname, comment)
		draft.save()
		draft.submit()
		return draft.name

	frappe.db.set_value(doctype, record.name, fieldname, comment)
	return record.name


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

	# Per sitting per student, for the same reason the by-student version does it:
	# a sheet answers for the sitting it covers and says nothing about the others.
	from_sheet = {}
	for row in _sheet_mark_rows(
		"sheet.course = %(course)s and sheet.academic_term = %(academic_term)s",
		{"course": course, "academic_term": academic_term},
	):
		score = _sheet_mark(row)
		if score is None:
			continue
		from_sheet.setdefault(row.student, []).append(
			{
				"course": course,
				"assessment_group": row.assessment_group,
				"sitting": row.sitting,
				"total_score": score,
				"maximum_score": row.maximum_score or 100,
			}
		)
	return _merge_sheet_marks(by_student, from_sheet)


def course_marks(course, academic_year, academic_term):
	"""One row per student for a whole course, from wherever its marks live.

	What the Course Results report shows. A sheet still in review is not read
	here — it is not approved, so it is not yet the record — which is why the
	sheet builds its own QA view from its own entries through review_rows below.
	"""
	from education_extension.education_extension.doctype.course_mark_scheme.course_mark_scheme import (
		get_scheme,
	)

	scheme = get_scheme(course, academic_year)
	criteria = list(scheme.criteria) if scheme else []

	return {
		"criteria": criteria,
		"rows": review_rows(course, academic_term, criteria, get_course_results(course, academic_term)),
		"scheme": scheme.name if scheme else None,
	}


def review_rows(course, academic_term, criteria, by_student):
	"""A row per student in the shape a reviewer reads: the score for each
	assessment, the semester mark, the final mark, the supplementary mark and the
	stored comments.

	Shared so the report and the sheet's own QA view cannot drift into showing
	the same course two different ways.
	"""
	from education_extension.education_extension.doctype.marking_settings.marking_settings import (
		order_students,
	)

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
			else legacy_course_marks(results).get(course)
		)
		complete = computed and computed["dp_complete"] and computed["exams_complete"]

		rows.append(
			{
				"student": student,
				"student_name": names.get(student, student),
				"scores": scores,
				"dp": round_half_up(computed["dp"]) if computed and computed["dp_complete"] else NO_MARK,
				"final_mark": round_half_up(computed["final_mark"]) if complete else NO_MARK,
				"supplementary": _supplementary_for(results),
				"remark": comments.get(student, ""),
				"supp_remark": supp_comments.get(student, ""),
				"missing": (computed or {}).get("missing") or [],
				"failed_subminima": (computed or {}).get("failed_subminima") or [],
			}
		)

	return rows


def _supplementary_for(results):
	"""The supplementary mark among a student's results, as a percentage."""
	for result in results:
		_group, sitting = sitting_of(result)
		if sitting != SUPPLEMENTARY:
			continue
		ratio = score_ratio(result)
		if ratio is not None:
			return round_half_up(ratio * 100)
	return NO_MARK


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

	# Read once and used twice: the marks are worked out from these, and so is the
	# supplementary column.
	by_course = get_assessment_results(student, academic_term)
	marks = student_marks(student, academic_year, academic_term, by_course)
	comments = _remarks(student, academic_term, "Academic Remark", "remark")

	# The supplementary sitting is released on its own date, so a student can be
	# looking at their main marks while the supplementary ones are still held.
	if is_released(academic_year, academic_term, ISSUE_DATE_SUPPLEMENTARY):
		supplementary = _supplementary_marks(by_course)
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
				"dp": f"{round_half_up(computed['dp'])}%" if computed["dp_complete"] else NO_MARK,
				"final_mark": f"{round_half_up(computed['final_mark'])}%" if complete else NO_MARK,
				"remark": comments.get(course, NO_MARK),
				"supp_exam": supplementary.get(course, NO_MARK),
				"supp_remark": supplementary_comments.get(course, NO_MARK),
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


def _supplementary_marks(by_course):
	"""The supplementary exam mark per course, as a percentage. Reported on its
	own and never folded into the final mark.

	Read from the resolved marks through the same helper the staff side uses.
	Querying Assessment Result directly, as this once did, could not see a
	supplementary captured on an approved Course Mark Sheet — so a student was
	shown a dash for a re-sit the Course Results report showed a mark for.
	"""
	marks = {}
	for course, results in by_course.items():
		mark = _supplementary_for(results)
		if mark != NO_MARK:
			marks[course] = f"{mark}%"

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
	return round_half_up(mark) if complete else NO_MARK


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
