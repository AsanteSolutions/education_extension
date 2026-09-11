# For registrars

This page covers running a registration window from beginning to end.

## The short version

1. Check the [settings](settings.md) are how you want them — you normally only
   do this once.
2. Create a **Registration Period** for the semester.
3. Watch the **Registration dashboard** while it runs, and chase from the
   **Registration Status** report.
4. Print **Proof of Registration** for students who ask.
5. Deal with anything in the *needs review* queue after it closes.

## Opening a registration window

Create a **Registration Period**. There is one per semester, and the record is
named after the semester so a second one cannot be made by accident.

| Field | What to put in it |
|---|---|
| **Academic Term** | The semester students are registering *for*. |
| **Academic Year** | Filled in for you from the term. |
| **Opens On** | First day students may register. |
| **Last Date to Register** | Last day. See the warning below. |
| **Open** | Tick to run. Untick to shut the window early without changing the dates. |
| **Programmes** | Leave empty to cover every programme. Fill it in only if you want to open one cohort before another. |

> **The last date matters more than it looks.** It is not only the deadline for
> starting a registration — it is the point after which **nothing about a
> registration changes by itself**. A supplementary result that lands the day
> after will not quietly remove a module a student has already started
> attending. Instead the case is flagged for a person to decide.

Students see the window the moment it opens. There is nothing else to publish.

## Watching it run

Open **Registration Dashboard** from the sidebar. It shows the window currently
open — or, once it closes, the last one that ran, because the chasing work
starts exactly when the window ends.

**The six numbers:**

| Card | Question it answers |
|---|---|
| Students Registered | How many are done. |
| Students Still To Register | How many are due this semester and have not. **This is the number the window is run against.** |
| Days Left To Register | Whether chasing is still worth doing. |
| Provisional Modules | How many registrations depend on a result that has not come back. |
| Modules Needing Review | How many cases the system refused to decide on its own. **This one is a queue — it needs a person.** |
| Consent Forms Signed | Should track the registered count. A gap means a registration exists without the consent that should accompany it. |

Every card is clickable and takes you to the list of students behind it.

**The four charts:**

- **Registration Progress** — registered against still to register.
- **Registration Progress Per Year** — the same split, broken down by year of
  study. This is the one that tells you *where* to go: a first-year cohort that
  is finished and a second-year cohort that has barely started are two different
  problems, and the overall total hides both.
- **Registrations By Programme** — where the cohort went. A programme far below
  the others is usually a prerequisite problem rather than a quiet cohort.
- **Registrations Per Day** — the shape of the window. Expect most of it at the
  end. Registrations dated before the window opened (students enrolled
  administratively rather than by registering themselves) are shown in a bucket
  of their own, so the chart always adds up to the headline number.

Each chart has a filter if you want to look back at a semester that has already
closed. Leave it empty for the current one.

## Chasing the students who have not registered

Open the **Registration Status** report and choose the semester. Every student
is listed with one of three statuses:

- **Not registered** — due to take a semester and has not. Sorted to the top.
- **Registered** — done, with what they took.
- **Not their term** — has no modules due this semester. Nothing to chase.

You can filter by status or by programme. The columns also show how many modules
each student took, how many are provisional, and how many need review.

## Proof of registration

Every registration creates a **Registration Consent** record holding the
student's declarations and their signature. To print proof of study:

1. Open the student's Registration Consent record.
2. Print it using the **Proof of Registration** format.

It prints on the college letterhead with the student's details, their
qualification, the modules they registered for, and signature lines for the
student and the registrar. The registrar's name comes from
[Registration Settings](settings.md).

## After the window closes

Two things can still need you.

### Provisional registrations that resolved themselves

A student who registered on the strength of a pending result is sorted out
automatically when that result is recorded:

- pass → the registration becomes ordinary, silently;
- fail → the module is removed and the student is emailed.

You do not need to do anything for these. The system also sweeps daily in case a
result settled while it was not looking.

### The cases it refused to decide

These are the **Modules Needing Review**, and they are the only part of this
that is genuinely a queue. A case lands here when a prerequisite turns out to
have failed, but:

- the registration window has already closed, or
- the student has already started work on the module.

The system deliberately does not strip a module out from under a student in
either situation. It flags it and leaves it for you. You will find them in the
*Needs Review* column of the Registration Status report, sorted to the top.

## Situations you will meet

**"A student says a module is blocked and they think it should not be."**
Look at the module's row on their registration page — it names the prerequisite
it is waiting on. Usually the earlier module has no recorded pass, either
because marking is not finished or because the remark code was never entered.
Fixing the remark fixes the block.

**"A student cannot see a module that is definitely in their programme."**
Check which semester the module runs in. Modules are only offered in the half of
the year they are taught, so a first-semester module does not appear in a
second-semester registration.

**"A student registered for the wrong thing."**
There is no self-service undo, by design — submitting is final. Amend their
Program Enrollment directly.

**"Registration is open but a student sees it as closed."**
Check the **Open** tick box on the Registration Period, and that today falls
between the two dates. If the period names specific programmes, check theirs is
on the list.
