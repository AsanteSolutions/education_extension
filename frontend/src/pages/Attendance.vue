<template>
  <div class="py-4 flex flex-col">
    <div class="px-5 flex items-center gap-2">
      <h2 class="font-semibold text-2xl">{{ programName }}</h2>
      <Dropdown :options="allStudentGroups">
        <template #default="{ open }">
          <Button :label="selectedGroup">
            <template #suffix>
              <FeatherIcon
                :name="open ? 'chevron-up' : 'chevron-down'"
                class="h-4 text-gray-600"
              />
            </template>
          </Button>
        </template>
      </Dropdown>
    </div>
    <div class="h-full">
      <Calendar
        v-if="!attendanceResource.loading && attendanceResource.data"
        :events="attendanceResource.data"
      />
      <Calendar v-else :events="[]" />
    </div>
  </div>
</template>
<script setup>
import { computed, ref, watch } from 'vue'
import { studentStore } from '@/stores/student'

import { createResource, Dropdown, FeatherIcon } from 'frappe-ui'
import Calendar from '@/components/Calendar.vue'

const { getCurrentProgram, getStudentInfo, getStudentGroups } = studentStore()

// Held as refs rather than unwrapped once. The store replaces these when its
// own request lands, which is usually after this page is set up, so reading
// `.value` here pinned whatever happened to be there -- nothing.
const currentProgram = getCurrentProgram()
const studentInfo = getStudentInfo()
const studentGroups = getStudentGroups()
const programName = computed(() => currentProgram.value?.program)

const NO_GROUP = 'Select Student Group'
const selectedGroup = ref(NO_GROUP)

const loadAttendance = () => {
  if (!studentInfo.value?.name || selectedGroup.value === NO_GROUP) return
  attendanceResource.update({
    params: {
      student: studentInfo.value.name,
      student_group: selectedGroup.value,
    },
  })
  attendanceResource.reload()
}

// Built from the store rather than mutated in place, so the dropdown follows
// the groups instead of being filled in once on mount and never again.
const allStudentGroups = computed(() =>
  (studentGroups.value || []).map((group) => ({
    ...group,
    onClick: () => {
      if (group.label === selectedGroup.value) return
      selectedGroup.value = group.label
      loadAttendance()
    },
  })),
)


const attendanceStatus = {
  Present: 'bg-green-100',
  Absent: 'bg-red-200',
  Leave: 'bg-orange-100',
}

const attendanceResource = createResource({
  url: 'education.education.api.get_student_attendance',
  // Params are set by `loadAttendance` once there is a student and a group to
  // ask about; there is nothing to fetch before that.
  transform: (attendance) => {
    // filter attendance to remove duplicate attendance data
    attendance = attendance.filter(
      (attendance, index, self) =>
        index === self.findIndex((t) => t.date === attendance.date)
    )

    let events = []

    attendance.forEach((attendance) => {
      events.push({
        name: attendance.name,
        title: attendance.status,
        background_color: attendanceStatus[attendance.status],
        date: attendance.date,
        status: attendance.status,
      })
    })
    return events
  },
  onError: (err) => {
    console.log('Error', err)
  },
})

// Below the resource on purpose: `immediate` runs this during setup, and
// `loadAttendance` reaches for `attendanceResource`, which is not initialised
// until the statement above has run.
watch(
  allStudentGroups,
  (groups) => {
    // A student can legitimately belong to no group at all -- a new intake, or
    // one not yet allocated. Reading `[0].label` threw on that, inside
    // `onMounted`, which left the calendar permanently empty and took the
    // dropdown down with it.
    if (!groups.length || selectedGroup.value !== NO_GROUP) return
    selectedGroup.value = groups[0].label || NO_GROUP
    loadAttendance()
  },
  { immediate: true },
)

</script>
