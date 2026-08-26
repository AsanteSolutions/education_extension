<template>
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
			<Dropdown class="mb-4" :options="allTerms">
				<template #default="{ open }">
					<Button :label="selectedTerm || 'Select a term'">
						<template #suffix>
							<FeatherIcon
								:name="open ? 'chevron-up' : 'chevron-down'"
								class="h-4 text-gray-600"
							/>
						</template>
					</Button>
				</template>
			</Dropdown>
			<div v-if="view.state === 'table'" class="grades-table">
				<ListView
					:columns="tableColumns"
					:rows="tableRows"
					:options="{
						selectable: false,
						showTooltip: false,
						onRowClick: () => {},
					}"
					row-key="id"
				/>
			</div>
			<ErrorMessage v-else-if="view.state === 'error'" class="py-6" :message="loadError" />
			<MissingData v-else :message="view.message" />
		</div>
	</div>
</template>
<script setup>
import {
	Dropdown,
	ErrorMessage,
	FeatherIcon,
	ListView,
	createListResource,
} from 'frappe-ui'
import { computed, ref } from 'vue'
import { studentStore } from '@/stores/student'
import MissingData from '@/components/MissingData.vue'
import { groupBy } from '@/utils'
import { calculateCourseMarks, scoreRatio, SUPP_GROUP } from '@/utils/marks'

const { getCurrentProgram, getStudentInfo } = studentStore()

// Held as refs, not unwrapped here: the store fills these in from its own
// request and replaces the object when it lands, so reading `.value` once at
// setup would pin whatever happened to be there at the time.
const studentInfo = getStudentInfo()
const currentProgram = getCurrentProgram()
const student = computed(() => studentInfo.value?.name)

const allTerms = ref([])
const selectedTerm = ref('')

// The raw responses. Everything the table shows is derived from these, so the
// three requests can land in any order without a rebuild step to sequence them.
const assessmentResults = ref([])
const academicRemarks = ref([])
const supplementaryRemarks = ref([])

// None of these three fetch on their own: each is scoped to one student and one
// term, which loadTerm supplies once both are known.
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
	pageLength: 256,
	auto: false,
	onSuccess: (response) => {
		assessmentResults.value = response
	},
})

const remarks = createListResource({
	doctype: 'Academic Remark',
	fields: ['name', 'student', 'remark', 'course', 'academic_year', 'academic_term'],
	pageLength: 256,
	auto: false,
	onSuccess: (response) => {
		academicRemarks.value = response
	},
})

// Supplementary Academic Remark mirrors Academic Remark, except its remark
// column is named `supp_remark`; normalising it here keeps the lookup common.
// Most students have none, so this is usually empty and no supplementary
// columns appear.
const supp_remarks = createListResource({
	doctype: 'Supplementary Academic Remark',
	fields: ['name', 'student', 'supp_remark', 'course', 'academic_year', 'academic_term'],
	pageLength: 256,
	auto: false,
	onSuccess: (response) => {
		supplementaryRemarks.value = response.map((r) => ({ ...r, remark: r.supp_remark }))
	},
})

// Selects a term and refetches everything scoped to it, so what is on screen
// always matches the selection.
const loadTerm = (academic_year, academic_term) => {
	selectedTerm.value = academic_term
	if (!student.value) return

	for (const resource of [grades, remarks, supp_remarks]) {
		resource.update({
			filters: {
				student: student.value,
				academic_year: academic_year,
				academic_term: academic_term,
				docstatus: '1',
			},
		})
		resource.reload()
	}
}

const getTerms = createListResource({
	doctype: 'Academic Term',
	fields: ['name', 'academic_year'],
	auto: true,
	onSuccess: (response) => {
		allTerms.value = response.map((term) => ({
			// `term.name` is the Academic Term docname, which the doctype builds as
			// `${academic_year} (${term_name})` — the same string the filters need.
			label: term.name,
			onClick: () => {
				if (selectedTerm.value === term.name) return
				loadTerm(term.academic_year, term.name)
			},
		}))

		const { academic_year, academic_term } = currentProgram.value || {}
		if (academic_term) loadTerm(academic_year, academic_term)
	},
})

