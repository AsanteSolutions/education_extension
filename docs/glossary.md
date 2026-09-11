# Glossary

## Outcome codes

The college's standard legend, as printed on the progress report. QA records one
of these against each result.

The third column matters as much as the second: these codes are what the
registration system reads to decide what a student may take next semester.

| Code | Meaning | Effect on registration |
|---|---|---|
| **P** | Passed (50–74%) | Passed — carries the credit and unlocks what follows |
| **PD** | Passed with Distinction (75–100%) | Passed |
| **C** | Condoned (49%) | **Passed.** Awarding the credit is the point of condoning, so it satisfies a prerequisite like any other pass |
| **F** | Failed (below 40%) | Failed — blocks anything depending on it |
| **FSUB** | Failed Subminimum | Failed |
| **NSM** | No Semester Marks | Failed |
| **DISC** | Discontinued | Failed |
| **SUPP** | Supplementary granted | **Pending** — the outcome is not known yet, so registration may proceed provisionally |
| **AEGRO** | Aegrotat granted | Pending |
| **PS** | Passed Supplementary | Passed |
| **FS** | Failed Supplementary | Failed |
| **PSE** | Passed Special Exam | Passed |
| **FSE** | Failed Special Exam | Failed |

Three groups, then: **passed** (P, PD, C, PS, PSE), **pending** (SUPP, AEGRO),
and **everything else fails**. A module with no code at all is a separate case —
see *When a prerequisite has no result on record* in
[settings](settings.md#when-a-prerequisite-has-no-result-on-record).

Where a student has attempted a module more than once, the **best** outcome
counts.

---

## Terms

**Aegrotat** — a sitting granted to a student who missed the exam for a
documented reason, usually illness. Granted by QA recording the `AEGRO` code,
not by being marked absent.

**Block** — see *Semester*.

**Carry-over** — a module from an earlier semester that was not passed, being
taken again alongside the current semester's work. Only offered in the half of
the year the module is taught in, so a failed first-semester module comes round
again the following first semester, not immediately.

**Condoned** — a mark of 49% allowed to pass. It carries the credit, and
therefore satisfies prerequisites.

**Co-requisite** — a module that must be taken *alongside* another, as opposed
to before it.

**DP** — the semester mark: everything except the exam. Tests, assignments and
practicals, weighted according to the Course Mark Scheme. Shown as *Coursework*
when setting a scheme up.

**Moderation** — an adjustment applied to a whole class at once, either by
scaling every mark (*Linear Scale*) or adding the same amount to everyone
(*Flat Adjustment*). Recorded with a reason; the original marks are kept.

**Prerequisite** — a module that must be passed before another may be taken.
Enforced as a hard rule: a blocked module cannot be registered for.

**Provisional registration** — a registration that depends on a result not yet
recorded. It resolves itself when the result arrives: a pass changes nothing, a
fail removes the module. If the result is too late, or work has already started,
it is flagged for a person instead.

**Semester** (also *block*) — a half-year of study, numbered 1 to 6 across the
three-year diploma. Semesters 1 and 2 are the first year, 3 and 4 the second,
5 and 6 the third. Odd semesters run in the first half of the calendar year,
even semesters in the second.

**Sitting** — which run of an assessment a mark belongs to: **Main**,
**Supplementary** or **Aegrotat**.

**Subminimum** — a minimum required in a particular component regardless of the
overall total. Failing it fails the module (`FSUB`).

**Supplementary** — a second chance at a course, sat as one paper covering the
whole course rather than a re-sit of each assessment. Granted by QA recording
the `SUPP` code. Reported in a column of its own so both attempts stay visible.

---

## Record types

| Record | What it is |
|---|---|
| **Registration Period** | One per semester. The window students may register in. |
| **Registration Consent** | What a student agreed and signed when registering. Also what Proof of Registration is printed from. |
| **Registration Settings** | The rules the registration page enforces. One for the college. |
| **Course Prerequisite** | An entry on a Course saying which module must come first. |
| **Course Mark Scheme** | How a course's final mark is built — which assessments, and what each is worth. One per course per year. |
| **Course Mark Sheet** | The mark entry grid for one course, one semester, one sitting. Travels through the approval workflow. |
| **Mark Change** | A mark changed after approval, with the reason and who approved it. |
| **Marking Settings** | How classes are ordered on grids. One for the college. |
| **Academic Remark** | The outcome code for a student's module in a semester. |
| **Supplementary Academic Remark** | The same, for a supplementary sitting. |
| **Progress Report Issue Date** | When a semester's results are issued and when students may see them. One per semester per sitting. |
| **Student Progress Report** | The tool that produces a student's printed progress report. |
| **Student Progress Report Settings** | The two signatures printed on it. |

## Reports and views

| Name | What it shows |
|---|---|
| **Registration Status** | Every student for a semester: registered, not registered, or not due. The list a registrar chases from. |
| **Course Results** | A course's results for QA to review and record outcome codes against. |
| **Registration Dashboard** | Six numbers and four charts on how a registration window is going. |
| **Proof of Registration** | A printable confirmation of a student's registration, from their Registration Consent. |
