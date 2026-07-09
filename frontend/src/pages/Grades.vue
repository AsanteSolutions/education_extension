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
			<div class="mb-4 flex items-center justify-between gap-3">
				<Dropdown :options="allPrograms">
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
				<Button variant="solid" @click="openReportDialog">
					<template #prefix>
						<FeatherIcon name="download" class="h-4 w-4" />
					</template>
					Progress Report
				</Button>
			</div>
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

		<Dialog v-model="showReportDialog" :options="{ title: 'Download Progress Report' }">
			<template #body-content>
				<div class="space-y-4">
					<FormControl
						type="select"
						label="Academic Year"
						:options="yearOptions"
						v-model="selectedYear"
					/>
					<FormControl
						type="select"
						label="Semester"
						:options="termOptions"
						v-model="selectedTerm"
					/>
				</div>
			</template>
			<template #actions>
				<Button
					variant="solid"
					class="w-full"
					:disabled="!selectedYear || !selectedTerm"
					@click="downloadReport"
				>
					Download
				</Button>
			</template>
		</Dialog>
	</div>
	<!-- <div v-else>
    <MissingData message="No grades found" />
  </div> -->
</template>
<script setup>
import {
	Dropdown,
	FeatherIcon,
	ListView,
	Dialog,
	FormControl,
	createResource,
	createListResource,
} from 'frappe-ui'
import { ref, computed, watch } from 'vue'
import { studentStore } from '@/stores/student'
import { groupBy } from '@/utils'

import MissingData from '@/components/MissingData.vue'

const { getCurrentProgram, getStudentInfo } = studentStore()

let studentInfo = getStudentInfo().value
let currentProgram = getCurrentProgram().value

const allPrograms = ref([])
const selectedProgram = ref('')

// ----- Progress report dialog -----
const showReportDialog = ref(false)
const yearOptions = ref([{ label: '', value: '' }])
const allTerms = ref([])
const selectedYear = ref('')
const selectedTerm = ref('')

// Academic Year / Term choices for the dialog, scoped to this student's
// enrolments. Fetched via a backend method because students can't list the
// Academic Year / Academic Term doctypes directly. All other report fields
// (student, letterhead, etc.) are filled automatically in downloadReport().
const reportOptions = createResource({
	url: 'education_extension.education_extension.doctype.student_progress_report.student_progress_report.get_progress_report_options',
	auto: true,
	onSuccess: (data) => {
		yearOptions.value = [
			{ label: '', value: '' },
			...(data?.years || []).map((y) => ({ label: y, value: y })),
		]
		allTerms.value = data?.terms || []
	},
})

// Only show terms belonging to the selected academic year.
const termOptions = computed(() => [
	{ label: '', value: '' },
	...allTerms.value
		.filter((t) => t.academic_year === selectedYear.value)
		.map((t) => ({ label: t.academic_term, value: t.academic_term })),
])

// Clear the term when the year changes so a stale term isn't submitted.
watch(selectedYear, () => {
	selectedTerm.value = ''
})

const openReportDialog = () => {
	showReportDialog.value = true
}

const downloadReport = () => {
	if (!selectedYear.value || !selectedTerm.value) return
	const doc = {
		doctype: 'Student Progress Report',
		student: studentInfo.name,
		student_name: studentInfo.student_name || studentInfo.name,
		academic_year: selectedYear.value,
		academic_term: selectedTerm.value,
		add_letterhead: 1,
		letterhead: 'TARDI Letterhead',
	}
	// The endpoint streams a PDF via frappe.response, so trigger it with a form
	// POST (opens the download in a new tab) and include the CSRF token.
	const url =
		'/api/method/education_extension.education_extension.doctype.student_progress_report.student_progress_report.preview_progress_report'
	const form = document.createElement('form')
	form.method = 'POST'
	form.action = url
	form.target = '_blank'
	const addField = (name, value) => {
		const input = document.createElement('input')
		input.type = 'hidden'
		input.name = name
		input.value = value
		form.appendChild(input)
	}
	addField('doc', JSON.stringify(doc))
	addField('csrf_token', window.csrf_token)
	document.body.appendChild(form)
	form.submit()
	document.body.removeChild(form)
	showReportDialog.value = false
}

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
		docstatus: ['!=', '2'],
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
		docstatus: ['!=', '2'],
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
			docstatus: ['!=', '2'],
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

	let conductedExams = groupBy(response, (row) => row.assessment_group)
	let exams = Object.keys(conductedExams)

	// Sort exams to ensure theory, practical, and oral exams are at the end of the columns
	exams.sort((a, b) => {
		const hasA = a.includes('Exam')
		const hasB = b.includes('Exam')

		if (hasA && !hasB) return 1
		if (!hasA && hasB) return -1
		return 0
	})

	updateColumns(exams)
	let courses = groupBy(response, (row) => row.course)
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
		tableData.value.rows.push(row)
	})
}

const updateColumns = (exams) => {
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
