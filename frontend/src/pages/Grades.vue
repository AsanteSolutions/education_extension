<template lang="">
	<!-- <div v-if="grades.data?.length > 0">-->
	<div>
		<!--Banner to remove-->
		<div
			class="flex items-center gap-2 border-b border-amber-200 bg-amber-50 px-5 py-3 text-sm text-amber-800"
		>
			<FeatherIcon name="info" class="h-4 w-4 shrink-0" />
			<span>For those taking Occupational Communication I results are still pending.</span>
		</div>
		<!--Banner to remove-->
		<div class="px-5 py-4">
			<Dropdown class="mb-4" :options="allPrograms">
				<template #default="{ open }">
					<Button :label="selectedProgram">
						<template #suffix>
							<FeatherIcon
								:name="open ? 'chevron-up' : 'chevron-down'"
								class="h-4 text-gray-600"
							/>
						</template>
					</Button>
				</template>
			</Dropdown>
			<ListView
				class="h-[250px]"
				:columns="tableData.columns"
				:rows="tableData.rows"
				:options="{
					selectable: false,
					showTooltip: false,
					onRowClick: () => {},
				}"
				row-key="id"
			/>
		</div>
	</div>
	<!-- <div v-else>
    <MissingData message="No grades found" />
  </div> -->
</template>
<script setup>
import { Dropdown, FeatherIcon, ListView, createResource, createListResource } from 'frappe-ui'
import { ref } from 'vue'
import { studentStore } from '@/stores/student'
import { groupBy } from '@/utils'

import MissingData from '@/components/MissingData.vue'

const { getCurrentProgram, getStudentInfo } = studentStore()

let studentInfo = getStudentInfo().value
let currentProgram = getCurrentProgram().value

const allPrograms = ref([])
const selectedProgram = ref('')

const tableData = ref({
	columns: [
		{
			label: 'Course',
			key: 'course',
		},
		/*{
      label: 'Batch',
      key: 'batch',
    },*/
	],
	rows: [],
})

const student_programs = createResource({
	url: 'education.education.api.get_student_programs',
	makeParams() {
		return {
			// student: studentInfo.value?.name
			student: studentInfo.name,
		}
	},
	onSuccess: (response) => {
		let programs = []
		response.forEach((program) => {
			programs.push({
				label: program.program,
				onClick: () => {
					if (selectedProgram.value === program.program) return
					loadProgram(program.program)
				},
			})
		})
		allPrograms.value = programs
		// Fetch grades for the program we actually display, so the table and the
		// dropdown label can never disagree. Default to the latest (last) program.
		loadProgram(programs[programs.length - 1].label)
	},
	auto: true,
})

let student_remarks = []

// The latest Assessment Result response, kept so the table can be rebuilt once
// the remarks arrive (the two resources load independently and either may win).
let latestGrades = null

const remarks = createListResource({
	doctype: 'Academic Remark',
	fields: ['name', 'student', 'remark', 'course', 'academic_year', 'academic_term'],
	filters: {
		student: studentInfo.name,
		docstatus: '1',
	},
	auto: true,
	onSuccess: (response) => {
		// Rebuild from scratch so reloads don't accumulate duplicate remarks.
		student_remarks = response.map((remark) => ({
			name: remark.name,
			student: remark.student,
			remark: remark.remark,
			course: remark.course,
			academic_year: remark.academic_year,
			academic_term: remark.academic_term,
		}))
		// Remarks may have arrived after the grades were already rendered with
		// '-' placeholders — rebuild the table now that we have them.
		buildTable()
	},
})

let student_supp_remarks = []

// Supplementary Academic Remark mirrors Academic Remark. Most students have
// none, so this simply yields an empty list and no supplementary columns appear.
const supp_remarks = createListResource({
	doctype: 'Supplementary Academic Remark',
	// The remark column on this doctype is named `supp_remark`, not `remark`.
	fields: ['name', 'student', 'supp_remark', 'course', 'academic_year', 'academic_term'],
	filters: {
		student: studentInfo.name,
		docstatus: '1',
	},
	auto: true,
	onSuccess: (response) => {
		student_supp_remarks = response.map((remark) => ({
			name: remark.name,
			student: remark.student,
			remark: remark.supp_remark,
			course: remark.course,
			academic_year: remark.academic_year,
			academic_term: remark.academic_term,
		}))
		buildTable()
	},
})

const grades = createListResource({
	doctype: 'Assessment Result',
	fields: [
		'name',
		'student_group',
		'course',
		'assessment_group',
		'total_score',
		'maximum_score',
		'grade',
		'custom_assessment_type',
		'academic_year',
		'academic_term',
	],
	filters: {
		student: studentInfo.name,
		program: currentProgram.program,
		docstatus: '1',
	},
	pageLength: 256,
	transform: () => {},

	onSuccess: (response) => {
		latestGrades = response
		buildTable()
	},
	// Not auto: the first fetch is triggered by loadProgram() once we know which
	// program is selected, avoiding an initial fetch for the wrong program.
	auto: false,
})

