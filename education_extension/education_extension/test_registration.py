# Copyright (c) 2026, Asante Solutions and Contributors
# See license.txt

"""Tests for the registration rules.

Split deliberately. `TestRegistrationRules` touches no database: it is the
regression net for the decisions that actually matter, and it runs anywhere.
`TestRegistrationFlow` needs the curriculum, and skips itself where that is
absent rather than failing — the rules are the thing under test, not whether a
given site happens to teach the Diploma in Animal Health.

`bench run-tests` cannot bootstrap this site (overlapping Fiscal Year), so these
also run from a console:

    from education_extension.education_extension.test_registration import run_tests
    run_tests()
"""

import json
import unittest

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase
from frappe.utils import add_days, nowdate

from education_extension.education_extension import registration as reg
from education_extension.patches import seed_course_prerequisites as seed

PROGRAM = "Diploma in Animal Health Semester {0}"

# Both declarations ticked, which is what the consent step sends.
AGREED = {"prerequisites": True, "popia": True}

# A drawn mark, as the pad produces it: a PNG data URI. One pixel is enough.
SIGNED = {
	"student": (
		"data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
		"AAAADUlEQVR42mP8z8AAAwAB/wFDkQvzAAAAAElFTkSuQmCC"
	)
}


class TestRegistrationRules(UnitTestCase):
	"""The rules, with hand-built inputs and no records involved."""

	def test_every_legend_code_maps_to_an_outcome(self):
		expected = {
			"P": reg.PASSED,
			"PD": reg.PASSED,
			"C": reg.PASSED,
			"PS": reg.PASSED,
			"PSE": reg.PASSED,
			"SUPP": reg.PENDING,
			"AEGRO": reg.PENDING,
			"F": reg.FAILED,
			"FS": reg.FAILED,
			"FSE": reg.FAILED,
			"FSUB": reg.FAILED,
			"NSM": reg.FAILED,
			"DISC": reg.FAILED,
		}
		# Every code the remark fields offer must be accounted for, or a new one
		# would silently read as a failure.
		options = frappe.get_meta("Academic Remark").get_field("remark").options.split("\n")
		codes = {code for code in options if code}
		self.assertEqual(codes, set(expected), "the Select options and this table have diverged")

		for code, outcome in expected.items():
			self.assertEqual(reg.outcome_of(code), outcome, code)

	def test_a_condoned_pass_carries_the_prerequisite(self):
		# The legend calls C a condoned 49%. Awarding the credit is the point of
		# condoning, so it has to satisfy a prerequisite.
		self.assertEqual(reg.outcome_of("C"), reg.PASSED)

	def test_unknown_and_empty_codes_are_not_passes(self):
		for value in ("", None, "   ", "A+", "75", "see email", "Passed"):
			self.assertNotEqual(reg.outcome_of(value), reg.PASSED, repr(value))

	def test_codes_are_read_case_and_space_insensitively(self):
		self.assertEqual(reg.outcome_of(" supp "), reg.PENDING)
		self.assertEqual(reg.outcome_of("pd"), reg.PASSED)

	def test_a_recorded_failure_blocks_either_way(self):
		rules = {"X": [("A", reg.PREREQUISITE)]}
		for strict in (False, True):
			blocking, outstanding, unverified = reg.unmet_prerequisites(
				"X", {"A": reg.FAILED}, set(), rules, strict
			)
			self.assertEqual(blocking, ["A"], f"strict={strict}")
			self.assertEqual((outstanding, unverified), ([], []))

	def test_a_missing_result_follows_the_setting(self):
		rules = {"X": [("A", reg.PREREQUISITE)]}

		blocking, _outstanding, unverified = reg.unmet_prerequisites("X", {}, set(), rules, False)
		self.assertEqual((blocking, unverified), ([], ["A"]))

		blocking, _outstanding, unverified = reg.unmet_prerequisites("X", {}, set(), rules, True)
		self.assertEqual((blocking, unverified), (["A"], []))

	def test_a_pending_result_is_provisional_not_blocking(self):
		rules = {"X": [("A", reg.PREREQUISITE)]}
		for strict in (False, True):
			blocking, outstanding, _unverified = reg.unmet_prerequisites(
				"X", {"A": reg.PENDING}, set(), rules, strict
			)
			# Pending must not depend on the setting: it is a known state, not a
			# gap in the record.
			self.assertEqual((blocking, outstanding), ([], ["A"]), f"strict={strict}")

	def test_a_corequisite_is_satisfied_by_being_taken_alongside(self):
		rules = {"X": [("A", reg.COREQUISITE)]}

		blocking, _o, _u = reg.unmet_prerequisites("X", {}, {"A"}, rules, True)
		self.assertEqual(blocking, [], "taking it alongside should satisfy it")

		blocking, _o, _u = reg.unmet_prerequisites("X", {"A": reg.PASSED}, set(), rules, True)
		self.assertEqual(blocking, [], "having passed it should satisfy it")

		blocking, _o, _u = reg.unmet_prerequisites("X", {"A": reg.FAILED}, set(), rules, False)
		self.assertEqual(blocking, ["A"], "failed and not taken should block")

	def test_blocks_alternate_between_the_terms(self):
		offered = {n: PROGRAM.format(n) for n in range(1, 7)}

		from education_extension.education_extension.report.registration_status.registration_status import (
			expected_block,
		)

		# Odd blocks run in the first term, even ones in the second.
		self.assertEqual(expected_block(0, 1, offered), 1)
		self.assertEqual(expected_block(2, 1, offered), 3)
		self.assertEqual(expected_block(1, 2, offered), 2)
		self.assertEqual(expected_block(3, 2, offered), 4)

		# A student who sat a term out has nothing to move into this time, which
		# must be reported rather than skipping them a block forward.
		self.assertIsNone(expected_block(1, 1, offered))
		self.assertIsNone(expected_block(2, 2, offered))

		# And nothing follows the last block.
		self.assertIsNone(expected_block(6, 2, offered))

	def test_reason_lines_name_codes_not_docnames(self):
		self.assertEqual(reg._codes(["ANH1101 - Vet Anatomy & Physiology I"]), ["ANH1101"])
		self.assertEqual(reg._codes(["unparseable"]), ["unparseable"])

	def test_only_actionable_statuses_are_selectable(self):
		self.assertEqual(reg.SELECTABLE, {reg.REQUIRED, reg.CARRIED_OVER, reg.PROVISIONAL})
		for status in (reg.BLOCKED, reg.ALREADY_PASSED, reg.AWAITING, reg.REGISTERED):
			self.assertNotIn(status, reg.SELECTABLE)

	def test_carry_overs_stay_in_their_own_semester(self):
		# A module is taught in its own semester and only there, so a failed
		# first-semester module waits for the next first semester rather than
		# being repeated in a second one. Blocks therefore step back in twos.
		self.assertEqual(reg.carry_over_blocks(1), [])
		self.assertEqual(reg.carry_over_blocks(2), [])
		self.assertEqual(reg.carry_over_blocks(3), [1])
		self.assertEqual(reg.carry_over_blocks(4), [2])
		self.assertEqual(reg.carry_over_blocks(5), [3, 1])
		self.assertEqual(reg.carry_over_blocks(6), [4, 2])

		for block in range(1, 7):
			for earlier in reg.carry_over_blocks(block):
				self.assertEqual(
					earlier % 2, block % 2, f"block {earlier} cannot run alongside {block}"
				)

	def test_a_students_own_semester_is_not_optional(self):
		# Carry-overs are the only thing a student may decline.
		self.assertEqual(reg.MANDATORY, {reg.REQUIRED, reg.PROVISIONAL})
		self.assertNotIn(reg.CARRIED_OVER, reg.MANDATORY)


