# Education Extension

An extension to the Frappe [Education](https://github.com/frappe/education) app,
built for TARDI (Tsolo Agriculture and Rural Development Institute).

It adds the parts of running a semester that the Education app leaves open:
capturing and moderating marks, letting students register themselves against the
curriculum's own rules, and printing the progress report. It reads and writes
the Education app's records — Student, Course, Program Enrollment, Academic Year
and Term, Assessment Result — rather than keeping its own copies, and will
refuse to install without it.

Requires **Frappe/ERPNext v16**. The working branch is `version-16`.

## What it does

**Marking.** A Course Mark Sheet is the grid a lecturer fills in for one course,
one sitting, built from a Course Mark Scheme that says which assessments count
and for how much. It moves through a workflow — *Awaiting Entry → In Entry →
Submitted for Checking → Checked → Moderated → Approved → Released* — and an
approved sheet becomes the record for the marks it carries. Moderation (linear
or flat) is recorded rather than typed over the marks, and is withdrawn
automatically if the marks underneath it change. A Mark Change records a
correction to an already-submitted mark, with its reason.

**Sittings.** A mark belongs to a Main, Supplementary or Aegrotat sitting. A
supplementary is reported in a column of its own and never folded into the final
mark; an aegrotat paper displaces the assessment it stands in for.

**Results and remarks.** QA files an Academic Remark per student per course from
a fixed legend (`P`, `PD`, `C`, `F`, `SUPP`, `AEGRO`, …), with a separate
Supplementary Academic Remark for a re-sit. A Student Progress Report prints
from those, dated from the Progress Report Issue Date records for the kinds of
sitting it covers.

**Registration.** A Registration Period opens a window for named programmes.
Students register themselves through the portal against the curriculum: their
own semester's modules are compulsory, carry-overs from earlier semesters are
theirs to choose, and prerequisites and co-requisites are enforced. A module
whose result has not landed yet can be taken provisionally, and a nightly job
settles those once it does. Registering captures a signed Registration Consent,
which the registrar countersigns and which prints as the Proof of Registration.

**Academic standing.** An optional rule excludes a student who has failed too
many modules, or too high a proportion of them, over a configurable window. A
registrar can admit an excluded student anyway with a Registration Override —
a record of who allowed it and why, against a snapshot of the standing it was
granted over, not a switch.

**Student portal.** A Vue app at `/student-portal` covering schedule, grades,
registration, fees and attendance.

**LMS mirroring.** Enrolments are mirrored into the Frappe LMS by queued jobs
running as a service account, so a failure there can never block a registration.

## Installing

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch version-16
bench install-app education_extension
```

The Education app must be installed first; Frappe checks this and fails at
install time rather than at the first mark.

## Working on it

Use `pre-commit` for formatting and linting — ruff, eslint, prettier, pyupgrade:

```bash
cd apps/education_extension
pre-commit install
```

### Tests

CI runs `bench run-tests --app education_extension` against a clean test site.
That does not work on a long-lived development site, where the Fiscal Years its
fixtures create overlap the ones already there and the bootstrap fails before
any test runs — so each suite under
`education_extension/education_extension/test_*.py` also exposes a
`run_tests()` you can call directly:

```python
from education_extension.education_extension.test_registration import run_tests
run_tests()
```

Call it from a script against `frappe.init()` / `frappe.connect()` rather than
from `bench console`, which evaluates each statement in its own namespace. Add
new test classes to that module's `run_tests()` tuple, or they will run in CI
and be silently skipped by everyone working locally.

### Portal

```bash
cd frontend
yarn install
yarn dev      # against a running bench
yarn build    # writes to education_extension/public/frontend/
```

Built assets are **gitignored**, so a portal change is not live until someone
builds it. Desk scripts under `education_extension/public/js/` need no build —
they are served through the assets symlink.

## Deploying

```bash
bench migrate                 # doctypes and patches
cd apps/education_extension/frontend && yarn build
bench --site $SITE clear-cache
```

Patches are listed in `education_extension/patches.txt` and run once per site.

## CI

Two GitHub Actions workflows:

- **CI** — installs the app on a fresh site and runs the test suite, on every
  pull request and on pushes to `version-16`.
- **Linters** — [Frappe Semgrep Rules](https://github.com/frappe/semgrep-rules)
  and [pip-audit](https://pypi.org/project/pip-audit/), on every pull request.

Contributors working with Claude Code should read `CLAUDE.md`, which carries the
conventions and the traps this codebase has already fallen into.

## License

MIT