// Selects a program: syncs the dropdown label and refetches grades for it, so
// the displayed results always match the selection.
const loadProgram = (program) => {
	selectedProgram.value = program
	grades.update({
		filters: {
			student: studentInfo.name,
			program,
			docstatus: '1',
		},
	})
	grades.reload()
}

// Builds the grades table from the latest Assessment Result response and the
// currently-loaded remarks. Safe to call from either resource's onSuccess: it
// re-runs whenever grades or remarks arrive, resolving the load-order race that
// previously left remarks showing '-' until the next visit.
const buildTable = () => {
	const response = latestGrades
	if (!response) return

	// Clear previous data
	tableData.value.rows = []
	tableData.value.columns = [
		{
			label: 'Course',
			key: 'course',
		},
	]

	const numberOfAssignments = 2
	const numberOfTests = 2
	const numberofPracticalTests = 1
	const numberOfExams = 3

	// Supplementary Exam is a separate assessment group; keep it out of the DP /
	// final-mark computation and surface it in its own column instead. Most
	// students have none, so these lookups are usually empty.
	const SUPP_GROUP = 'Supplementary Exam'
	const suppByCourse = {}
	response.forEach((r) => {
		if (r.assessment_group === SUPP_GROUP) suppByCourse[r.course] = r
	})
	const mainRows = response.filter((r) => r.assessment_group !== SUPP_GROUP)

	let conductedExams = groupBy(mainRows, (row) => row.assessment_group)
	let exams = Object.keys(conductedExams)

	// Sort exams to ensure theory, practical, and oral exams are at the end of the columns
	exams.sort((a, b) => {
		const hasA = a.includes('Exam')
		const hasB = b.includes('Exam')

		if (hasA && !hasB) return 1
		if (!hasA && hasB) return -1
		return 0
	})

	let courses = groupBy(mainRows, (row) => row.course)

	// Only add the supplementary columns when some course in view actually has a
	// supplementary exam result or remark (most students have neither).
	const suppRemarkCourses = new Set(student_supp_remarks.map((r) => r.course))
	const hasSupp = Object.keys(courses).some((c) => suppByCourse[c] || suppRemarkCourses.has(c))

	updateColumns(exams, hasSupp)
	Object.keys(courses).forEach((course) => {
		let row = {}
		// ListView keys rows by `row-key="id"`; without a unique id every
		// row keys to `undefined`, so Vue can't diff them and the table fails
		// to re-render when switching programs. Course code is unique per row.
		row.id = course
		row.course = course
		row.remark = '-'
		let dp = 0.0
		let final_mark = 0.0
		let assignments = 0
		let tests = 0
		let practical_tests = 0
		let number_of_exams = 0
		let rowYear = null
		let rowTerm = null
		exams.forEach((exam) => {
			let examData = conductedExams[exam].find((row) => row.course === course)
			;({ dp, final_mark, tests, assignments, practical_tests, number_of_exams } =
				calculateDPAndFinalMark(
					examData,
					tests,
					assignments,
					dp,
					final_mark,
					practical_tests,
					number_of_exams,
				))
			if (examData) {
				rowYear = examData.academic_year
				rowTerm = examData.academic_term
				row.remark =
					student_remarks.find(
						(r) =>
							r.course === course &&
							r.academic_year === examData.academic_year &&
							r.academic_term === examData.academic_term,
					)?.remark ||
					row.remark ||
					'-'
			}
		})
		row.dp =
			assignments == numberOfAssignments &&
			tests == numberOfTests &&
			practical_tests == numberofPracticalTests
				? `${Math.round(dp)}%`
				: '-'
		row.final_mark =
			row.dp !== '-' && number_of_exams == numberOfExams ? `${Math.round(final_mark)}%` : '-'

		// Supplementary exam result (as a percentage) and supplementary remark,
		// matched to the same course/year/term. Both fall back to '-' when absent.
		const supp = suppByCourse[course]
		row.supp_exam =
			supp && parseFloat(supp.maximum_score)
				? `${Math.round((parseFloat(supp.total_score) / parseFloat(supp.maximum_score)) * 100)}%`
				: '-'
		const suppYear = supp ? supp.academic_year : rowYear
		const suppTerm = supp ? supp.academic_term : rowTerm
		row.supp_remark =
			student_supp_remarks.find(
				(r) =>
					r.course === course &&
					r.academic_year === suppYear &&
					r.academic_term === suppTerm,
			)?.remark || '-'

		tableData.value.rows.push(row)
	})
}

const updateColumns = (exams, hasSupp) => {
	tableData.value.columns.push({
		label: 'DP',
		key: 'dp',
	})
	tableData.value.columns.push({
		label: 'Final Mark',
		key: 'final_mark',
	})
	tableData.value.columns.push({
		label: 'Remark',
		key: 'remark',
	})
	// Only shown when a student actually has supplementary data.
	if (hasSupp) {
		tableData.value.columns.push({
			label: 'Supp Exam',
			key: 'supp_exam',
		})
		tableData.value.columns.push({
			label: 'Supp Remark',
			key: 'supp_remark',
		})
	}
}

