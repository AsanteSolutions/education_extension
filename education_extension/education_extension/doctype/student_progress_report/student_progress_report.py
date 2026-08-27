# Copyright (c) 2026, Asante Solutions and contributors
# For license information, please see license.txt

import json
import re
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

import frappe
from frappe.utils.pdf import get_pdf
from frappe.model.document import Document
from frappe.www.printview import get_letter_head

# The progress report is issued for a single qualification, so these are fixed.
QUALIFICATION_NAME = "DIPLOMA IN ANIMAL HEALTH"
QUALIFICATION_ID = "90911"

# Assessment group for the supplementary (re-sit) exam. Handled separately from
# the regular marks, mirroring the portal Grades page.
SUPP_GROUP = "Supplementary Exam"

# Aegrotat (illness/absence) sittings are recorded by prefixing the normal exam
# assessment group with AEGRO, e.g. "AEGRO Theory Exam". Any such result in the
# term's marks moves the report onto the AEGROTAT issue date.
AEGROTAT_GROUP_PREFIX = "AEGRO"

# The "Issue Date For" options on Progress Report Issue Date. Standard is a normal
# marks run; the rest apply on top of it when the report carries a supplementary
# sitting, an aegrotat sitting, or remarked results.
ISSUE_DATE_STANDARD = "Standard"
ISSUE_DATE_SUPPLEMENTARY = "Supplementary"
ISSUE_DATE_REMARKING = "Remarking"
ISSUE_DATE_AEGROTAT = "AEGROTAT"

# Which sittings a course is examined and assessed on. These are the exceptions
# to the standard shape (two tests, two assignments, a practical test, and theory,
# practical and oral papers); a course code absent from a set follows the standard.
# Module-level so Course Mark Scheme can generate the equivalent scheme rows from
# them instead of keeping a second copy.
NO_PRAC_OR_ORAL_EXAM = {"OCAH1101", "ANH2305", "AEC2301", "ANH3503", "AEC2302", "ANH3507", "ANH3506"}
NO_PRAC_TEST = {"OCAH1101", "ANH2305", "AEC2301", "AEC2302", "ANH3507", "ANH2404"}
NO_ORAL_EXAM = {"CLT1101"}


class StudentProgressReport(Document):
	pass

@frappe.whitelist()
def preview_progress_report(doc):
    # `doc` arrives as a JSON string from the desk form; tolerate an already-parsed
    # dict so the endpoint also works when called with a JSON request body.
    doc = frappe._dict(json.loads(doc) if isinstance(doc, str) else doc)
    # Marked from the course's Course Mark Scheme where it has one, and from
    # the calculation below where it does not. Imported here rather than at the
    # top because marking reads that fallback calculation from this module.
    from education_extension.education_extension.marking import final_marks

    results = final_marks(doc.student, doc.academic_year, doc.academic_term)
    courses = results.keys() if results else []
    results_remarks = get_academic_remarks(doc)
    supplementary = get_supplementary_results(doc)
    supplementary_remarks = get_supplementary_remarks(doc)
    # Modules are printed one table per programme semester, ascending; the
    # course -> semester lookup is shared by both sittings.
    course_semesters = get_course_semesters(doc)
    result_groups = group_by_semester(results, doc, course_semesters)
    supplementary_groups = group_by_semester(supplementary, doc, course_semesters)
    issue_date = get_issue_date(doc, supplementary, supplementary_remarks)
    # Footer stamp: when this PDF was generated, as opposed to when the marks were
    # issued.
    print_date = frappe.utils.getdate(frappe.utils.nowdate())
    letterhead = get_letter_head(doc, not doc.add_letterhead)
    signature_settings = frappe.get_single("Student Progress Report Settings")
    signature_one_name = signature_settings.signature_one_name
    signature_one_role = signature_settings.signature_one_role
    signature_one = signature_settings.signature_one
    signature_two_name = signature_settings.signature_two_name
    signature_two_role = signature_settings.signature_two_role
    signature_two = signature_settings.signature_two
    html = frappe.render_template(
		"education_extension/education_extension/doctype/student_progress_report/student_progress_report_template.html",
		{"doc": doc, "results": results, "courses": courses, "letterhead": letterhead and letterhead.get("content", None),
   		"add_letterhead": doc.add_letterhead if doc.add_letterhead else False,
		"qualification": QUALIFICATION_NAME, "qualification_id": QUALIFICATION_ID,
		"identity_number": get_identity_number(doc), "year_label": get_year_label(doc),
		"issue_date": issue_date, "print_date": print_date,
		"expected_completion": get_expected_completion(doc),
		"results_remarks": results_remarks, "result_groups": result_groups,
		"supplementary": supplementary, "supplementary_remarks": supplementary_remarks,
		"supplementary_groups": supplementary_groups,
		"signature_one_name": signature_one_name, "signature_one_role": signature_one_role, "signature_one": signature_one,
		"signature_two_name": signature_two_name, "signature_two_role": signature_two_role, "signature_two": signature_two},

	)

    final_template = frappe.render_template("frappe/www/printview.html", {"body": html, "title": "Progress Report"})

    # Streamed straight back as PDF bytes; the desk form fetches this as a blob and
    # saves it under the filename set here.
    frappe.response.filename = "Progress Report - {}.pdf".format(
        doc.student_name or doc.student or ""
    )
    frappe.response.filecontent = get_pdf(final_template)
    frappe.response.type = "pdf"

