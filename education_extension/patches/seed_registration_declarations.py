"""Seed the registration declarations from the institution's paper form.

Transcribed from the TARDI POPIA consent form, which is what students currently
sign on paper at registration. It lands in Registration Settings rather than in
code so the institution can amend it without a release; each Registration
Consent keeps its own copy of the wording, so amending it never rewrites what
somebody already agreed to.

Only fills a field that is empty, so re-running cannot overwrite an amendment.

The blanks the paper form leaves for a signature are placeholders here --
{student_name}, {id_number}, {student_number} and {date} -- filled in per
student, so the text reads as a completed document rather than a form.

NOTE: clause 6 of the source document ends mid-sentence -- "...will also be
transferred to any statutory body for purposes registration," -- and is
transcribed as it stands rather than completed by guesswork. It needs finishing
by whoever owns the form.
"""

import frappe

PREREQUISITE_DECLARATION = """<p>I, <b>{student_name}</b>, ID number <b>{id_number}</b>, student number
<b>{student_number}</b>, declare that I have met all the pre-requisites of the modules I have
registered for and all the information furnished in this document is correct, and I give the quality
assurance office permission to verify it. I understand that if I have given false information I may be
liable to disciplinary action.</p>"""

POPIA_CONSENT = """<p><b>POPI ACT: CONSENT FORM FOR COLLECTION, STORAGE AND PROCESSING OF PERSONAL
INFORMATION</b></p>
<p>Dear Applicant/Student</p>
<ol>
<li>The Protection of Personal Information Act (POPIA) came into effect on 01 July 2021. Therefore by
virtue of signing the registration form for the semester gives consent to collect, store and process
your personal information for any of the institution’s academic, financial and any other related
purposes, inclusive of any affiliations to statutory bodies, bursary application and reports.</li>
<li>Personal Information collected in the application for your studies and in the duration of your
studies will be processed, stored according to provisions of POPIA and the institution’s record
keeping policy. The institution’s Protection of Personal Information Policy will be made available to
the students upon request and a copy might be obtained from the library.</li>
<li>In a case where an applicant or student fails to give consent to the institution to collect, store
and process their personal information this will render the institution unable to render the necessary
services required from the institution by the individual.</li>
<li>TARDI commits itself to protect the applicant or student information that it has obtained in line
with relevant policies and regulations. Should there be any personal information that is required from
the student by any of the institute’s stakeholders for any academic, financial and any other related
purposes the applicant or student must be made aware of such as well as which information is
needed.</li>
<li>The institution utilizes an applicant or student’s personal information only for the following
instances: processing of application for tuition, bursary, professional body affiliation, practical
trips, extra-mural affiliation, SRC candidacy, registration, tests, examinations, WIL, reports,
statistical purposes, communication, contractual obligations, academic purposes, employment purposes
and any other related purposes inclusive but not limited to disciplinary processes, enquiries,
complaint, requests.</li>
<li>This personal information will be distributed to third parties for purposes of professional body
registration, certification, workplace opportunities, verification of qualification and will also be
transferred to any statutory body for purposes registration,</li>
</ol>
<p>I, <b>{student_name}</b>, ID number <b>{id_number}</b>, student number
<b>{student_number}</b>, declare and confirm that I have given TARDI consent to collect, process,
store and utilize my personal information for any of the above mentioned events. I further state that the
information collected was supplied in a free and fair manner and not at any time did I provide my
personal information under duress and there was no undue influence from any party. Failure to provide
my personal information might result in TARDI and any of its stakeholders being unable to render
services to me, this might affect my academic progress and possibly TARDI’s inability to award me a
qualification.</p>
<p>Agreed on <b>{date}</b>.</p>"""

FIELDS = {
	"prerequisite_declaration": PREREQUISITE_DECLARATION,
	"popia_consent": POPIA_CONSENT,
}


def execute():
	if not frappe.db.exists("DocType", "Registration Settings"):
		return

	filled = []
	for fieldname, text in FIELDS.items():
		if (frappe.db.get_single_value("Registration Settings", fieldname) or "").strip():
			continue
		frappe.db.set_single_value("Registration Settings", fieldname, text)
		filled.append(fieldname)

	if filled:
		frappe.db.commit()
		print("Seeded registration declarations: {0}".format(", ".join(filled)))
