/**
 * DP and final-mark calculation for the Diploma in Animal Health.
 *
 * Kept free of Vue and of any table/display concern so it can be reasoned about
 * and tested on its own. The same rules exist server-side in
 * education_extension/doctype/student_progress_report/student_progress_report.py
 * (calculate_final_results), which is what the printed report uses — change both
 * together until the calculation moves behind an API.
 */

// Courses examined by theory paper alone: it carries the whole exam portion.
export const NO_PRAC_OR_ORAL_EXAM = [
	'OCAH1101',
	'ANH2305',
	'AEC2301',
	'ANH3503',
	'AEC2302',
	'ANH3507',
	'ANH3506',
]

// Courses with no practical test, so tests and assignments carry the whole DP.
export const NO_PRAC_TEST = ['OCAH1101', 'ANH2305', 'AEC2301', 'AEC2302', 'ANH3507', 'ANH2404']

// Courses examined by theory and practical papers only, with no oral.
export const NO_ORAL_EXAM = ['CLT1101']

// The supplementary (re-sit) exam is reported in its own column and takes no
// part in the DP or the final mark.
export const SUPP_GROUP = 'Supplementary Exam'

// An aegrotat (illness/absence) sitting is recorded by prefixing the normal
// assessment group, e.g. "AEGRO Theory Exam". Mirrors AEGROTAT_GROUP_PREFIX in
// student_progress_report.py, and tolerates the AEGROTAT spelling and a missing
// separator the same way the report does.
export const AEGROTAT_PREFIX = /^AEGRO(?:TAT)?[\s_-]*/i

/** The sitting a result belongs to, as [sitting, isAegrotat]. */
const sittingOf = (row) => {
	const group = (row.assessment_group || '').trim()
	return AEGROTAT_PREFIX.test(group)
		? [group.replace(AEGROTAT_PREFIX, ''), true]
		: [group, false]
}

// What a complete set of results looks like: the marks only show once every
// component is in.
export const NUMBER_OF_TESTS = 2
export const NUMBER_OF_ASSIGNMENTS = 2
export const NUMBER_OF_PRACTICAL_TESTS = 1
export const NUMBER_OF_EXAMS = 3

/** Course codes are matched as substrings of "CODE - Course Name". */
const matchesCourse = (course, codes) => codes.some((code) => course.includes(code))

const groupName = (row) => (row.assessment_group || '').toLowerCase()

/** A result's score as a fraction of its maximum; 0 when there is no maximum. */
export const scoreRatio = (row) => {
	const maximum = parseFloat(row.maximum_score)
	return maximum ? parseFloat(row.total_score) / maximum : 0
}

/** Exam sittings, as opposed to the tests and assignments that make up the DP. */
export const isExamResult = (row) => groupName(row).includes('exam')

/**
 * DP and final mark for one course, from that course's assessment results.
 *
 * Returns raw numbers plus the two completeness flags; formatting and the
 * decision to show '-' belong to the caller. `finalMark` is only meaningful
 * once both flags are true.
 *
 * The DP is worth 50% of the final mark and the exam sittings the other 50%.
 * Where a course has a practical test it takes half the DP, and the written
 * tests and assignments are halved to make room for it.
 */
export function calculateCourseMarks(course, rows) {
	const noPracOrOralExam = matchesCourse(course, NO_PRAC_OR_ORAL_EXAM)
	const noPracTest = matchesCourse(course, NO_PRAC_TEST)
	const noOralExam = matchesCourse(course, NO_ORAL_EXAM)

	// One result per sitting, keeping the first of any duplicates. An aegrotat
	// sitting stands in for the one it prefixes, so the two share a key and the
	// aegrotat mark displaces the normal one when both were captured — the rule
	// the printed report applies.
	const bySitting = new Map()
	for (const row of rows) {
		const [sitting, isAegrotat] = sittingOf(row)
		const kept = bySitting.get(sitting)
		if (kept && !(isAegrotat && !kept.isAegrotat)) continue
		bySitting.set(sitting, { row, isAegrotat })
	}
	const results = [...bySitting.values()].map((entry) => entry.row)

	// ---- DP ----
	let dp = 0
	let tests = 0
	let assignments = 0
	let practicalTests = 0

	for (const row of results.filter((r) => !isExamResult(r))) {
		const group = groupName(row)
		const ratio = scoreRatio(row)

		if (group.includes('practical test')) {
			practicalTests++
			if (!noPracTest) dp += ratio * 50
		} else if (group.includes('test')) {
			tests++
			dp += ratio * 30 * (noPracTest ? 1 : 0.5)
		} else if (group.includes('assignment')) {
			assignments++
			dp += ratio * 20 * (noPracTest ? 1 : 0.5)
		}
	}

	// ---- Exam sittings ----
	let examMark = 0
	let examsDone = 0

	for (const row of results.filter(isExamResult)) {
		const group = groupName(row)
		const ratio = scoreRatio(row)
		examsDone++

		if (noPracOrOralExam) {
			// The theory paper is the whole exam portion, so one sitting completes it.
			examMark += ratio * 50
			examsDone = NUMBER_OF_EXAMS
		} else if (group.includes('theory exam')) {
			examMark += ratio * 40 * 0.5
		} else if (group.includes('practical exam')) {
			// With no oral to sit, the practical absorbs its weight and stands in
			// for that sitting too.
			examMark += ratio * (noOralExam ? 60 : 50) * 0.5
			if (noOralExam) examsDone++
		} else if (group.includes('oral exam')) {
			examMark += ratio * 10 * 0.5
		}
	}

	const examsComplete = examsDone === NUMBER_OF_EXAMS

	return {
		dp,
		// The DP's 50% is only added once the exam portion is complete.
		finalMark: examsComplete ? examMark + dp * 0.5 : examMark,
		dpComplete:
			tests === NUMBER_OF_TESTS &&
			assignments === NUMBER_OF_ASSIGNMENTS &&
			// A course without a practical test has no row to count, so its DP is
			// complete on the tests and assignments alone.
			(noPracTest ? true : practicalTests === NUMBER_OF_PRACTICAL_TESTS),
		examsComplete,
	}
}