def get_identity_number(doc):
	"""The student's national ID, stored on the Student as a custom field."""
	if not doc.student:
		return ""
	return frappe.db.get_value("Student", doc.student, "custom_id_number") or ""


def _to_roman(n):
	numerals = [
		(1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"),
		(90, "XC"), (50, "L"), (40, "XL"), (10, "X"), (9, "IX"),
		(5, "V"), (4, "IV"), (1, "I"),
	]
	result = ""
	for value, symbol in numerals:
		while n >= value:
			result += symbol
			n -= value
	return result


def _program_semester(program):
	"""Extract the trailing semester number from a programme name such as
	'Diploma in Animal Health Semester 3'. Returns None if none is found."""
	if not program:
		return None
	match = re.search(r"(\d+)\s*$", program)
	return int(match.group(1)) if match else None


def _highest_semester(doc):
	"""The highest programme semester (1..6) the student is enrolled in for this
	term. A student may hold several enrolments in the same term (e.g. a second
	year repeating first-year modules is in both Semester 1 and Semester 2), so
	the report uses the highest. Returns None if none can be determined."""
	enrollments = frappe.get_all(
		"Program Enrollment",
		fields=["program"],
		filters={
			"student": doc.student,
			"academic_year": doc.academic_year,
			"academic_term": doc.academic_term,
			"docstatus": 1,
		},
	)

	semesters = [
		s for s in (_program_semester(e.program) for e in enrollments) if s is not None
	]
	return max(semesters) if semesters else None


def _semester_label(semester):
	"""Heading for an overall semester number (1..6), e.g. 4 -> "YEAR II SEMESTER
	II": the year is ceil(semester / 2) and the semester is shown per-year (I or
	II), not as the overall number."""
	year = (semester + 1) // 2
	semester_in_year = 1 if semester % 2 else 2
	return "YEAR {} SEMESTER {}".format(_to_roman(year), _to_roman(semester_in_year))


def get_year_label(doc):
	"""Build the "YEAR II SEMESTER III" heading from the student's enrolled
	programme. The Diploma in Animal Health is split into six per-semester
	programmes named "Diploma in Animal Health Semester X" (X = 1..6)."""
	semester = _highest_semester(doc)
	if semester is None:
		return ""
	return _semester_label(semester)


def get_course_semesters(doc):
	"""Map each course to the programme semester (1..6) it belongs to, so the
	report can print one marks table per semester. The curriculum (Program Course
	on each "... Semester X" programme) provides the base mapping; the student's
	own enrolments for this term override it, which is what places a repeated
	module under the semester it is actually being repeated in."""
	semesters = {}

	for row in frappe.get_all(
		"Program Course",
		fields=["course", "parent"],
		filters={"parenttype": "Program"},
	):
		semester = _program_semester(row.parent)
		if semester is None:
			continue
		# A module listed by several programmes is attributed to the earliest.
		current = semesters.get(row.course)
		if current is None or semester < current:
			semesters[row.course] = semester

	enrollments = frappe.get_all(
		"Program Enrollment",
		fields=["name", "program"],
		filters={
			"student": doc.student,
			"academic_year": doc.academic_year,
			"academic_term": doc.academic_term,
			"docstatus": 1,
		},
	)
	enrollment_semester = {e.name: _program_semester(e.program) for e in enrollments}
	if enrollment_semester:
		for row in frappe.get_all(
			"Program Enrollment Course",
			fields=["course", "parent"],
			filters={
				"parent": ["in", list(enrollment_semester)],
				"parenttype": "Program Enrollment",
			},
		):
			semester = enrollment_semester.get(row.parent)
			if semester is not None:
				semesters[row.course] = semester

	return semesters


def group_by_semester(rows, doc, course_semesters=None):
	"""Split a { course: mark } dict into one group per programme semester, in
	ascending semester order, as [{"semester", "label", "rows"}]. Courses within a
	group are sorted by code. Courses whose semester cannot be determined are
	collected into a final group headed by the report's own year/term label."""
	if not rows:
		return []

	if course_semesters is None:
		course_semesters = get_course_semesters(doc)

	grouped = defaultdict(dict)
	for course in sorted(rows):
		grouped[course_semesters.get(course)][course] = rows[course]

	# Only the unknown-semester group needs the report-wide heading, and resolving
	# it costs a query, so look it up only when there is such a group.
	fallback_label = (get_year_label(doc) or doc.academic_term or "") if None in grouped else ""
	# `None` (unknown semester) sorts after the numbered semesters.
	return [
		{
			"semester": semester,
			"label": _semester_label(semester) if semester is not None else fallback_label,
			"rows": grouped[semester],
		}
		for semester in sorted(grouped, key=lambda s: (s is None, s))
	]


def _academic_year_start(doc):
	"""Starting calendar year of the report's academic year, used as the base for
	the expected-completion calculation. Prefers the Academic Year's
	year_start_date, falls back to a 4-digit year in its name, then to today."""
	if doc.academic_year:
		start = frappe.db.get_value("Academic Year", doc.academic_year, "year_start_date")
		if start:
			return frappe.utils.getdate(start).year
		match = re.search(r"(\d{4})", doc.academic_year)
		if match:
			return int(match.group(1))
	return frappe.utils.getdate(frappe.utils.nowdate()).year


def get_expected_completion(doc):
	"""Expected year of completion, based on the highest enrolled semester and
	anchored to the report's academic year: Semester 5/6 -> that year,
	Semester 3/4 -> the next year, Semester 1/2 -> the year after that.
	Equivalently: academic_year_start + (3 - academic_year_number), where the
	academic year number is ceil(semester / 2)."""
	semester = _highest_semester(doc)
	if semester is None:
		return ""

	year = (semester + 1) // 2  # 1, 2 or 3
	return str(_academic_year_start(doc) + (3 - year))


def get_results(doc):
	# Get the student results based on the provided doc data
	# Implement your logic here to fetch and process the results
	# For example, you might query the database for the student's grades, attendance, etc.
	# Return the results in a suitable format (e.g., a dictionary or list)

	results = frappe.get_all(
		"Assessment Result",
		fields=["course", "assessment_group", "total_score"],
		filters={
			"student": doc.student,
			"academic_term": doc.academic_term,
			# Supplementary Exam is surfaced separately; keep it out of the DP /
			# final-mark computation (same as the portal Grades page).
			"assessment_group": ["!=", SUPP_GROUP],
			"docstatus": 1,
		},
	)
	return results


def get_supplementary_results(doc):
	"""Supplementary exam mark per course, mirroring the portal Grades page: the
	"Supplementary Exam" assessment group's score (treated as a percentage, like
	the other marks here). Keyed by course; usually empty as few students supplement."""
	rows = frappe.get_all(
		"Assessment Result",
		fields=["course", "total_score"],
		filters={
			"student": doc.student,
			"academic_term": doc.academic_term,
			"assessment_group": SUPP_GROUP,
			"docstatus": 1,
		},
	)
	return {r.course: round_half_up(r.total_score) for r in rows if r.total_score is not None}


def get_academic_remarks(doc):
	"""Stored remark per course, from the Academic Remark doctype. Keyed by course.
	The report shows only stored remarks (it never derives them from the mark)."""
	rows = frappe.get_all(
		"Academic Remark",
		fields=["course", "remark"],
		filters={
			"student": doc.student,
			"academic_term": doc.academic_term,
			"docstatus": 1,
		},
	)
	return {r.course: r.remark for r in rows if r.remark}


def get_supplementary_remarks(doc):
	"""Stored supplementary remark per course, from the Supplementary Academic
	Remark doctype (whose remark field is named `supp_remark`). Keyed by course."""
	rows = frappe.get_all(
		"Supplementary Academic Remark",
		fields=["course", "supp_remark"],
		filters={
			"student": doc.student,
			"academic_term": doc.academic_term,
			"docstatus": 1,
		},
	)
	return {r.course: r.supp_remark for r in rows if r.supp_remark}


def _has_aegrotat_result(doc):
	"""True when the term's marks include an aegrotat (illness/absence) sitting,
	i.e. a result in an AEGRO-prefixed exam group."""
	return bool(
		frappe.get_all(
			"Assessment Result",
			filters={
				"student": doc.student,
				"academic_term": doc.academic_term,
				"assessment_group": ["like", AEGROTAT_GROUP_PREFIX + "%"],
				"docstatus": 1,
			},
			limit=1,
		)
	)


def _has_remarked_result(doc):
	"""True when a result or remark for the term has been remarked. Correcting a
	submitted document in Frappe means cancelling and amending it, so the amendment
	(`amended_from` set) is the trace a remark leaves behind."""
	for doctype in ("Assessment Result", "Academic Remark"):
		if frappe.get_all(
			doctype,
			filters={
				"student": doc.student,
				"academic_term": doc.academic_term,
				"amended_from": ["is", "set"],
				"docstatus": 1,
			},
			limit=1,
		):
			return True
	return False


def _issue_date_kinds(doc, supplementary=None, supplementary_remarks=None):
	"""The "Issue Date For" kinds this report falls under. Standard always applies
	— the report always carries the term's normal marks — and the others are added
	on top when the report also carries a supplementary sitting, an aegrotat
	sitting, or results that have been remarked."""
	kinds = [ISSUE_DATE_STANDARD]

	if supplementary is None:
		supplementary = get_supplementary_results(doc)
	if supplementary_remarks is None:
		supplementary_remarks = get_supplementary_remarks(doc)
	if supplementary or supplementary_remarks:
		kinds.append(ISSUE_DATE_SUPPLEMENTARY)

	if _has_aegrotat_result(doc):
		kinds.append(ISSUE_DATE_AEGROTAT)

	if _has_remarked_result(doc):
		kinds.append(ISSUE_DATE_REMARKING)

	return kinds


def get_issue_date(doc, supplementary=None, supplementary_remarks=None):
	"""The date printed as the report's "Date of Issue".

	Taken from the submitted Progress Report Issue Date records for the report's
	academic year and term, limited to the kinds this report falls under (see
	_issue_date_kinds). The latest of those is used, since the report is only
	issued once the last of those sittings has been dealt with.

	With no such record on file, it falls back to when the marks were last
	touched: the latest modification across the student's results and remarks."""
	kinds = _issue_date_kinds(doc, supplementary, supplementary_remarks)

	rows = frappe.get_all(
		"Progress Report Issue Date",
		fields=["issue_date"],
		filters={
			"academic_year": doc.academic_year,
			"academic_term": doc.academic_term,
			# "" catches a record left on no kind at all, which is a Standard run.
			"issue_date_for": ["in", kinds + [""]],
			"docstatus": 1,
		},
		order_by="issue_date desc",
		limit=1,
	)
	if rows and rows[0].issue_date:
		return frappe.utils.getdate(rows[0].issue_date)

	return _last_marks_change(doc) or frappe.utils.getdate(frappe.utils.nowdate())


def _last_marks_change(doc):
	"""When the student's marks for the term were last touched: the latest
	`modified` across their results and remarks. None if they have neither, which
	only happens on a report with nothing on it."""
	latest = None
	for doctype in ("Assessment Result", "Academic Remark", "Supplementary Academic Remark"):
		rows = frappe.get_all(
			doctype,
			fields=["modified"],
			filters={
				"student": doc.student,
				"academic_term": doc.academic_term,
				"docstatus": 1,
			},
			order_by="modified desc",
			limit=1,
		)
		if rows and rows[0].modified and (latest is None or rows[0].modified > latest):
			latest = rows[0].modified

	return frappe.utils.getdate(latest) if latest else None

def round_half_up(value):
    return str(int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)))