// The supplementary exam is reported in its own columns and takes no part in
// the DP or the final mark.
const supplementaryByCourse = computed(() => {
	const byCourse = {}
	for (const result of assessmentResults.value) {
		if (result.assessment_group === SUPP_GROUP) byCourse[result.course] = result
	}
	return byCourse
})

const tableRows = computed(() => {
	const mainResults = assessmentResults.value.filter((r) => r.assessment_group !== SUPP_GROUP)
	const courses = groupBy(mainResults, (row) => row.course)

	return Object.keys(courses).map((course) => {
		const courseResults = courses[course]
		// Every result in view comes from the one selected term, so any of the
		// course's rows carries the year and term the remarks are matched on.
		const { academic_year, academic_term } = courseResults[0]
		const { dp, finalMark, dpComplete, examsComplete } = calculateCourseMarks(
			course,
			courseResults,
		)
		const supp = supplementaryByCourse.value[course]

		return {
			// ListView keys rows by `row-key="id"`; without a unique id every row
			// keys to `undefined`, so Vue can't diff them and the table fails to
			// re-render when switching terms. Course code is unique per row.
			id: course,
			course: course,
			dp: dpComplete ? `${Math.round(dp)}%` : '-',
			final_mark: dpComplete && examsComplete ? `${Math.round(finalMark)}%` : '-',
			remark: findRemark(academicRemarks.value, course, academic_year, academic_term),
			supp_exam:
				supp && parseFloat(supp.maximum_score)
					? `${Math.round(scoreRatio(supp) * 100)}%`
					: '-',
			supp_remark: findRemark(
				supplementaryRemarks.value,
				course,
				supp ? supp.academic_year : academic_year,
				supp ? supp.academic_term : academic_term,
			),
		}
	})
})

// The supplementary columns only appear when a course in view actually has a
// supplementary result or remark.
const hasSupplementary = computed(() => {
	const remarked = new Set(supplementaryRemarks.value.map((r) => r.course))
	return tableRows.value.some(
		(row) => supplementaryByCourse.value[row.course] || remarked.has(row.course),
	)
})

const tableColumns = computed(() => {
	const columns = [
		{ label: 'Course', key: 'course' },
		{ label: 'DP', key: 'dp' },
		{ label: 'Final Mark', key: 'final_mark' },
		{ label: 'Remark', key: 'remark' },
	]
	if (hasSupplementary.value) {
		columns.push(
			{ label: 'Supp Exam', key: 'supp_exam' },
			{ label: 'Supp Remark', key: 'supp_remark' },
		)
	}
	return columns
})

// The first failure across the four requests, if any. Shown in place of the
// table rather than leaving an empty one behind.
const loadError = computed(() =>
	[getTerms, grades, remarks, supp_remarks].map((resource) => resource.list.error).find(Boolean),
)

// What the page shows: the table, an error, or a message standing in for it.
// Ordered so the more specific reason wins — an unloaded student reads better
// than "no grades found", which is what an empty table would have implied.
const view = computed(() => {
	const message = (text) => ({ state: 'message', message: text })

	if (loadError.value) return { state: 'error' }
	if (!student.value) return message('Your student details could not be loaded.')
	if (getTerms.list.loading || !getTerms.list.fetched) return message('Loading grades...')
	if (!selectedTerm.value) return message('Select a term to see your grades.')
	if (grades.list.loading || !grades.list.fetched) return message('Loading grades...')
	if (!tableRows.value.length) return message(`No grades found for ${selectedTerm.value}.`)
	return { state: 'table' }
})

// The stored remark for a course in a given term, or '-' when there is none.
// Matching on year and term matters while a term switch is in flight: the
// previous term's remarks are still loaded until the new ones arrive.
const findRemark = (remarkList, course, academic_year, academic_term) =>
	remarkList.find(
		(r) =>
			r.course === course &&
			r.academic_year === academic_year &&
			r.academic_term === academic_term,
	)?.remark || '-'
</script>

<style scoped>
.grades-table :deep(.overflow-x-auto) {
	overflow-x: visible;
}
</style>
