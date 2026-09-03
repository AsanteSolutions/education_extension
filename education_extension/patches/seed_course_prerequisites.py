"""Seed the prerequisite graph for the Diploma in Animal Health.

Until now the rules lived only in a document. Registration has to enforce them,
so they are recorded against each Course as `custom_prerequisites` rows and this
patch loads them once.

Two codes in the source document match no Course: OCAH2301 (Occupational
Communication II) is ANH2305 here, and ANS2301 (Animal Breeding and Genetics) is
ANS2302. The server naming is authoritative, so ALIASES maps the document onto
it -- and because both codes also appear inside other modules prerequisite
lists, the mapping is applied on every lookup rather than to the two rows that
define them.

The Year 3 lists are the whole preceding curriculum, so they are written as
_through(block) rather than typed out; the rows stored are still explicit, so
later curriculum changes cannot silently reinterpret them.

Only a Course whose table is empty is seeded. That makes the patch idempotent and
means it can never overwrite a rule someone has since corrected by hand.

NOTE: eligibility is only as complete as this graph. Codes that fail to resolve
are reported rather than raising, so a migrate is never blocked by curriculum
drift -- run verify() to assert the graph is whole on a given site.
"""

import re

import frappe
from frappe.modules.utils import sync_customizations

# Module codes encode placement: the second digit is the semester block.
BLOCKS = {
	1: ["ANH1101", "ANH1102", "CLT1101", "OCAH1101", "ANS1101", "ANS1102", "AQW1101"],
	2: ["ANH1201", "ANH1202", "ANH1203", "ANH1204", "ANH1205", "ANS1201"],
	3: ["OCAH2301", "ANH2302", "ANH2303", "ANH2304", "PAN2301", "AEC2301", "AEC2302", "ANS2301"],
	4: ["ANH2401", "ANH2402", "ANH2403", "ANH2404", "ANH2405", "ANH2406"],
	5: ["ANH3501", "ANH3503", "ANH3504", "ANH3505", "ANH3506", "ANH3507"],
	6: ["ANH3601", "ANH3602"],
}

# Document code -> the code this site actually uses.
ALIASES = {
	"OCAH2301": "ANH2305",
	"ANS2301": "ANS2302",
}

CODE = re.compile(r"([A-Z]{3,4}\d{4})")

PREREQUISITE = "Prerequisite"
COREQUISITE = "Co-requisite"


def _through(block):
	"""Every module up to and including `block`, in curriculum order."""
	codes = []
	for number in range(1, block + 1):
		codes.extend(BLOCKS[number])
	return codes


# Modules absent from this table -- all of block 1, plus ANS1201, PAN2301,
# ANS2301 and ANH3506 -- carry no prerequisites in the source document.
PREREQUISITES = {
	"ANH1201": ["ANH1101"],
	"ANH1202": ["ANH1101"],
	"ANH1203": ["ANH1101"],
	"ANH1204": ["ANH1101"],
	"ANH1205": ["ANS1101", "ANS1102"],
	"OCAH2301": ["OCAH1101"],
	"ANH2302": ["ANH1101", "ANH1202", "ANH1205"],
	"ANH2303": ["ANH1202", "ANH1203", "ANH1205"],
	"ANH2304": ["ANH1204"],
	"AEC2301": ["ANS1101", "ANS1102", "ANS1201"],
	"AEC2302": ["ANS1101", "ANS1102", "ANS1201"],
	"ANH2401": ["ANH1201", "ANH1202", "ANH1203", "ANH1205"],
	"ANH2402": ["ANH1204", "ANH2304"],
	"ANH2403": ["CLT1101", "ANH1204", "ANH2303", "ANH2304"],
	"ANH2404": ["ANH1101", "ANH1202", "ANH1204", "ANH2302", "ANH2303", "ANH2304"],
	"ANH2405": ["OCAH1101"],
	"ANH2406": ["ANH1101", "ANH1201", "ANH1204", "ANH2304", "PAN2301"],
	"ANH3501": _through(4),
	"ANH3503": _through(4),
	"ANH3504": _through(4),
	"ANH3505": _through(4),
	"ANH3507": _through(4),
	"ANH3601": _through(5),
	"ANH3602": _through(5),
}

# Taken alongside rather than before. Only ANH1205 has any.
COREQUISITES = {
	"ANH1205": ["ANS1201", "ANH1204"],
}


def execute():
	# Custom fields declared in custom/*.json are synced after patches run, so a
	# patch that needs one has to apply it itself or it writes into nothing.
	sync_customizations("education_extension")
	frappe.reload_doc("education_extension", "doctype", "course_prerequisite")

	by_code = course_by_code()
	if not by_code:
		# No coded Courses: a site that does not carry this curriculum.
		return

	unresolved = set()
	seeded = rows_written = already_set = 0

	for code in sorted(set(PREREQUISITES) | set(COREQUISITES)):
		name = by_code.get(ALIASES.get(code, code))
		if not name:
			unresolved.add(code)
			continue

		course = frappe.get_doc("Course", name)
		if course.get("custom_prerequisites"):
			already_set += 1
			continue

		for other, kind in _wanted_rows(code):
			other_name = by_code.get(ALIASES.get(other, other))
			if not other_name:
				unresolved.add(other)
				continue
			course.append("custom_prerequisites", {"course": other_name, "kind": kind})

		if not course.get("custom_prerequisites"):
			continue

		course.flags.ignore_permissions = True
		course.save()
		seeded += 1
		rows_written += len(course.custom_prerequisites)

	frappe.db.commit()

	print(
		"Seeded {0} rows across {1} courses ({2} already had rules)".format(
			rows_written, seeded, already_set
		)
	)
	for code in sorted(unresolved):
		print("  UNRESOLVED: no Course on this site for {0}".format(code))


def _wanted_rows(code):
	"""(other code, kind) pairs for one module, prerequisites before co-requisites."""
	rows = [(other, PREREQUISITE) for other in PREREQUISITES.get(code, ())]
	rows.extend((other, COREQUISITE) for other in COREQUISITES.get(code, ()))
	return rows


def course_by_code():
	"""Module code -> Course docname. Courses here are named "CODE - Title"."""
	by_code = {}
	for name in frappe.get_all("Course", pluck="name"):
		match = CODE.match(name)
		if match:
			by_code[match.group(1)] = name
	return by_code


def verify():
	"""Codes referenced by this patch that no Course on this site can satisfy.
	Empty means the seeded graph is whole."""
	by_code = course_by_code()
	referenced = set(PREREQUISITES) | set(COREQUISITES)
	for others in list(PREREQUISITES.values()) + list(COREQUISITES.values()):
		referenced.update(others)
	return sorted(c for c in referenced if not by_code.get(ALIASES.get(c, c)))
