# Education Extension

This is an add-on for the college's ERPNext system. ERPNext already knows about
students, courses, programmes and terms; this add-on covers three jobs it does
not do well enough on its own:

1. **Registration** — students choose and register for their own modules online,
   and the system decides what each of them is allowed to take.
2. **Marking** — marks are entered on a grid, checked, moderated and approved by
   different people, and nothing is published until someone says so.
3. **Reporting** — progress reports, proof of registration, and a dashboard that
   shows how a registration window is going while it is still running.

You do not need to understand the whole thing to use part of it. Start with the
page for your job.

## Where to start

| If you are a… | Read |
|---|---|
| Student, or supporting students | [For students](for-students.md) |
| Registrar or admissions officer | [For registrars](for-registrars.md) |
| Lecturer, QA checker or moderator | [For lecturers and QA](for-lecturers-and-qa.md) |
| Administrator setting the system up | [For administrators](for-administrators.md) |
| Anyone wondering what a setting does | [Settings reference](settings.md) |
| Anyone who has met a code like `FSUB` | [Glossary](glossary.md) |

## How the three parts fit together

They run in a loop, once per semester.

```
   ┌─ Registration window opens ────────────────────────────┐
   │  Students register for modules online.                 │
   │  The system checks prerequisites and fees.             │
   └──────────────────────┬─────────────────────────────────┘
                          │
   ┌──────────────────────▼─────────────────────────────────┐
   │  Teaching happens. Lecturers enter marks on a          │
   │  Course Mark Sheet: entered → checked → moderated →    │
   │  approved → released.                                  │
   └──────────────────────┬─────────────────────────────────┘
                          │
   ┌──────────────────────▼─────────────────────────────────┐
   │  QA records an outcome code against each result         │
   │  (passed, failed, supplementary…). Students see their  │
   │  marks once the term is released.                      │
   └──────────────────────┬─────────────────────────────────┘
                          │
                          └──> those outcomes decide what the
                               student may register for next
                               semester, and the loop repeats.
```

The important connection is the last arrow. **Marking feeds registration.** A
student cannot register for Animal Nutrition II if they have not passed Animal
Nutrition I, and "passed" means a QA checker recorded a pass code against it.
That is why the two halves of this add-on are in one place.

## A note on vocabulary

The system calls each kind of record a **doctype** — a Student is a doctype, a
Course Mark Sheet is a doctype. When this documentation says "create a
Registration Period", it means "add one of those records", the same way you
would add an invoice.

**Semester** and **block** mean the same thing here: a half-year of study.
Semesters run 1 to 6 across a three-year diploma. Semesters 1 and 2 are the
first year, 3 and 4 the second, 5 and 6 the third. Odd-numbered semesters run in
the first half of the year, even-numbered in the second.

## Where this lives in the system

Once installed there is an **Education Extension** tile on the apps screen and
an icon on the desk, which open a page holding everything below:

- **Registration** — Registration Period, Registration Consent, Registration
  Status report, Registration Settings
- **Marking** — Course Mark Sheet, Course Mark Scheme, Mark Change, Course
  Results report, Marking Settings
- **Results and Remarks** — Academic Remark, Supplementary Academic Remark,
  Student Progress Report, Progress Report Issue Date, Student Progress Report
  Settings

The same links also appear on the standard **Education** page, because most of
this work happens alongside the rest of the education module rather than in a
corner of its own.