class TestPrerequisiteGraph(IntegrationTestCase):
	"""The seeded graph, which is hand-editable from the Course form."""

	def setUp(self):
		if not frappe.get_all("Course Prerequisite", limit=1):
			self.skipTest("no prerequisite graph on this site")

	def test_every_referenced_code_resolves_to_a_course(self):
		self.assertEqual(seed.verify(), [], "the curriculum and the seed table have diverged")

	def test_no_prerequisite_points_at_a_missing_course(self):
		dangling = frappe.db.sql(
			"""select cp.parent, cp.course from `tabCourse Prerequisite` cp
			left join tabCourse c on c.name = cp.course where c.name is null"""
		)
		self.assertEqual(dangling, (), "prerequisites pointing at courses that do not exist")

	def test_no_course_is_its_own_prerequisite(self):
		self.assertEqual(
			frappe.db.sql("""select parent from `tabCourse Prerequisite` where parent = course"""),
			(),
		)

	def test_the_graph_has_no_cycles(self):
		"""A cycle makes a module permanently unregisterable, and with a hard
		block and no reviewer nobody would be told why."""
		graph = {}
		for row in frappe.get_all(
			"Course Prerequisite", fields=["parent", "course", "kind"]
		):
			if row.kind == reg.PREREQUISITE:
				graph.setdefault(row.parent, set()).add(row.course)

		state = {}
		cycles = []

		def walk(node, trail):
			if state.get(node) == "done":
				return
			if state.get(node) == "open":
				cycles.append(trail[trail.index(node) :] + [node])
				return
			state[node] = "open"
			for nxt in sorted(graph.get(node, ())):
				walk(nxt, trail + [node])
			state[node] = "done"

		for node in sorted(graph):
			walk(node, [])

		self.assertEqual(cycles, [], "prerequisite cycles")


