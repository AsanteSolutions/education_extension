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

			<div v-else-if="data.state === 'open'">
				<div class="mb-1 text-lg font-semibold text-gray-900">
					Register for {{ data.period.academic_term }}
				</div>
				<div class="mb-4 text-sm text-gray-600">
					{{ data.block_label }} &middot; {{ data.program }} &middot; last day to register
					{{ data.period.last_date_to_register }}
				</div>

				<!-- Two steps, both named up front, so the student knows a declaration
				     is coming rather than meeting it as a surprise at the end. -->
				<div class="mb-5 flex items-center gap-2 text-sm">
					<span
						v-for="(name, index) in ['Choose modules', 'Declarations']"
						:key="name"
						class="flex items-center gap-2"
					>
						<span
							class="grid h-5 w-5 place-items-center rounded-full text-xs font-medium"
							:class="
								step === index + 1
									? 'bg-gray-900 text-white'
									: 'bg-gray-200 text-gray-600'
							"
						>
							{{ index + 1 }}
						</span>
						<span :class="step === index + 1 ? 'text-gray-900' : 'text-gray-500'">
							{{ name }}
						</span>
						<FeatherIcon
							v-if="index === 0"
							name="chevron-right"
							class="h-4 w-4 text-gray-400"
						/>
					</span>
				</div>

				<Alert v-if="data.fee_block" class="mb-4" title="Registration is blocked">
					There is {{ data.fee_block }} outstanding on your account. Settle it with the
					finance office to register.
				</Alert>

				<!-- Step 1: what they will be taking. -->
				<template v-if="step === 1">
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
								<!-- A mandatory row is shown ticked and locked rather than hidden:
								     the student should see everything the term commits them to. -->
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
									<!-- Only when the institute has turned it on for debugging. It
									     explains why a module is offered despite a prerequisite
									     that cannot be confirmed, which helps whoever is diagnosing
									     the rules and not the student, who cannot act on it. The
									     server sends an empty list when it is off. -->
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
							@click="step = 2"
						>
							Continue
						</Button>
					</div>
				</template>

				<!-- Step 2: what they are agreeing to, and the act of registering. The
				     modules are restated here so the declaration is not made against a
				     list the student can no longer see. -->
				<template v-else>
					<div class="mb-5">
						<div class="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">
							Registering for {{ sortedChosen.length }}
							{{ sortedChosen.length === 1 ? 'module' : 'modules' }}
						</div>
						<div class="divide-y rounded border">
							<div
								v-for="course in sortedChosen"
								:key="course"
								class="px-4 py-2 text-sm text-gray-900"
							>
								{{ course }}
							</div>
						</div>
					</div>

					<div class="mb-5 rounded border">
						<div class="border-b bg-gray-50 px-4 py-2 text-xs font-semibold uppercase tracking-wide text-gray-500">
							Pre-requisite declaration
						</div>
						<div class="prose-sm px-4 py-3 text-sm text-gray-800" v-html="data.declarations.prerequisites" />
						<div class="border-t px-4 py-3">
							<Checkbox
								v-model="agreed.prerequisites"
								label="I agree to the declaration above"
							/>
						</div>
					</div>

					<div class="mb-5 rounded border">
						<div class="border-b bg-gray-50 px-4 py-2 text-xs font-semibold uppercase tracking-wide text-gray-500">
							Protection of Personal Information
						</div>
						<div
							class="prose-sm max-h-80 overflow-y-auto px-4 py-3 text-sm text-gray-800"
							v-html="data.declarations.popia"
						/>
						<div class="border-t px-4 py-3">
							<Checkbox
								v-model="agreed.popia"
								label="I give the consent described above"
							/>
						</div>
					</div>

					<div class="mb-5 rounded border">
						<div class="border-b bg-gray-50 px-4 py-2 text-xs font-semibold uppercase tracking-wide text-gray-500">
							Signature
						</div>
						<div class="px-4 py-3">
							<SignaturePad
								v-model="signatures.student"
								:placeholder="studentName ? `Sign as ${studentName}` : 'Sign here'"
							/>

							<!-- Offered rather than deduced. The form requires a parent or
							     guardian to sign for a minor, and nothing here can reliably
							     tell who is one: date of birth is recorded for almost nobody. -->
							<div class="mt-4 border-t pt-3">
								<Checkbox
									v-model="withGuardian"
									label="A parent or guardian is signing as well"
								/>
								<p class="mt-1 text-xs text-gray-500">
									Required if you are under 18.
								</p>
							</div>

							<div v-if="withGuardian" class="mt-3">
								<FormControl
									v-model="signatures.guardian_name"
									label="Parent or guardian name"
									class="mb-3"
								/>
								<SignaturePad
									v-model="signatures.guardian"
									placeholder="Parent or guardian signs here"
									hint="To be signed by the parent or guardian, not the student"
								/>
							</div>
						</div>
					</div>

					<ErrorMessage class="mb-3" :message="submission.error" />

					<div class="flex items-center justify-between gap-4 border-t pt-4">
						<Button variant="subtle" @click="step = 1">Back</Button>
						<div class="flex items-center gap-3">
							<span class="text-sm text-gray-600">
								Registering cannot be undone.
							</span>
							<Button
								variant="solid"
								:disabled="!readyToRegister"
								:loading="submission.loading"
								@click="submit"
							>
								Register
							</Button>
						</div>
					</div>
				</template>
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
	ErrorMessage,
	FeatherIcon,
	FormControl,
	createResource,
} from 'frappe-ui'
import { computed, reactive, ref, watch } from 'vue'
import MissingData from '@/components/MissingData.vue'
import SignaturePad from '@/components/SignaturePad.vue'
import { studentStore } from '@/stores/student'