def _assessment_field(assessment_group, group_to_field):
	"""The score field an assessment group's mark belongs to, as (field, is_aegrotat).

	An aegrotat sitting is the normal exam group prefixed with AEGRO (e.g. "AEGRO
	Theory Exam") and stands in for the sitting it replaces, so it resolves to the
	same field as the group it prefixes. (None, False) for a group that is not part
	of the final mark, such as the supplementary exam."""
	group = (assessment_group or "").strip()

	field = group_to_field.get(group)
	if field:
		return field, False

	if group.upper().startswith(AEGROTAT_GROUP_PREFIX):
		for name, aegrotat_field in group_to_field.items():
			if group.upper().endswith(name.upper()):
				return aegrotat_field, True

	return None, False


def calculate_final_results(results):
    """Final mark per course, keyed by course code, in the form the report prints:
    "-" until both the DP and the exam components are complete."""
    return {
        course: format_legacy_mark(marks)
        for course, marks in calculate_final_results_detailed(results).items()
    }


def format_legacy_mark(marks):
    return (
        round_half_up(marks["final_mark"])
        if marks["dp_complete"] and marks["exams_complete"]
        else "-"
    )


def calculate_final_results_detailed(results):
    """The calculation in full: DP, final mark and both completeness flags per
    course, worked out from the weightings written into this module.

    This is the fallback for a course that has no Course Mark Scheme yet, which
    is why it reports the DP rather than only the final mark — an unconverted
    course still has to show one on the portal."""

    NUMBER_OF_ASSIGNMENTS = 2
    NUMBER_OF_TESTS = 2

    group_to_field = {
        "Assignment 1": "assignment_1",
        "Assignment 2": "assignment_2",
        "Test 1": "test_1",
        "Test 2": "test_2",
        "Practical Test": "practical_test",
        "Theory Exam": "theory_exam",
        "Practical Exam": "practical_exam",
        "Oral Exam": "oral_exam",
    }

    # Group the flat assessment results by course
    courses = defaultdict(list)
    for d in results:
        courses[d["course"]].append(d)

    final_results = {}

    for course, course_results in courses.items():
        is_no_prac_or_oral = any(c in course for c in NO_PRAC_OR_ORAL_EXAM)
        is_no_oral = any(c in course for c in NO_ORAL_EXAM)
        is_no_prac_test = any(c in course for c in NO_PRAC_TEST)

        scores = {field: None for field in group_to_field.values()}
        aegrotat_fields = set()
        for sr in course_results:
            field, is_aegrotat = _assessment_field(sr["assessment_group"], group_to_field)
            if not field or sr["total_score"] is None:
                continue
            # An aegrotat sitting replaces the one it stands in for, so it keeps the
            # field if both were captured.
            if field in aegrotat_fields and not is_aegrotat:
                continue
            scores[field] = float(sr["total_score"])
            if is_aegrotat:
                aegrotat_fields.add(field)

        # ---- DP (continuous assessment, worth 50% of the final mark) ----
        if is_no_prac_test:
            test_w, assign_w, prac_w = 30.0, 20.0, 0.0
        else:
            test_w, assign_w, prac_w = 15.0, 10.0, 50.0  # 30/20 * 0.5, plus practical

        dp = 0.0
        for key in ("test_1", "test_2"):
            if scores[key] is not None:
                dp += (scores[key] / 100.0) * test_w
        for key in ("assignment_1", "assignment_2"):
            if scores[key] is not None:
                dp += (scores[key] / 100.0) * assign_w
        if not is_no_prac_test and scores["practical_test"] is not None:
            dp += (scores["practical_test"] / 100.0) * prac_w

        tests_done = sum(scores[k] is not None for k in ("test_1", "test_2"))
        assigns_done = sum(scores[k] is not None for k in ("assignment_1", "assignment_2"))
        prac_done = is_no_prac_test or scores["practical_test"] is not None
        dp_complete = (
            tests_done == NUMBER_OF_TESTS
            and assigns_done == NUMBER_OF_ASSIGNMENTS
            and prac_done
        )

        # ---- Exam portion (worth 50% of the final mark) ----
        theory = scores["theory_exam"]
        prac = scores["practical_exam"]
        oral = scores["oral_exam"]

        exam_mark = 0.0
        if is_no_prac_or_oral:
            if theory is not None:
                exam_mark += (theory / 100.0) * 50.0
            exams_complete = theory is not None
        elif is_no_oral:
            if theory is not None:
                exam_mark += (theory / 100.0) * 40.0 * 0.5
            if prac is not None:
                exam_mark += (prac / 100.0) * 60.0 * 0.5
            exams_complete = theory is not None and prac is not None
        else:
            if theory is not None:
                exam_mark += (theory / 100.0) * 40.0 * 0.5
            if prac is not None:
                exam_mark += (prac / 100.0) * 50.0 * 0.5
            if oral is not None:
                exam_mark += (oral / 100.0) * 10.0 * 0.5
            exams_complete = theory is not None and prac is not None and oral is not None

        final_results[course] = {
            "dp": dp,
            "final_mark": exam_mark + dp * 0.5,
            "dp_complete": dp_complete,
            "exams_complete": exams_complete,
        }

    return final_results