/***
 * Calculates the DP and Final Mark for a given exam data and updates the respective variables accordingly.
 */
const calculateDPAndFinalMark = (
	examData,
	tests,
	assignments,
	dp,
	final_mark,
	practical_tests,
	number_of_exams,
) => {
	const noPracOrOralExam = [
		'OCAH1101',
		'ANH2305',
		'AEC2301',
		'ANH3503',
		'AEC2302',
		'ANH3507',
		'ANH3506',
	]
	const noPracTest = ['OCAH1101', 'ANH2305', 'AEC2301', 'AEC2302', 'ANH3507', 'ANH2404']
	const noOralExam = ['CLT1101']

	if (examData && examData.assessment_group.toLowerCase().includes('exam')) {
		number_of_exams++
		if (noPracOrOralExam.some((assessment) => examData.course.includes(assessment))) {
			/*
        For courses with no practical or oral exams, the final mark is calculated based on the theory exam alone, 
        which contributes 50% to the final mark.
        The number_of_exams is set to 3 to ensure that the DP contribution is added to the final mark.
       */
			number_of_exams = 3
			final_mark +=
				(parseFloat(examData.total_score) / parseFloat(examData.maximum_score)) * 50.0
		} else if (noOralExam.some((assessment) => examData.course.includes(assessment))) {
			// When Courses have no oral exam theory exams contribute 40% and practical contributes 60% to the exam mark
			// The final mark is calculated based on the contributions of the theory and practical exams, which together contribute 50% to the final mark.
			if (examData.assessment_group.toLowerCase().includes('theory exam')) {
				final_mark +=
					(parseFloat(examData.total_score) / parseFloat(examData.maximum_score)) *
					40.0 *
					0.5
			} else if (examData.assessment_group.toLowerCase().includes('practical exam')) {
				number_of_exams++
				final_mark +=
					(parseFloat(examData.total_score) / parseFloat(examData.maximum_score)) *
					60.0 *
					0.5
			}
		} else {
			// For courses with all three exams, the final mark is calculated based on the contributions of the
			// theory, practical, and oral exams, which together contribute 50% to the final mark.
			if (examData.assessment_group.toLowerCase().includes('theory exam')) {
				final_mark +=
					(parseFloat(examData.total_score) / parseFloat(examData.maximum_score)) *
					40.0 *
					0.5
			} else if (examData.assessment_group.toLowerCase().includes('practical exam')) {
				final_mark +=
					(parseFloat(examData.total_score) / parseFloat(examData.maximum_score)) *
					50.0 *
					0.5
			} else if (examData.assessment_group.toLowerCase().includes('oral exam')) {
				final_mark +=
					(parseFloat(examData.total_score) / parseFloat(examData.maximum_score)) *
					10.0 *
					0.5
			}
		}
		// Add DP contribution if all exams are conducted.
		// DP contributes 50% to the final mark.
		if (number_of_exams == 3) {
			final_mark += dp * 0.5
		}
	} else if (
		examData &&
		examData.assessment_group.toLowerCase().includes('test') &&
		!examData.assessment_group.toLowerCase().includes('practical test')
	) {
		/*
     Practical tests account for 50% of the dp for modules with a practical test, written tests and assignments are
     multiplied by 0.5 to account for their contribution to the DP when a practical test is present. 
     practical_tests is set to 1 to ensure the results are displayed for modules without a practical test.
     For modules without a practical test, written tests and assignments contribute fully to the DP. 
     */
		tests++
		if (noPracTest.some((assessment) => examData.course.includes(assessment))) {
			practical_tests = 1
			dp += (parseFloat(examData.total_score) / parseFloat(examData.maximum_score)) * 30
		} else {
			dp +=
				(parseFloat(examData.total_score) / parseFloat(examData.maximum_score)) *
				30.0 *
				0.5
		}
	} else if (examData && examData.assessment_group.toLowerCase().includes('assignment')) {
		assignments++
		if (noPracTest.some((assessment) => examData.course.includes(assessment))) {
			practical_tests = 1
			dp += (parseFloat(examData.total_score) / parseFloat(examData.maximum_score)) * 20.0
		} else {
			dp +=
				(parseFloat(examData.total_score) / parseFloat(examData.maximum_score)) *
				20.0 *
				0.5
		}
	} else if (examData && examData.assessment_group.toLowerCase().includes('practical test')) {
		practical_tests++
		if (noPracTest.some((assessment) => examData.course.includes(assessment))) {
			practical_tests = 1
			dp += 0
		} else {
			dp += (parseFloat(examData.total_score) / parseFloat(examData.maximum_score)) * 50.0
		}
	}

	return { dp, final_mark, tests, assignments, practical_tests, number_of_exams }
}
</script>
