# For administrators

Setting the add-on up, keeping it running, and understanding the parts that
work without anyone touching them.

## Installing and updating

It is a Frappe app. Install it onto the site alongside `education`, then:

```
bench --site <yoursite> migrate
```

Migrating applies any pending **patches** — one-off scripts that bring the
database up to date. They are safe to re-run; each checks whether its work has
already been done.

| Patch | What it does |
|---|---|
| `convert_remark_codes` | Normalises existing remark text (`Passed`, `Pass`…) to the legend codes (`P`). Anything it cannot recognise is reported and left alone. |
| `seed_course_prerequisites` | Loads the prerequisite graph for the Diploma in Animal Health. Skips any course that already has prerequisites set. |
| `seed_registration_declarations` | Loads the declaration and POPIA wording from the college's paper form. |
| `move_lms_sync_into_the_app` | Creates the service account the LMS sync jobs run as, and reports any old Server Scripts still enabled. |
| `seed_registrar_name` | Fills in the registrar printed on the Proof of Registration. |
| `confine_students_to_their_own_records` | Gives every existing student a permission limiting them to their own records. |
| `create_course_mark_sheet_workflow` | Creates the mark sheet approval workflow. Leaves an existing one alone, so a site that has tuned it keeps its changes. |
| `set_sitting_on_assessment_results` | Labels historical results with the sitting they belong to. |

Read the migrate output. These patches report what they skipped rather than
passing over it silently — an unresolved remark code or a still-enabled Server
Script is printed, not hidden.

## Publishing results to students

This catches people out, so it is worth stating plainly.

**Approving and releasing a mark sheet does not show anything to students.**
Publication is a separate decision, recorded per semester as a **Progress Report
Issue Date**:

1. Create one for the Academic Year and Term.
2. Set **Issue Date For** to **Standard** (the main sitting).
3. Set **Released to Students At** to the moment students may see the marks.
4. Submit it.

Until that moment passes, the Grades page tells students results have not been
published yet.

**Supplementary results need their own record**, with *Issue Date For* set to
**Supplementary**. Without one, a student's supplementary result stays hidden
while their main result is visible — which reads as a bug and is not one.

The same applies to **Remarking** and **AEGROTAT** sittings.

## Student privacy

Students can only see their own records. This is enforced with a **User
Permission** per student, created automatically:

- when a new Student record is added,
- and moved if the student's portal account is changed.

Anyone holding a staff role — System Manager, Education Manager, Academics User,
Instructor or Moderator — is never confined, so a member of staff who is also a
student does not lose the cross-student view their job needs.

This matters because it constrains **every** record type that refers to a
student: results, remarks, enrolments, consents, fees. Records with no student
on them — courses, the timetable, the academic calendar, LMS content — are not
affected, so nothing legitimate is lost.

> Before this was in place, a signed-in student could list every other student
> record on the site and every assessment result. If you are auditing, that is
> what changed.

## The LMS integration

If the `lms` app is installed, education records and LMS records are kept in
step in both directions:

- a Program Enrollment creates the matching LMS programme membership, and
  removing it removes the membership;
- a Course Enrollment creates the matching LMS course enrolment;
- an LMS Program or LMS Course creates the matching education record.

Three things are worth knowing:

**It runs in the background.** The mirroring is queued rather than done inline,
so if the LMS end fails it does not take down the registration that triggered
it. Registration succeeds; the mirror retries.

**It runs as a service account.** A user called `lms-sync@education-extension.invalid`
holding only the `Moderator` role. It has no password and cannot be signed in
to; it exists solely to be the user a background job runs as. `Moderator` is
exactly the role the LMS checks for, and no more.

**It checks the LMS is there.** With no LMS installed, the jobs do nothing
rather than failing.

If your site previously did this with **Server Scripts**, those must be disabled
— otherwise every enrolment is mirrored twice, and the only symptom is duplicate
LMS members. The `move_lms_sync_into_the_app` patch reports any that are still
enabled but deliberately does not disable them, since that is a decision per
site.

## What runs on its own

**Daily:** a sweep that settles provisional registrations whose results have
since been recorded. This is a backstop — the normal path fires as soon as a
result is submitted. The sweep catches results that settled while the queue was
down, or registrations that became resolvable because a window closed rather
than because anything was marked.

**On every result submitted, corrected or cancelled:** the affected student's
provisional registrations are re-checked. Queued, not inline, so marking a whole
sheet does not pay for it on every row.

**After every migrate:** this app's links are re-applied to the Education
workspace page and sidebar. The education app overwrites those from its own
files on each migrate, so anything added by hand there does not survive;
re-applying is how these links persist.

## Where things appear in the desk

The app ships its own **workspace page**, **sidebar**, **apps-screen tile** and
**desk icon**. All four are shown only to System Manager, Education Manager,
Academics User and Instructor — not a security boundary, since every record
behind them keeps its own permissions, but students hold `Desk User` on a
Frappe site and there is no reason to put any of it in front of them.

The same links are also copied onto the standard Education page, because most
of this work happens alongside the rest of the education module.

## Prerequisites are data, not code

The rule that Module B needs Module A lives in a **Prerequisites** table on the
Course record itself, seeded once by a patch. Each row names a course and a
kind: **Prerequisite** (must be passed first) or **Co-requisite** (may be taken
alongside).

You can edit it directly on any Course — open the course and look for the
Prerequisites section.

This means **a course added after the seed has no prerequisites and is open to
anyone** until you add them. Worth checking when the curriculum changes.

## Running the tests

`bench run-tests` cannot bootstrap this site, so the suites are run from a
console instead:

```
bench --site <yoursite> console
```

```python
from education_extension.education_extension.test_registration import run_tests
run_tests()
```

The same pattern works for `test_marking`, `test_dashboard` and `test_desk`.

## Troubleshooting

**Every student is blocked from every module.**
Almost certainly *When a prerequisite has no result on record* is set to *Treat
as not passed* on a site whose history is incomplete. See
[settings](settings.md#when-a-prerequisite-has-no-result-on-record).

**Students say marks are missing after you approved everything.**
No Progress Report Issue Date for that semester, or its release moment has not
passed yet. If only the supplementary column is missing, that sitting needs its
own record.

**A registration succeeded but nothing appeared in the LMS.**
Check the background queue, and check the service account exists and holds
`Moderator`. The mirror is queued, so a stopped worker means nothing mirrors.

**LMS members are duplicated.**
Both the old Server Scripts and the new jobs are running. Disable the scripts.

**A dashboard card shows a dash.**
The card could not reach its method. Check the error log; this normally means a
rename.

**Links have disappeared from the Education page.**
Run `bench migrate`. The education app overwrites that page from its own files,
and the re-apply happens at the end of a migrate.
