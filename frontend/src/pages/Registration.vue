<template>
	<div class="px-5 py-4">
		<!-- One request drives the whole page, so there is no arrangement of
		     responses that can put it in an inconsistent state. -->
		<MissingData v-if="options.loading && !options.data" message="Loading registration..." />
		<ErrorMessage v-else-if="options.error" class="py-6" :message="options.error" />

		<template v-else-if="data">
			<!-- Nothing to do: shut, already done, or not this student's term. -->
			<MissingData v-if="data.state === 'no_student'" message="Your student details could not be loaded." />
			<MissingData v-else-if="data.state === 'closed'" :message="closedMessage" />
			<MissingData v-else-if="data.state === 'not_offered'" :message="data.message" />

			<!-- Registered: a record of what was taken, not an offer to do it again. -->
			<div v-else-if="data.state === 'registered'">
				<div class="mb-1 text-lg font-semibold text-gray-900">You are registered</div>
				<div class="mb-4 text-sm text-gray-600">
					{{ data.programs.join(', ') }} &middot; {{ data.period.academic_term }}
				</div>
				<div class="divide-y rounded border">
					<div
						v-for="module in data.modules"
						:key="module.course"
						class="flex items-center justify-between gap-3 px-4 py-3"
					>
						<span class="text-sm text-gray-900">{{ module.course }}</span>
						<Badge v-if="module.provisional" theme="orange" variant="subtle">
							Provisional &middot; {{ module.provisional_on }}
						</Badge>
					</div>
				</div>
				<p v-if="hasProvisional" class="mt-3 text-sm text-gray-600">
					A provisional module rests on a result that has not been finalised. If that
					result is a fail, the module will be removed and you will be told.
				</p>
			</div>

			<!-- Open: confirm the block, choose among the carry-overs. -->
			<div v-else-if="data.state === 'open'">
				<div class="mb-1 text-lg font-semibold text-gray-900">
					Register for {{ data.period.academic_term }}
				</div>
				<div class="mb-4 text-sm text-gray-600">
					{{ data.block_label }} &middot; {{ data.program }} &middot; last day to register
					{{ data.period.last_date_to_register }}
				</div>

				<Alert v-if="data.fee_block" class="mb-4" title="Registration is blocked">
					There is {{ data.fee_block }} outstanding on your account. Settle it with the
					finance office to register.
				</Alert>

				<div v-for="group in data.groups" :key="group.block" class="mb-5">
					<div class="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">
						{{ group.label }}
					</div>
					<div class="divide-y rounded border">
						<div
							v-for="row in group.rows"
							:key="row.course"
							class="flex items-start gap-3 px-4 py-3"
							:class="{ 'bg-gray-50': !row.selectable }"
						>
							<!-- A mandatory row is shown ticked and locked rather than hidden: the
							     student should see everything the term commits them to. -->
							<Checkbox
								v-if="row.selectable"
								:modelValue="chosen.has(row.course)"
								:disabled="isMandatory(row) || !!data.fee_block"
								class="mt-0.5"
								@update:modelValue="toggle(row.course)"
							/>
							<span v-else class="mt-1 w-4 shrink-0" />

							<div class="min-w-0 flex-1">
								<div class="flex flex-wrap items-center gap-2">
									<span
										class="text-sm"
										:class="row.selectable ? 'text-gray-900' : 'text-gray-500'"
									>
										{{ row.course }}
									</span>
									<Badge :theme="badge(row.status).theme" variant="subtle">
										{{ badge(row.status).label }}
									</Badge>
								</div>
								<div v-if="row.reason" class="mt-0.5 text-xs text-gray-600">
									{{ row.reason }}
								</div>
								<!-- Said plainly, because it explains why a module is offered
								     despite a prerequisite that cannot be confirmed. -->
								<div v-if="row.unverified.length" class="mt-0.5 text-xs text-gray-500">
									No result on record for {{ row.unverified.join(', ') }}.
								</div>
							</div>
						</div>
					</div>
				</div>

				<div class="flex items-center justify-between gap-4 border-t pt-4">
					<span class="text-sm text-gray-600">
						{{ chosen.size }} {{ chosen.size === 1 ? 'module' : 'modules' }} selected
					</span>
					<Button
						variant="solid"
						:disabled="!chosen.size || !!data.fee_block"
						@click="confirming = true"
					>
						Register
					</Button>
				</div>

				<!-- Registration is final, so the last step is deliberate rather than a
				     single click that cannot be taken back. -->
				<Dialog
					v-model="confirming"
					:options="{ title: 'Confirm your registration' }"
				>
					<template #body-content>
						<p class="mb-3 text-p-base text-gray-700">
							You are registering for these
							{{ chosen.size }} {{ chosen.size === 1 ? 'module' : 'modules' }}:
						</p>
						<ul class="mb-4 list-inside list-disc text-p-base text-gray-800">
							<li v-for="course in sortedChosen" :key="course">{{ course }}</li>
						</ul>
						<p class="text-p-base font-medium text-gray-900">
							This cannot be changed once submitted. Speak to the academic office if
							you need it altered afterwards.
						</p>
						<ErrorMessage class="mt-3" :message="submission.error" />
					</template>
					<template #actions>
						<Button
							class="w-full"
							variant="solid"
							:loading="submission.loading"
							@click="submit"
						>
							Confirm registration
						</Button>
					</template>
				</Dialog>
			</div>
		</template>
	</div>
