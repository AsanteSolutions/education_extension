<template>
  <div class="w-full h-full">
    <Calendar v-if="view.state === 'calendar'" :events="events" />
    <ErrorMessage
      v-else-if="view.state === 'error'"
      class="py-6"
      :message="loadError"
    />
    <MissingData v-else :message="view.message" />
  </div>
</template>

<script setup>
import Calendar from '@/components/Calendar.vue'
import MissingData from '@/components/MissingData.vue'
import { ErrorMessage, createResource } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { studentStore } from '@/stores/student'

const { getCurrentProgram, getStudentGroups } = studentStore()

// Held as refs, not unwrapped here. The store fills these in from its own
// request, which has usually not landed when this page is set up -- so reading
// `.value` once pinned an undefined programme into the params below, and this
// page, the app's default route, asked the server for a timetable for nobody.
const currentProgram = getCurrentProgram()
const studentGroups = getStudentGroups()
const programName = computed(() => currentProgram.value?.program)

const events = ref([])

// A time comes back as "09:00:00.000000" and the display wants the clock part.
// Written to survive the field being empty: it is not mandatory on a Course
// Schedule, and one row without it used to throw here and take the whole
// timetable down with it.
const clockTime = (value) => (value || '').split('.')[0]

const scheduleResource = createResource({
  url: 'education.education.api.get_course_schedule_for_student',
  // Fetched from the watch below instead, once there is a programme to ask
  // about. `auto` would have fired it immediately, before the store answered.
  auto: false,
  onSuccess: (response) => {
    const schedule = (response || []).map((classSchedule) => ({
      title: classSchedule.title,
      with: classSchedule.instructor,
      name: classSchedule.name,
      room: classSchedule.room,
      date: classSchedule.schedule_date,
      from_time: clockTime(classSchedule.from_time),
      to_time: clockTime(classSchedule.to_time),
      color: classSchedule.class_schedule_color,
    }))

    schedule.sort((a, b) => {
      const dateA = new Date(a.date + ' ' + a.from_time)
      const dateB = new Date(b.date + ' ' + b.from_time)
      return dateA - dateB
    })

    events.value = schedule
  },
})

watch(
  [programName, studentGroups],
  ([program, groups]) => {
    if (!program) return
    scheduleResource.update({
      params: { program_name: program, student_groups: groups || [] },
    })
    scheduleResource.reload()
  },
  { immediate: true },
)

const loadError = computed(() => scheduleResource.error)

// What the page shows: the calendar, an error, or a message standing in for
// one. A page that quietly renders nothing is indistinguishable from a page
// that is still loading, and this is the first thing a student sees.
const view = computed(() => {
  const message = (text) => ({ state: 'message', message: text })

  if (loadError.value) return { state: 'error' }
  if (!programName.value) return message('Your programme could not be loaded.')
  if (scheduleResource.loading || !scheduleResource.fetched)
    return message('Loading your timetable...')
  if (!events.value.length) return message('Nothing is scheduled for you yet.')
  return { state: 'calendar' }
})
</script>

<style></style>
