# For lecturers and QA

Marks are entered on a **Course Mark Sheet** — one grid per course per semester,
with students down the side and assessments across the top. The sheet then
travels through several pairs of hands before anyone sees a mark.

## Why there is a workflow at all

The point of the sequence is that **marks can only be changed while the sheet is
with the lecturer**. Everything after that is a review of a fixed set of marks.
If checking or moderation could quietly alter figures, there would be no moment
at which anyone could say what the marks actually were.

```
Awaiting Entry → In Entry → Submitted for Checking → Checked → Moderated → Approved → Released
                    ▲              │                    │          │
                    └──────────────┴────────────────────┴──────────┘
                              "Return for Correction"
```

| State | Who acts | What happens |
|---|---|---|
| **Awaiting Entry** | Lecturer | The sheet exists with its students and assessments, nothing entered. |
| **In Entry** | Lecturer | Marks are being typed. **The only state in which marks can change.** |
| **Submitted for Checking** | QA / Academics | Marks are frozen. Someone checks them against the scripts. |
| **Checked** | QA / Academics | Arithmetic and capture confirmed. |
| **Moderated** | Education Manager | An adjustment has been recorded across the class, if one was needed. |
| **Approved** | Education Manager | Final. These are the marks. |
| **Released** | Education Manager | Cleared for publication. |

A cohort needing no adjustment goes straight from **Checked** to **Approved** —
moderation is not compulsory.

At any review stage the sheet can be sent back with **Return for Correction**,
which puts it in *In Entry* and unlocks the marks again. You are asked for a
reason, and it is stored on the sheet.

## Before any of that: the Course Mark Scheme

A **Course Mark Scheme** says how a course's final mark is built — which
assessments count and how much each is worth.

- Every row is an assessment (Test 1, Assignment, Theory Exam…) with a
  **weighting as a share of the final mark**, not of its own component.
- Each row is either **Coursework** or **Examination**. Coursework is what the
  progress report prints as the **DP** (semester mark).
- **The weightings must total 100%.**
- The scheme belongs to a **year**. Marks keep the scheme they were assessed
  under, so changing next year's weightings never alters a past result.

There can be only one submitted scheme per course per year.

> A course with no submitted scheme still works — the system falls back to the
> older built-in weightings. This lets you convert the college one course at a
> time rather than all at once.

## Entering marks

Open the sheet and use the grid. Each cell is one student's mark for one
assessment, and each has a status:

- **Not Marked** — nothing entered yet. This is not the same as zero.
- **Marked** — a mark has been entered.
- **Absent** — the student did not sit it. Recorded deliberately, so an empty
  cell never has to be interpreted.

The sheet tells you how many marks are still outstanding. That count is what
stops a half-finished sheet going forward.

Sheets are usually created in bulk for a whole semester rather than one at a
time, and are filled with the students enrolled for that course. If students
join late, **Generate Entries** adds the missing rows.

Students are listed by surname by default. If your college works from a student
number instead, that is a setting — see [settings](settings.md).

## Moderation

Moderation adjusts a whole class at once, and is recorded rather than applied by
hand to each mark. Two methods:

- **Linear Scale** — multiply every mark by a factor. A value of `1.05` raises
  everyone by 5% of their own mark.
- **Flat Adjustment** — add the same number of marks to everyone. A value of `4`
  gives everyone four more marks; `-2` takes two away.

Either way a mark is held inside the possible range — scaling cannot push a
strong mark above the maximum, and a flat deduction cannot push a weak one below
zero.

You are asked for a reason, and both the original and the moderated mark are
kept, so the adjustment is always visible rather than baked in. Moderation can
also be cleared, which restores the raw marks.

## QA review and outcome codes

Once the marks are in, the sheet stops being a grid to fill and becomes a set of
results to read. The **QA view** on the sheet shows each student's semester
mark, exam mark and final mark, and lets you record the **outcome code** against
each one.

The codes are the college's standard legend — **P**, **PD**, **C**, **F**,
**SUPP**, **AEGRO** and the rest, all listed in the [glossary](glossary.md).
They are chosen from a list rather than typed, because a typo makes a result
invisible to everything that reads them.

**These codes are not decoration.** They are what the registration system reads
to decide what a student may take next semester. A student with no recorded pass
against a module will be blocked from its follow-on module, however good their
mark was. Recording the code is part of finishing the marking, not an
afterthought.

The same codes can be recorded from the **Course Results** report, which is
often easier when you are working through a whole course in one sitting.

## Re-sittings: supplementary and aegrotat

A re-sitting gets a sheet of its own, because it is a different set of students
sitting a different paper.

- **Supplementary** — one paper covering the whole course, for students QA has
  granted a supplementary by recording the **SUPP** code. It is reported in a
  column of its own rather than replacing the original mark, so both attempts
  remain visible.
- **Aegrotat** — for students who missed the exam with documentation, granted by
  recording the **AEGRO** code.

Only **exams** are sat again. A missed test or assignment simply scores nothing,
because there is no second chance at one.

Entitlement comes from the QA code, not from absence. Being marked absent does
not by itself grant a re-sit — an aegrotat needs documentation, and QA is who
has seen it.

## Changing a mark after approval

Re-marking is not a step in the sequence. It can happen at any time once marks
are out, so it is a document of its own: a **Mark Change**.

It records the student, the course, the assessment, the previous mark, the new
mark, **why**, who requested it and who approved it. Submitting it applies the
new mark wherever that mark is actually stored.

This is the correct way to change an approved mark. Editing the underlying
record leaves no trace of what changed or who decided it.

## When students see any of this

They do not, until someone says so. Approving and releasing a sheet is not
enough on its own — publication is a separate decision, recorded as a
**Progress Report Issue Date** for the semester. See
[for administrators](for-administrators.md#publishing-results-to-students).