</template>

<script setup>
import {
	Alert,
	Badge,
	Button,
	Checkbox,
	Dialog,
	ErrorMessage,
	createResource,
} from 'frappe-ui'
import { computed, reactive, ref, watch } from 'vue'
import MissingData from '@/components/MissingData.vue'

// The endpoint is session-scoped, so the page never names a student. Everything
// on screen comes from this one response.
const options = createResource({
	url: 'education_extension.education_extension.registration.my_options',
	auto: true,
	onSuccess: (response) => seedSelection(response),
})

const data = computed(() => options.data)

// Course names the student is registering for. A Set because the only questions
// asked of it are membership and size.
const chosen = reactive(new Set())
const confirming = ref(false)

// Mandatory rows are the ones the student cannot opt out of: their own semester,
// including any module offered provisionally.
const MANDATORY = ['required', 'provisional']
const isMandatory = (row) => MANDATORY.includes(row.status)

// Carry-overs start ticked. Retaking a failed module is the expected path, so
// opting out is the deliberate act rather than opting in — and the running count
// above the button keeps the total visible either way.
const seedSelection = (response) => {
	chosen.clear()
	if (response?.state !== 'open') return
	for (const group of response.groups) {
		for (const row of group.rows) {
			if (row.selectable) chosen.add(row.course)
		}
	}
}

const toggle = (course) => {
	if (chosen.has(course)) chosen.delete(course)
	else chosen.add(course)
}

// Sorted for the confirmation dialog: course names begin with the module code,
// so this reads in curriculum order.
const sortedChosen = computed(() => [...chosen].sort())

const hasProvisional = computed(() =>
	(data.value?.modules || []).some((module) => module.provisional),
)

const closedMessage = computed(() => {
	const response = data.value
	if (response?.message) return response.message
	if (response?.opens_on)
		return `Registration for ${response.academic_term} opens on ${response.opens_on}.`
	return 'Registration is not open.'
})

// Colour carries the same distinction the text does, so the list can be scanned
// without reading every reason line.
const BADGES = {
	required: { label: 'Required', theme: 'blue' },
	carried_over: { label: 'Carried over', theme: 'orange' },
	provisional: { label: 'Provisional', theme: 'orange' },
	blocked: { label: 'Blocked', theme: 'red' },
	passed: { label: 'Passed', theme: 'green' },
	awaiting_result: { label: 'Awaiting result', theme: 'gray' },
	registered: { label: 'Registered', theme: 'green' },
}
const badge = (status) => BADGES[status] || { label: status, theme: 'gray' }

const submission = createResource({
	url: 'education_extension.education_extension.registration.register',
	// The server recomputes eligibility and is the authority on what was created,
	// so the page reloads from it rather than assuming the request succeeded as
	// sent.
	onSuccess: () => {
		confirming.value = false
		options.reload()
	},
})

const submit = () => submission.submit({ courses: sortedChosen.value })

// A reload after registering returns a different state, and the selection built
// for the previous one no longer means anything.
watch(
	() => data.value?.state,
	(state) => {
		if (state !== 'open') chosen.clear()
	},
)
</script>