// The endpoint is session-scoped, so the page never names a student. Everything
// on screen comes from this one response, including the declaration wording —
// which means the text shown is the text the server records as agreed.
const options = createResource({
	url: 'education_extension.education_extension.registration.my_options',
	auto: true,
	onSuccess: (response) => seedSelection(response),
})

const data = computed(() => options.data)

// 1 = choose modules, 2 = declarations.
const step = ref(1)

// Course names the student is registering for. A Set because the only questions
// asked of it are membership and size.
const chosen = reactive(new Set())

const agreed = reactive({ prerequisites: false, popia: false })
const bothAgreed = computed(() => agreed.prerequisites && agreed.popia)

// Drawn marks, as PNG data URIs. The student's is required; a guardian's is
// offered because the form requires one for a minor, and nothing here can tell
// who is one — date of birth is recorded for two students out of 189.
const signatures = reactive({ student: '', guardian_name: '', guardian: '' })
const withGuardian = ref(false)

const { getStudentInfo } = studentStore()
const studentInfo = getStudentInfo()
const studentName = computed(() => studentInfo.value?.student_name || '')

const guardianComplete = computed(
	() => !!signatures.guardian_name.trim() && !!signatures.guardian,
)

// Half a countersignature is worse than none: a name with no mark is not signed,
// and a mark with no name cannot be attributed to anybody. The server refuses
// either half, so the button does too rather than letting it fail on submit.
const readyToRegister = computed(
	() =>
		bothAgreed.value &&
		!!signatures.student &&
		(!withGuardian.value || guardianComplete.value),
)

// Unticking discards what was drawn, so an abandoned half-filled guardian block
// cannot be submitted by accident.
watch(withGuardian, (wanted) => {
	if (wanted) return
	signatures.guardian_name = ''
	signatures.guardian = ''
})

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

// Sorted for the review list: course names begin with the module code, so this
// reads in curriculum order.
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
		step.value = 1
		options.reload()
	},
})

const submit = () =>
	submission.submit({
		courses: sortedChosen.value,
		// Sent as what the student actually ticked rather than a single flag: the
		// server records the two declarations separately, as the paper form does.
		declarations: { prerequisites: agreed.prerequisites, popia: agreed.popia },
		signatures: {
			student: signatures.student,
			guardian_name: withGuardian.value ? signatures.guardian_name : '',
			guardian: withGuardian.value ? signatures.guardian : '',
		},
	})

// A reload after registering returns a different state, and nothing built for
// the previous one still means anything — least of all a signature, which must
// never be carried into a registration it was not drawn for.
watch(
	() => data.value?.state,
	(state) => {
		if (state === 'open') return
		chosen.clear()
		agreed.prerequisites = false
		agreed.popia = false
		withGuardian.value = false
		signatures.student = ''
		signatures.guardian_name = ''
		signatures.guardian = ''
	},
)
</script>
