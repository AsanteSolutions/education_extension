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
import { onMounted, reactive, ref } from 'vue'
import { studentStore } from '@/stores/student'

import { Dialog, createResource, Dropdown, FeatherIcon } from 'frappe-ui'
import { storeToRefs } from 'pinia'
import Calendar from '@/components/Calendar.vue'

const { getCurrentProgram, getStudentInfo, getStudentGroups } = studentStore()
const programName = ref(getCurrentProgram().value?.program)

let studentInfo = getStudentInfo().value

onMounted(() => {
  setStudentGroup()
})

const selectedGroup = ref('Select Student Group')
const allStudentGroups = ref()
function setStudentGroup() {
  allStudentGroups.value = getStudentGroups().value
  allStudentGroups.value.forEach(
    (group) =>
      (group.onClick = () => {
        if (group.label === selectedGroup.value) return
        selectedGroup.value = group.label
	attendanceResource.update({
	  params: {
	    student: studentInfo.name,
	    student_group: selectedGroup.value,
	  },
	})
        attendanceResource.reload()
      })
  )
  selectedGroup.value =
    allStudentGroups.value[0].label || 'Select Student Group'
  attendanceResource.update({
    params: {
      student: studentInfo.name,
      student_group: selectedGroup.value,
    },
  })
  attendanceResource.reload()
}

const attendanceStatus = {
  Present: 'bg-green-100',
  Absent: 'bg-red-200',
  Leave: 'bg-orange-100',
}

const attendanceResource = createResource({
  url: 'education.education.api.get_student_attendance',
  params: {
    student: studentInfo.name,
    student_group: selectedGroup.value,
  },
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

</script>
