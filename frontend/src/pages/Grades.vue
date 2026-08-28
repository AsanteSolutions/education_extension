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
	createResource,
} from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { studentStore } from '@/stores/student'
import MissingData from '@/components/MissingData.vue'

const { getCurrentProgram, getStudentInfo } = studentStore()

// Held as refs, not unwrapped here: the store fills these in from its own
// request and replaces the object when it lands, so reading `.value` once at
// setup would pin whatever happened to be there at the time.
const studentInfo = getStudentInfo()
const currentProgram = getCurrentProgram()
const student = computed(() => studentInfo.value?.name)

const allTerms = ref([])
const selectedTerm = ref('')

// The finished table, worked out on the server. The marks used to be calculated
// here, which meant the weightings and the course rules existed a second time in
// JavaScript and could drift from the ones the printed report uses.
const grades = createResource({
	url: 'education_extension.education_extension.marking.get_student_grades',
	auto: false,
})

// The terms on offer are the ones the student is actually enrolled for, not
// every Academic Term on the site. A student can hold more than one enrolment
// in a term, and the term is optional on an enrolment, so the responses are
// reduced to the distinct terms that carry one.
const enrollments = createListResource({
	doctype: 'Program Enrollment',
	fields: ['academic_year', 'academic_term'],
	pageLength: 256,
	auto: false,
	onSuccess: (response) => {
		const byTerm = new Map()
		for (const enrollment of response) {
			// `academic_term` is a link to Academic Term, so its value is that
			// doctype's docname — `${academic_year} (${term_name})`, the same string
			// the filters need.
			if (enrollment.academic_term && !byTerm.has(enrollment.academic_term)) {
				byTerm.set(enrollment.academic_term, enrollment.academic_year)
			}
		}

		allTerms.value = [...byTerm.keys()]
			// The docname sorts by year and then term, so this is chronological.
			.sort()
			.map((term) => ({
				label: term,
				onClick: () => {
					if (selectedTerm.value === term) return
					loadTerm(byTerm.get(term), term)
				},
			}))

		const { academic_year, academic_term } = currentProgram.value || {}
		if (academic_term) loadTerm(academic_year, academic_term)
	},
})

// Fetched as soon as there is a student to fetch them for, whether the store
// had already loaded by the time this page mounted or lands later.
watch(
	student,
	(name) => {
		if (!name) return
		enrollments.update({ filters: { student: name, docstatus: 1 } })
		enrollments.reload()
	},
	{ immediate: true },
)

// Selects a term and refetches the table for it, so what is on screen always
// matches the selection.
const loadTerm = (academic_year, academic_term) => {
	selectedTerm.value = academic_term
	if (!student.value) return

	grades.update({ params: { academic_year: academic_year, academic_term: academic_term } })
	grades.reload()
}

const tableRows = computed(() => grades.data?.rows || [])

const tableColumns = computed(() => {
	const columns = [
		{ label: 'Course', key: 'course' },
		{ label: 'DP', key: 'dp' },
		{ label: 'Final Mark', key: 'final_mark' },
		{ label: 'Remark', key: 'remark' },
	]
	// The supplementary columns only appear when the student has something in
	// them; the server decides, because it is what looked.
	if (grades.data?.has_supplementary) {
		columns.push(
			{ label: 'Supp Exam', key: 'supp_exam' },
			{ label: 'Supp Remark', key: 'supp_remark' },
		)
	}
	return columns
})

// The first failure across the two requests, if any. Shown in place of the
// table rather than leaving an empty one behind.
const loadError = computed(() => enrollments.list.error || grades.error)

// What the page shows: the table, an error, or a message standing in for it.
// Ordered so the more specific reason wins — an unloaded student reads better
// than "no grades found", which is what an empty table would have implied.
const view = computed(() => {
	const message = (text) => ({ state: 'message', message: text })

	if (loadError.value) return { state: 'error' }
	if (!student.value) return message('Your student details could not be loaded.')
	if (enrollments.list.loading || !enrollments.list.fetched) return message('Loading grades...')
	if (!allTerms.value.length) return message('You are not enrolled for any term yet.')
	if (!selectedTerm.value) return message('Select a term to see your grades.')
	if (grades.loading || !grades.fetched) return message('Loading grades...')
	// The server says why there is nothing rather than leaving the page to guess:
	// results held back before their release date read very differently from
	// results that do not exist.
	if (grades.data?.message) return message(grades.data.message)
	if (!tableRows.value.length) return message(`No grades found for ${selectedTerm.value}.`)
	return { state: 'table' }
})
</script>

<style scoped>
.grades-table :deep(.overflow-x-auto) {
	overflow-x: visible;
}
</style>
