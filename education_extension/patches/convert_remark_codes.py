"""Normalise stored remark values to the legend codes.

`Academic Remark.remark` and `Supplementary Academic Remark.supp_remark` were
free-text Data fields, so nothing stopped a value like "Passed" being saved
where "P" was meant -- and every reader of these records compares against the
bare code, so such a row silently counts as no code at all. The fields become
Select in the same release; this cleans what is already stored so the constraint
lands over conforming data.

Values are matched case- and whitespace-insensitively, then against a table of
word forms. Anything that still does not resolve is reported rather than
guessed: a remark is a QA judgement, and inventing one is worse than leaving it
visible for someone to fix.

Written with `frappe.db.set_value(..., update_modified=False)` on purpose. These
are submitted documents, and more importantly the progress report derives its
fallback "Date of Issue" from the latest `modified` across a student's results
and remarks (`_last_marks_change`) -- bumping the timestamp here would silently
move the issue date on every report that relies on it.
"""

import frappe

# Frozen here rather than imported: a patch has to keep behaving the way it did
# when it ran, whatever the code around it becomes.
CODES = (
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
)

# Word forms seen or plausibly typed for a code, upper-cased with whitespace
# collapsed. Only unambiguous expansions belong here.
ALIASES = {
	"PASS": "P",
	"PASSED": "P",
	"DISTINCTION": "PD",
	"PASS WITH DISTINCTION": "PD",
	"PASSED WITH DISTINCTION": "PD",
	"CONDONE": "C",
	"CONDONED": "C",
	"FAIL": "F",
	"FAILED": "F",
	"SUBMINIMUM": "FSUB",
	"FAIL SUBMINIMUM": "FSUB",
	"FAILED SUBMINIMUM": "FSUB",
	"NO SEMESTER MARK": "NSM",
	"NO SEMESTER MARKS": "NSM",
	"DISCONTINUE": "DISC",
	"DISCONTINUED": "DISC",
	"SUPPLEMENTARY": "SUPP",
	"AEGROTAT": "AEGRO",
	"PASS SUPPLEMENTARY": "PS",
	"PASSED SUPPLEMENTARY": "PS",
	"FAIL SUPPLEMENTARY": "FS",
	"FAILED SUPPLEMENTARY": "FS",
	"PASS SPECIAL EXAM": "PSE",
	"PASSED SPECIAL EXAM": "PSE",
	"FAIL SPECIAL EXAM": "FSE",
	"FAILED SPECIAL EXAM": "FSE",
}

FIELDS = (
	("Academic Remark", "remark"),
	("Supplementary Academic Remark", "supp_remark"),
)


def execute():
	converted = 0
	unresolved = {}

	for doctype, fieldname in FIELDS:
		if not frappe.db.table_exists(doctype):
			continue

		for row in frappe.get_all(doctype, fields=["name", fieldname]):
			stored = row.get(fieldname)
			code = resolve(stored)

			if code is None:
				unresolved.setdefault((doctype, stored), 0)
				unresolved[(doctype, stored)] += 1
				continue

			if code == stored:
				continue

			frappe.db.set_value(doctype, row.name, fieldname, code, update_modified=False)
			converted += 1

	if converted:
		frappe.db.commit()

	print("Converted {0} remark values to legend codes".format(converted))

	for (doctype, stored), count in sorted(unresolved.items(), key=lambda item: -item[1]):
		print(
			"  UNRESOLVED: {0} row(s) in {1} hold {2!r} -- left as they are".format(
				count, doctype, stored
			)
		)


def resolve(stored):
	"""The legend code `stored` means, or None if it cannot be told."""
	if stored is None:
		return None

	stripped = stored.strip()
	if stripped in CODES:
		return stripped

	# Collapse case and internal whitespace, so " supp " and "No  Semester Marks"
	# both land on their code.
	key = " ".join(stripped.upper().split())
	if key in CODES:
		return key

	return ALIASES.get(key)