class TestRegistrationFlow(IntegrationTestCase):
	"""Registering, and what happens when an outstanding result settles.

	Every test here rolls back, including the Registration Period it creates.
	"""

	def setUp(self):
		self.term = "2026 (Second Semester 2026)"
		self.previous_term = "2026 (First Semester 2026)"
		if not frappe.db.exists("Academic Term", self.term):
			self.skipTest("curriculum terms not on this site")

		# Must not already be registered for the term under test, or the page
		# correctly reports a registration instead of offering one. Stated here
		# rather than left to whichever student a bare query happens to return:
		# eighteen students hold two enrolments in one term, and picking one of
		# those made eight of these tests fail for the wrong reason.
		candidates = frappe.db.sql(
			"""
			select pe.student from `tabProgram Enrollment` pe
			where pe.program = %(program)s and pe.docstatus = 1
			  and not exists (
				select 1 from `tabProgram Enrollment` other
				where other.student = pe.student and other.docstatus = 1
				  and other.academic_term = %(term)s
			  )
			  -- Registering is impossible for a student whose student_email_id is
			  -- not a User: this site's LMS script links an LMS Program Member by
			  -- that field, the link fails validation, and the enrolment insert
			  -- aborts with it. 22 of 189 students are in that state, so a bare
			  -- query lands on one sooner or later and the failure looks like a
			  -- registration bug rather than the data problem it is.
			  and exists (
				select 1 from tabStudent s
				join tabUser u on u.name = s.student_email_id
				where s.name = pe.student
			  )
			order by pe.student
			limit 1
			""",
			{"program": PROGRAM.format(3), "term": self.term},
		)
		if not candidates:
			self.skipTest("no unregistered Semester 3 student to progress")
		self.student = candidates[0][0]

		# This site has a Server Script on Program Enrollment that pushes the
		# student into an LMS Program on before_insert, and the LMS Program refuses
		# a member it already has -- so a second registration for the same
		# programme aborts. Worse, that write escapes the rollback: the first test
		# to register would otherwise leave the membership behind and every later
		# one in the run would fail on it. Cleared at the start of each test, which
		# is order-independent, unlike a cleanup.
		# Keyed on student_email_id, which is what the script links the member by --
		# not on `user`, which is a different field and happens to hold the same
		# value for most but not all students here.
		for field in ("student_email_id", "user"):
			member = frappe.db.get_value("Student", self.student, field)
			if member:
				frappe.db.delete("LMS Program Member", {"member": member})

		frappe.db.delete("Registration Period", {"academic_term": self.term})
		self.period = frappe.get_doc(
			{
				"doctype": "Registration Period",
				"academic_term": self.term,
				"opens_on": add_days(nowdate(), -1),
				"last_date_to_register": add_days(nowdate(), 14),
			}
		).insert()
		frappe.clear_cache(doctype="Registration Period")

	def remark(self, course, code):
		name = frappe.db.exists(
			"Academic Remark",
			{
				"student": self.student,
				"course": course,
				"academic_term": self.previous_term,
				"docstatus": 1,
			},
		)
		if name:
			frappe.db.set_value("Academic Remark", name, "remark", code, update_modified=False)
			return name
		doc = frappe.get_doc(
			{
				"doctype": "Academic Remark",
				"student": self.student,
				"course": course,
				"academic_year": "2026",
				"academic_term": self.previous_term,
				"remark": code,
			}
		)
		doc.insert()
		doc.submit()
		return doc.name

	def options(self):
		return reg.options_for(self.student)

	def test_a_closed_window_offers_nothing(self):
		self.period.is_open = 0
		self.period.save()
		frappe.clear_cache(doctype="Registration Period")
		self.assertEqual(self.options()["state"], "closed")

	def test_an_open_window_offers_the_next_block(self):
		result = self.options()
		self.assertEqual(result["state"], "open")
		self.assertEqual(result["block"], 4)
		self.assertEqual(result["program"], PROGRAM.format(4))

	def test_registering_creates_a_submitted_enrolment(self):
		result = self.options()
		mandatory = [
			row["course"]
			for group in result["groups"]
			for row in group["rows"]
			if row["status"] in reg.MANDATORY
		]

		created = reg.register_student(self.student, mandatory, AGREED, SIGNED)
		self.assertTrue(created["enrollments"])

		enrollment = frappe.get_doc("Program Enrollment", created["enrollments"][0])
		self.assertEqual(enrollment.docstatus, 1)
		self.assertEqual(
			{row.course for row in enrollment.courses}, set(mandatory) & set(mandatory)
		)
		# Submitting the enrolment is what raises the Course Enrollment records.
		self.assertEqual(
			frappe.db.count("Course Enrollment", {"program_enrollment": enrollment.name}),
			len(enrollment.courses),
		)

	def test_a_student_can_register_as_themselves(self):
		"""The whole point, and the case every other test here misses.

		`permissions.has_permission` returns True immediately for Administrator,
		so a write path can be thoroughly tested and still fail for every real
		user. This one registers through the session endpoint as the student,
		which is the only way that hole shows up.
		"""
		user = frappe.db.get_value("Student", self.student, "user")
		if not user:
			self.skipTest("student has no portal user")

		frappe.set_user(user)
		try:
			options = reg.my_options()
			self.assertEqual(options["state"], "open")
			mandatory = [
				row["course"]
				for group in options["groups"]
				for row in group["rows"]
				if row["status"] in reg.MANDATORY
			]
			created = reg.register(
				json.dumps(mandatory), json.dumps(AGREED), json.dumps(SIGNED)
			)
		finally:
			frappe.set_user("Administrator")

		self.assertTrue(created["enrollments"])
		enrollment = frappe.get_doc("Program Enrollment", created["enrollments"][0])
		self.assertEqual(enrollment.docstatus, 1)
		# Registering elevates only to submit, so the record stays theirs.
		self.assertEqual(enrollment.owner, user)
		self.assertEqual(
			frappe.db.count("Course Enrollment", {"program_enrollment": enrollment.name}),
			len(enrollment.courses),
		)
		# And the elevation must not leak past the call.
		self.assertEqual(frappe.session.user, "Administrator")

	def mandatory_modules(self):
		return [
			row["course"]
			for group in self.options()["groups"]
			for row in group["rows"]
			if row["status"] in reg.MANDATORY
		]

	def test_a_signature_is_required(self):
		# Ticking a box is agreement; the form asks for a mark as well.
		with self.assertRaises(frappe.ValidationError):
			reg.register_student(self.student, self.mandatory_modules(), AGREED, {})

		self.assertFalse(reg.registered_courses(self.student, "2026", self.term))

	def test_only_a_drawn_mark_counts_as_a_signature(self):
		from education_extension.education_extension.doctype.registration_consent import (
			registration_consent as consent_doctype,
		)

		# The field is fed straight from a request, so what arrives has to look
		# like an image and be small enough to be one.
		for value in (
			"scribble",
			"data:text/html;base64,YWJj",
			"data:image/png;base64," + "A" * (consent_doctype.SIGNATURE_LIMIT + 1),
		):
			with self.assertRaises(frappe.ValidationError, msg=value[:40]):
				consent_doctype.validate_signature(value, "Signature")

		consent_doctype.validate_signature(SIGNED["student"], "Signature")

	def test_a_guardian_signature_needs_a_name_and_the_reverse(self):
		# Half a countersignature is not one: a name with no mark is not signed,
		# and a mark with no name cannot be attributed to anybody.
		for half in (
			{"guardian_name": "A Parent"},
			{"guardian": SIGNED["student"]},
		):
			with self.assertRaises(frappe.ValidationError, msg=repr(half)):
				reg.register_student(
					self.student, self.mandatory_modules(), AGREED, dict(SIGNED, **half)
				)

	def test_a_guardian_countersignature_is_recorded(self):
		signatures = dict(
			SIGNED, guardian_name="A Parent", guardian=SIGNED["student"]
		)
		result = reg.register_student(
			self.student, self.mandatory_modules(), AGREED, signatures
		)

		consent = frappe.get_doc("Registration Consent", result["consent"])
		self.assertTrue(consent.student_signature)
		self.assertTrue(consent.signed_by_guardian)
		self.assertEqual(consent.guardian_name, "A Parent")
		self.assertTrue(consent.guardian_signature)

	def test_the_guardian_flag_follows_the_signature(self):
		# Set from whether a guardian actually signed, so the flag cannot claim a
		# countersignature that is not there.
		result = reg.register_student(
			self.student, self.mandatory_modules(), AGREED, SIGNED
		)
		consent = frappe.get_doc("Registration Consent", result["consent"])
		self.assertFalse(consent.signed_by_guardian)
		self.assertFalse(consent.guardian_name)
		self.assertFalse(consent.guardian_signature)

	def test_neither_declaration_can_be_skipped(self):
		# Two separate agreements on the paper form, and neither implies the other:
		# one is about academic standing, the other is consent to process personal
		# information. Half of it is not consent.
		for partial in (
			{},
			{"prerequisites": True},
			{"popia": True},
			{"prerequisites": True, "popia": False},
		):
			with self.assertRaises(frappe.ValidationError, msg=repr(partial)):
				reg.register_student(self.student, self.mandatory_modules(), partial, SIGNED)

		# And nothing was created on the way to refusing.
		self.assertFalse(reg.registered_courses(self.student, "2026", self.term))
		self.assertFalse(
			frappe.db.exists("Registration Consent", {"student": self.student, "docstatus": 1})
		)

	def test_the_consent_records_what_was_shown(self):
		reg.register_student(self.student, self.mandatory_modules(), AGREED, SIGNED)

		name = frappe.db.get_value(
			"Registration Consent",
			{"student": self.student, "academic_term": self.term, "docstatus": 1},
		)
		self.assertTrue(name, "registering must leave a consent on record")

		consent = frappe.get_doc("Registration Consent", name)
		self.assertEqual(consent.docstatus, 1, "a consent record should be immutable")
		self.assertTrue(consent.prerequisites_declared)
		self.assertTrue(consent.popia_consented)
		self.assertTrue(consent.consented_at)

		# Snapshotted, not referenced: amending the wording afterwards must not
		# rewrite what this student agreed to. Compared against the filled version,
		# which is what was put in front of them.
		wording = reg.declarations(self.student)
		self.assertEqual(consent.declaration_text, wording["prerequisites"])
		self.assertEqual(consent.consent_text, wording["popia"])

		# Restored by hand rather than left to the rollback. A Single is cached in
		# redis, which outlives both the transaction and the process, and cleanups
		# run LIFO so one registered here fires before the rollback -- either way
		# the cache would be left holding the amended wording, and every later test
		# and run would read that instead of the real text.
		field = "popia_consent"
		original = frappe.db.get_single_value("Registration Settings", field)
		try:
			frappe.db.set_single_value(
				"Registration Settings", field, "<p>Amended.</p>"
			)
			frappe.clear_cache()
			self.assertNotEqual(
				frappe.db.get_value("Registration Consent", name, "consent_text"),
				"<p>Amended.</p>",
			)
		finally:
			frappe.db.set_single_value("Registration Settings", field, original)
			frappe.clear_cache()

	def test_the_declaration_names_the_student(self):
		"""The paper form has the student write their name, number and the date into
		the sentence. Filled in here, so the text reads as a completed document
		rather than a form with blanks, and so the recorded consent says who agreed
		to it inside the wording itself."""
		wording = reg.declarations(self.student)
		details = frappe.db.get_value(
			"Student",
			self.student,
			["student_name", "custom_id_number", "custom_student_number"],
			as_dict=True,
		)

		for text in wording.values():
			self.assertIn(details.student_name, text)
			self.assertIn(details.custom_id_number or details.custom_student_number, text)

		# Nothing may reach a student with a placeholder still in it.
		for token in ("{student_name}", "{id_number}", "{student_number}", "{date}"):
			for key, text in wording.items():
				self.assertNotIn(token, text, f"{token} unfilled in {key}")

	def test_the_unfilled_wording_keeps_its_placeholders(self):
		# Called without a student it is the template, which is what the settings
		# form edits.
		template = " ".join(reg.declarations().values())
		self.assertIn("{student_name}", template)

	def test_a_name_cannot_carry_markup_into_the_declaration(self):
		# The wording is rendered as HTML, so a value substituted into it is escaped
		# -- a student name is not a place to accept markup from.
		filled = reg.fill_declaration(
			"<p>I, {student_name}, declare.</p>", {"{student_name}": "<script>x</script>"}
		)
		self.assertNotIn("<script>", filled)

	def test_the_consent_records_the_filled_wording(self):
		reg.register_student(self.student, self.mandatory_modules(), AGREED, SIGNED)
		name = frappe.db.get_value(
			"Registration Consent",
			{"student": self.student, "academic_term": self.term, "docstatus": 1},
		)
		consent = frappe.get_doc("Registration Consent", name)
		student_name = frappe.db.get_value("Student", self.student, "student_name")
		self.assertIn(student_name, consent.declaration_text)
		self.assertIn(student_name, consent.consent_text)
		self.assertNotIn("{student_name}", consent.consent_text)

	def test_the_wording_reaches_the_page(self):
		# The page renders what the server will record, so it comes down with the
		# modules rather than being fetched or hard-coded in the frontend.
		options = self.options()
		self.assertIn("declarations", options)
		self.assertTrue(options["declarations"]["prerequisites"].strip())
		self.assertTrue(options["declarations"]["popia"].strip())

	def test_a_consent_cannot_be_recorded_half_agreed(self):
		# Guarding the doctype itself, not just the endpoint: a consent written by
		# any other route has to be a whole one too.
		consent = frappe.get_doc(
			{
				"doctype": "Registration Consent",
				"student": self.student,
				"academic_year": "2026",
				"academic_term": self.term,
				"consented_at": nowdate(),
				"prerequisites_declared": 1,
				"popia_consented": 0,
				"declaration_text": "<p>x</p>",
				"consent_text": "<p>y</p>",
			}
		)
		with self.assertRaises(frappe.ValidationError):
			consent.insert()

	def test_a_students_own_semester_cannot_be_left_out(self):
		result = self.options()
		mandatory = [
			row["course"]
			for group in result["groups"]
			for row in group["rows"]
			if row["status"] in reg.MANDATORY
		]
		with self.assertRaises(frappe.ValidationError):
			reg.register_student(self.student, mandatory[:-1], AGREED, SIGNED)

	def test_an_off_semester_module_is_not_listed_at_all(self):
		# Block 4 runs in the second semester, so a failed block 3 module cannot be
		# retaken now and has no business on the page.
		failed = "ANH2303 - Veterinary Laboratory Diagnostics"
		self.remark(failed, "F")

		rows = {
			row["course"]: row
			for group in self.options()["groups"]
			for row in group["rows"]
		}
		self.assertNotIn(failed, rows)

		# And it cannot be smuggled in by a stale or hand-built request.
		with self.assertRaises(frappe.ValidationError):
			reg.register_student(self.student, [failed], AGREED, SIGNED)

	def test_a_blocker_is_named_even_when_it_is_not_on_the_page(self):
		# ANH2403 needs ANH2303, a first-semester module. It stays blocked, and the
		# reason names the module plainly whether or not it is listed.
		self.remark("ANH2303 - Veterinary Laboratory Diagnostics", "F")
		rows = {
			row["course"]: row
			for group in self.options()["groups"]
			for row in group["rows"]
		}
		blocked = rows["ANH2403 - Veterinary Epidemiology"]
		self.assertEqual(blocked["status"], reg.BLOCKED)
		self.assertIn("ANH2303", blocked["blocked_by"])
		self.assertEqual(blocked["reason"], "Not yet passed: ANH2303.")

	def test_nothing_offered_comes_from_the_other_semester(self):
		block = self.options()["block"]
		for group in self.options()["groups"]:
			for row in group["rows"]:
				if row["selectable"]:
					self.assertEqual(
						row["block"] % 2,
						block % 2,
						f"{row['course']} runs in the other semester",
					)

	def test_a_blocked_module_is_refused(self):
		self.remark("ANH2303 - Veterinary Laboratory Diagnostics", "F")
		result = self.options()
		rows = {r["course"]: r for g in result["groups"] for r in g["rows"]}
		blocked = [c for c, r in rows.items() if r["status"] == reg.BLOCKED]
		if not blocked:
			self.skipTest("no blocked module for this student")

		mandatory = [c for c, r in rows.items() if r["status"] in reg.MANDATORY]
		with self.assertRaises(frappe.ValidationError):
			reg.register_student(self.student, mandatory + blocked[:1], AGREED, SIGNED)

	def test_registering_twice_is_refused_and_the_record_is_shown(self):
		result = self.options()
		mandatory = [
			row["course"]
			for group in result["groups"]
			for row in group["rows"]
			if row["status"] in reg.MANDATORY
		]
		reg.register_student(self.student, mandatory, AGREED, SIGNED)

		# Once registered the page becomes a record, not another offer -- and the
		# block calculation must not read the new enrolment as progress.
		after = self.options()
		self.assertEqual(after["state"], "registered")
		self.assertEqual(len(after["modules"]), len(mandatory))

		with self.assertRaises(frappe.ValidationError):
			reg.register_student(self.student, mandatory, AGREED, SIGNED)

	def registered_provisionally(self):
		"""Register with one prerequisite pending, and return the provisional set."""
		self.remark("ANH1204 - Animal Disease I", "P")
		self.supp_course = "ANH2304 - Animal Diseases II (Non-Infectious Diseases)"
		self.remark(self.supp_course, "SUPP")

		result = self.options()
		rows = {r["course"]: r for g in result["groups"] for r in g["rows"]}
		mandatory = [c for c, r in rows.items() if r["status"] in reg.MANDATORY]
		provisional = [c for c, r in rows.items() if r["status"] == reg.PROVISIONAL]
		self.assertTrue(provisional, "expected a provisional module to test with")

		reg.register_student(self.student, mandatory, AGREED, SIGNED)
		return provisional

	def settle_supplementary(self, code):
		doc = frappe.get_doc(
			{
				"doctype": "Supplementary Academic Remark",
				"student": self.student,
				"course": self.supp_course,
				"academic_year": "2026",
				"academic_term": self.previous_term,
				"supp_remark": code,
			}
		)
		doc.insert()
		doc.submit()
		return doc

	def test_a_provisional_row_is_marked_with_what_it_waits_on(self):
		provisional = self.registered_provisionally()
		rows = reg.provisional_rows(self.student)
		self.assertEqual({row.course for _enrollment, row in rows}, set(provisional))
		for _enrollment, row in rows:
			self.assertTrue(row.custom_provisional_on, "should name the outstanding result")

	def test_nothing_moves_while_the_result_is_outstanding(self):
		self.registered_provisionally()
		self.assertEqual(
			reg.resolve_provisional_registrations(self.student),
			{"cleared": 0, "removed": 0, "reported": 0},
		)

	def test_a_passed_supplementary_clears_the_provisional_mark(self):
		provisional = self.registered_provisionally()
		self.settle_supplementary("PS")

		tally = reg.resolve_provisional_registrations(self.student)
		self.assertEqual(tally["cleared"], len(provisional))
		self.assertEqual((tally["removed"], tally["reported"]), (0, 0))
		self.assertEqual(reg.provisional_rows(self.student), [])

	def test_a_failed_supplementary_removes_the_module_and_tells_the_student(self):
		provisional = self.registered_provisionally()
		self.settle_supplementary("FS")

		tally = reg.resolve_provisional_registrations(self.student)
		self.assertEqual(tally["removed"], len(provisional))

		still_registered = reg.registered_courses(self.student, "2026", self.term)
		for course in provisional:
			self.assertNotIn(course, still_registered)
			self.assertFalse(
				frappe.db.exists("Course Enrollment", {"student": self.student, "course": course}),
			)

		user = frappe.db.get_value("Student", self.student, "user")
		self.assertTrue(
			frappe.db.exists("Notification Log", {"for_user": user, "type": "Alert"}),
			"the student must be told a module was removed",
		)

	def test_nothing_is_removed_once_the_window_has_closed(self):
		provisional = self.registered_provisionally()
		self.settle_supplementary("FS")

		frappe.db.set_value(
			"Registration Period", self.period.name, "last_date_to_register", add_days(nowdate(), -1)
		)
		frappe.clear_cache(doctype="Registration Period")

		tally = reg.resolve_provisional_registrations(self.student)
		self.assertEqual(tally["reported"], len(provisional))
		self.assertEqual(tally["removed"], 0)

		# Left standing, and flagged so the registrar can find it.
		still_registered = reg.registered_courses(self.student, "2026", self.term)
		for course in provisional:
			self.assertIn(course, still_registered)

		flagged = frappe.db.sql(
			"""select count(*) from `tabProgram Enrollment Course` pec
			join `tabProgram Enrollment` pe on pe.name = pec.parent
			where pe.student = %s and pec.custom_needs_review = 1""",
			self.student,
		)[0][0]
		self.assertEqual(flagged, len(provisional))

	def test_resolution_is_idempotent(self):
		self.registered_provisionally()
		self.settle_supplementary("PS")
		reg.resolve_provisional_registrations(self.student)
		self.assertEqual(
			reg.resolve_provisional_registrations(self.student),
			{"cleared": 0, "removed": 0, "reported": 0},
		)


class TestRegistrationPeriod(IntegrationTestCase):
	def test_a_window_cannot_close_before_it_opens(self):
		if not frappe.db.exists("Academic Term", "2026 (First Semester 2026)"):
			self.skipTest("curriculum terms not on this site")
		frappe.db.delete("Registration Period", {"academic_term": "2026 (First Semester 2026)"})
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{
					"doctype": "Registration Period",
					"academic_term": "2026 (First Semester 2026)",
					"opens_on": nowdate(),
					"last_date_to_register": add_days(nowdate(), -1),
				}
			).insert()


def run_tests(verbosity=2):
	"""Run these from a console, since bench run-tests cannot bootstrap this site."""
	suite = unittest.TestSuite()
	loader = unittest.TestLoader()
	for case in (
		TestRegistrationRules,
		TestPrerequisiteGraph,
		TestRegistrationFlow,
		TestRegistrationPeriod,
	):
		suite.addTests(loader.loadTestsFromTestCase(case))
	return unittest.TextTestRunner(verbosity=verbosity).run(suite)
