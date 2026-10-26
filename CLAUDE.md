# education_extension

A Frappe/ERPNext **v16** app for TARDI (Tsolo Agriculture and Rural Development
Institute). It extends the `education` app rather than replacing it: marking,
registration, academic standing, the printed progress report, and a Vue student
portal. Working branch is `version-16`; `main` is the PR target.

Bench apps alongside it: `frappe`, `erpnext`, `education`, `lms`, `hrms`,
`payments`, `lms_extension`, `asante_hrms_extension`.

---

## Run the tests

**`bench run-tests` cannot bootstrap this site** (overlapping Fiscal Year), so
every suite exposes a `run_tests()` you call yourself. The whole set:

```python
# ~/AsanteHRMS/sites, with ~/AsanteHRMS/env/bin/python
import frappe
frappe.init(site="hrms.localhost"); frappe.connect(); frappe.set_user("Administrator")
import importlib
for name in ["test_academic_standing", "test_api", "test_dashboard", "test_desk",
             "test_marking", "test_patches", "test_progress_report",
             "test_registration", "test_registration_forms"]:
    r = importlib.import_module("education_extension.education_extension." + name).run_tests(verbosity=0)
    print(name, r.testsRun, len(r.failures), len(r.errors))
```

~331 tests, and they should all pass. Prefer this **plain-python runner over
`bench console`**: the console runs each top-level statement as its own IPython
cell, so a function or lambda defined in one cell cannot see names from another
and you get spurious `NameError`s. If you do use the console, keep everything
inside one statement or expect that trap.

A doctype's own `test_*.py` under `doctype/<name>/` is where Frappe looks but
never runs here; the runnable siblings live in `education_extension/`. If you
add a test class, add it to that module's `run_tests()` tuple or it never runs.

`testing.py` has `needs_education_app(case)` and `needs_doctype(case, *names)`
for skipping where a site lacks the fixtures.

## The site is a copy of production

`hrms.localhost` holds **real student records**. It is disposable and refreshed
from production, so probing it is fine and expected — but anything that writes
needs `frappe.db.rollback()`, and anything destructive deserves a look at the
target first. Checking a fix against real data is normal practice here and has
repeatedly caught things tests did not.

---

## Layout

```
education_extension/
  education_extension/          # the module
    registration.py             # what a student may register for, and the write
    marking.py                  # marks, sittings, remark codes, grades payload
    academic_standing.py        # the exclusion rule and the registrar override
    dashboard.py                # registrar charts + REGISTRAR_ROLES/registrar_only
    registration_forms.py       # the countersigning queue
    desk.py                     # copies this app's cards onto the Education page
    lms_sync.py                 # queued mirroring into the LMS
    student_permissions.py      # confines students to their own rows
    api.py                      # portal session -> Student
    testing.py                  # test skip helpers
    test_*.py                   # the runnable suites
    doctype/ report/ page/ workspace/
  patches/                      # listed in patches.txt, run once per site
  public/js/registration_desk.js  # shared desk script (app_include_js)
frontend/                       # Vue 3 + frappe-ui student portal
```

**Portal** (`frontend/`): pages Schedule, Grades, Registration, Fees,
Attendance; stores session/student/user. `yarn build` outputs to
`education_extension/public/frontend/`, which is **gitignored** — a portal
change is not deployed until someone builds it.

**Desk JS** is different: `/assets/education_extension` is a symlink to
`public/`, and Frappe only consults the built asset manifest for paths
containing `.bundle.`, so `registration_desk.js` needs **no `bench build`**.

---

## Domain vocabulary

- **Block / semester** — a programme is "… Semester N"; the block is N. Modules
  carry over only into the same-parity semester (`carry_over_blocks`).
- **Sitting** — `Main`, `Supplementary`, `Aegrotat`, on `custom_sitting`.
  `marking.sitting_of()` is the **only** authority: it reconciles the field with
  the older `AEGRO…` group-name convention. Never re-derive a sitting elsewhere.
- **Remark codes** — `P PD C PS PSE` pass, `SUPP AEGRO` pending, the rest fail.
  Registration reads the **code**, not a recomputed mark, so it stays
  independent of how marks happen to be calculated.
- **Provisional registration** — a module taken while a result is outstanding.
  The nightly `resolve_provisional_registrations` settles them.
- **Registration Period** — a window; several can be open at once for different
  programmes (`open_periods`).

## Rules the code already follows

- **An approved Course Mark Sheet is the record for the marks it carries.**
  Read marks through `marking.get_assessment_results()` / `get_sheet_marks()`,
  never by querying `Assessment Result` directly — that misses sheet-marked
  results, and has caused this bug three separate times.
- **One home per constant.** `COURSEWORK` in `course_mark_scheme`, `SUPP_GROUP`
  in `student_progress_report`, the sittings in `marking`. Import, don't restate.
- **The reason for missing data is recorded, not guessed.** A module with no
  results is only mentioned to a student where a `Course Results Notice` exists.
- **Students are confined by User Permissions** on Student
  (`student_permissions.py`) — not `permission_query_conditions`, not `if_owner`.
  `frappe.get_all` **bypasses** permissions; `frappe.get_list` checks them.
  Portal endpoints take the student from the session, never from the caller.
- **Comments say why, not what.** Most explain a bug that is no longer visible.
  Keep them when you touch the code; they are the reason it is shaped that way.

## Gotchas that have bitten repeatedly

- On a **developer_mode** site, saving a standard record (Workspace, Workspace
  Sidebar, Desktop Icon) **exports it back over the owning app's file**, and
  `delete_doc` deletes the file. `desk._without_writing_to_the_source_tree()`
  exists for this — any test or hook touching those must use it.
- `git checkout -- <file>` and `git stash` revert to HEAD and **destroy
  uncommitted work**. To compare against the old version, use
  `git show HEAD:<path> > /tmp/old.py` and import it; back up before restoring.
- `round_half_up()` returns a **string**. It is defined in
  `doctype/student_progress_report/`, not in `marking`, which imports it.
- `maximum_score` is an optional Float, so unset stores as `0`, not `None`.
- `frappe.parse_json` raises on `''`; use `frappe.utils.sbool` for HTTP booleans.
- A `%` in a raw `frappe.db.sql` string is a format placeholder.
- `insert()` fires `after_insert` **and** `on_update`; `get_doc_before_save()`
  is `None` on an insert.
- Frappe records patches as already run on a **fresh install**, so a one-shot
  patch never fires there — put anything that must happen on both in
  `after_install` and `after_migrate`.

---

## Working style that fits this repo

Changes here are expected to come with evidence, not just passing tests:

1. **Reproduce first.** Confirm the defect against real data or the old code
   before changing anything — several reported problems turned out to be
   correct behaviour, and one finding's stated cause was wrong.
2. **Negative control every test.** Neutralise the fix (stub the new function,
   or import the pre-fix module from `git show HEAD:…`) and confirm the test
   fails. Tests here have passed for the wrong reason more than once, usually by
   rebuilding the logic instead of calling it.
3. **Say what you left out.** Partial scope is fine if it is stated.

## Deploying

- `bench migrate` for new doctypes and patches.
- `cd frontend && yarn build` for any portal change (assets are gitignored).
- No `bench build` needed for the desk script.

## Triage backlog

`code-review-findings.md` at the repo root is **gitignored** but kept in the
working tree: 60 review findings in 7 tiers, with VERIFIED/REFUTED/FIXED marks
and what the evidence was. Tiers 2–7 are complete. Still open: **1.2** (the fees
payment dialog charges a different invoice than the one on screen) and **3.5**
(a never-attempted module has no route back through the portal).
