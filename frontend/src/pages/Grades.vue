<template lang="">
	<!-- <div v-if="grades.data?.length > 0">-->
	<div>
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
					selectedProgram.value = program.program
					grades.update({
						filters: {
							student: studentInfo.name,
							program: selectedProgram.value,
							docstatus: '1',
						},
					})
					grades.reload()
				},
			})
		})
		selectedProgram.value = programs[programs.length - 1].label
		allPrograms.value = programs
	},
	auto: true,
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
	],
	filters: {
		student: studentInfo.name,
		program: currentProgram.program,
		docstatus: '1',
		// student:"EDU-STU-2023-00005",
		// program:"Comp Science"
	},
	transform: () => {},

	onSuccess: (response) => {
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
			row.course = course
			//row.batch = courses[course][0].student_group
			let dp = 0.0
			let final_mark = 0.0
			let assignments = 0
			let tests = 0
			let practical_tests = 0
			let number_of_exams = 0
			exams.forEach((exam) => {
				let examData = conductedExams[exam].find((row) => row.course === course)
				row[exam] = examData
					? `${+((parseFloat(examData.total_score) / parseFloat(examData.maximum_score)) * 100.0).toFixed(2)}%`
					: '-'
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
			})
			row.dp =
				assignments == numberOfAssignments &&
				tests == numberOfTests &&
				practical_tests == numberofPracticalTests
					? `${+dp.toFixed(2)}%`
					: '-'
			row.final_mark =
				row.dp !== '-' && number_of_exams == numberOfExams
					? `${+final_mark.toFixed(2)}%`
					: '-'
			tableData.value.rows.push(row)
		})
	},
	auto: true,
})

const updateColumns = (exams) => {
	exams.forEach((exam) => {
		let col = {}
		col.label = exam
		col.key = exam
		tableData.value.columns.push(col)
	})
	tableData.value.columns.push({
		label: 'DP',
		key: 'dp',
	})

	const length = tableData.value.columns.length
	for (
		let i = length - 1;
		tableData.value.columns[i - 1].key.toLowerCase().includes('theory exam') ||
		tableData.value.columns[i - 1].key.toLowerCase().includes('practical exam') ||
		tableData.value.columns[i - 1].key.toLowerCase().includes('oral exam');
		i--
	) {
		;[tableData.value.columns[i], tableData.value.columns[i - 1]] = [
			tableData.value.columns[i - 1],
			tableData.value.columns[i],
		]
	}

	tableData.value.columns.push({
		label: 'Final Mark',
		key: 'final_mark',
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
	const noPracTest = ['OCAH1101', 'ANH2305', 'AEC2301', 'ANH3503', 'ANH2404']
	const noOralExam = ['CLT1101']

	if (examData && examData.custom_assessment_type == 'Exam') {
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
	} else if (examData && examData.custom_assessment_type == 'Test') {
		/*
     Practical tests account for 50% of the dp for modules with a practical test, written tests and assignments are
     multiplied by 0.5 to account for their contribution to the DP when a practical test is present. 
     practical_tests is set to 1 to ensure the results are displayed for modules without a practical test.
     For modules without a practical test, written tests and assignments contribute fully to the DP. 
     */
		tests++
		if (noPracTest.some((assessment) => examData.course.includes(assessment))) {
			practical_tests = 1
			final_mark +=
				(parseFloat(examData.total_score) / parseFloat(examData.maximum_score)) * 30
		} else {
			dp +=
				(parseFloat(examData.total_score) / parseFloat(examData.maximum_score)) *
				30.0 *
				0.5
		}
	} else if (examData && examData.custom_assessment_type == 'Assignment') {
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
	} else if (examData && examData.custom_assessment_type == 'Practical Test') {
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
