# Settings reference

Every switch this add-on introduces, what it does, and what happens if you get
it wrong. Most of these are set once when the system is first configured.

---

## Registration Settings

The rules the registration page enforces. One record for the whole college.

### When a prerequisite has no result on record

**The most consequential setting here.** A student wants to take Module B,
which needs Module A. The system looks for a recorded outcome on Module A and
finds nothing at all — not a pass, not a fail, nothing. What should happen?

| Option | Behaviour | Choose it when |
|---|---|---|
| **Do not block** *(default)* | Only a recorded *failure* stops a student. A missing result is noted on the row and the student may proceed. | Your results predate this system, or are still being captured. |
| **Treat as not passed** | A missing result blocks, exactly as a failure would. | Every result a student could need is recorded here. |

> Set this to *Treat as not passed* too early and **every student is blocked
> from everything**, because the system has no history to check against. This
> is the single most likely way to make registration appear broken.

### Outstanding Fees Block Registration

Off by default. Turn it on to refuse registration to a student who owes money.

The balance is the outstanding total on their submitted Sales Invoices. If your
college does not raise invoices in this system, every balance is zero and nobody
is ever blocked — turning it on has no effect rather than blocking everyone.

### Tolerance

Only relevant with the above turned on. Balances at or below this amount are
ignored, so a student owing a few rand is not turned away at the door.

### Pre-requisite Declaration / POPIA Consent

The wording students are shown and must agree to at the second step of
registration. Both accept placeholders, filled in per student:

`{student_name}` · `{id_number}` · `{student_number}` · `{date}`

> Amending the wording does **not** alter consents already recorded. Each
> consent keeps its own copy of the text as it stood when the student signed it,
> which is the whole point of recording consent.

### Registrar Name

Printed under the second signature line on the Proof of Registration. Worth
checking when the post changes hands.

### Show Unconfirmed Prerequisites to Students

Off by default, and should normally stay off.

With it on, students are told which of their prerequisites have no result on
record. That is internal detail about how complete your records are, not
anything a student can act on — "no result on record for ANH1201" invites a
query you cannot answer at the counter.

Turn it on to work out why a particular module is being offered or withheld,
then **turn it off again**. It applies to every student while it is on.

---

## Marking Settings

### List Students By

How students are ordered on mark entry grids, and anywhere else a class is shown
in order. Options: **Last Name** (default), **First Name**, **Student Name**,
**Student Number**, **Student ID**.

A surname roll is conventional on a mark sheet, but some colleges work from a
student number, which is why this is a setting rather than a decision baked into
the grid.

---

## Student Progress Report Settings

The two signatures printed at the foot of every progress report. For each:

- **Name** — the person signing.
- **Role** — their title, printed under the name.
- **Signature** — the signature image itself.

---

## Registration Period

Not a global setting — one record per semester. Covered in
[for registrars](for-registrars.md#opening-a-registration-window).

The field worth repeating here is **Last Date to Register**: after it, nothing
about a registration changes by itself. A supplementary result landing later
will not remove a module the student has started attending; the case is flagged
for a person instead.

---

## Progress Report Issue Date

Not a global setting either — one record per semester, per kind of sitting. This
is what makes marks visible to students.

| Field | Meaning |
|---|---|
| **Academic Year / Term** | Which semester it covers. |
| **Issue Date For** | **Standard** (the main sitting), **Supplementary**, **Remarking** or **AEGROTAT**. |
| **Issue Date** | The date printed on the progress report. |
| **Released to Students At** | The moment students may see these marks on the portal. |

Until **Released to Students At** passes, the portal shows nothing for that
sitting — however far through approval the marks are. Approving a mark sheet is
not the same as publishing it.

A supplementary sitting needs its **own** record. With only a *Standard* record
filed, a student's supplementary result stays hidden even though their main
result is visible.

---

## Course Mark Scheme

Per course, per year, rather than a global setting. Covered in
[for lecturers and QA](for-lecturers-and-qa.md#before-any-of-that-the-course-mark-scheme).

The rule to remember: **weightings must total 100%**, and they are shares of the
final mark rather than of their own component.
