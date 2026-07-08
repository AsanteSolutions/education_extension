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


class StudentProgressReport(Document):
	pass

@frappe.whitelist()
def preview_progress_report(doc):
    doc = frappe._dict(json.loads(doc))
    results = calculate_final_results(get_results(doc))
    courses = results.keys() if results else []
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
		"expected_completion": get_expected_completion(doc),
		"signature_one_name": signature_one_name, "signature_one_role": signature_one_role, "signature_one": signature_one,
		"signature_two_name": signature_two_name, "signature_two_role": signature_two_role, "signature_two": signature_two},

	)

    final_template = frappe.render_template("frappe/www/printview.html", {"body": html, "title": "Progress Report"})

    frappe.response.filename = "Progress Report" + doc.student_name + ".pdf"
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
			"docstatus": ["!=", 2],
		},
	)

	semesters = [
		s for s in (_program_semester(e.program) for e in enrollments) if s is not None
	]
	return max(semesters) if semesters else None


def get_year_label(doc):
	"""Build the "YEAR II SEMESTER III" heading from the student's enrolled
	programme. The Diploma in Animal Health is split into six per-semester
	programmes named "Diploma in Animal Health Semester X" (X = 1..6), where the
	year is ceil(X / 2) and X itself is the overall semester number."""
	semester = _highest_semester(doc)
	if semester is None:
		return ""

	year = (semester + 1) // 2
	return "YEAR {} SEMESTER {}".format(_to_roman(year), _to_roman(semester))


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
		filters={"student": doc.student, "academic_term": doc.academic_term, "docstatus": ['!=', 2]}
	)
	return results

def round_half_up(value):
    return str(int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)))

def calculate_final_results(results):
    """Calculate the final mark for every course the student has assessment
    results for, returning a dict keyed by course code (value "-" until both
    the DP and exam components are complete)."""

    NUMBER_OF_ASSIGNMENTS = 2
    NUMBER_OF_TESTS = 2

    NO_PRAC_OR_ORAL_EXAM = {"OCAH1101", "ANH2305", "AEC2301", "ANH3503", "AEC2302", "ANH3507", "ANH3506"}
    NO_PRAC_TEST = {"OCAH1101", "ANH2305", "AEC2301", "AEC2302", "ANH3507", "ANH2404"}
    NO_ORAL_EXAM = {"CLT1101"}

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
        for sr in course_results:
            field = group_to_field.get(sr["assessment_group"])
            if field and sr["total_score"] is not None:
                scores[field] = float(sr["total_score"])

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

        if dp_complete and exams_complete:
            final_results[course] = round_half_up(exam_mark + dp * 0.5)
        else:
            final_results[course] = "-"

    return final_results