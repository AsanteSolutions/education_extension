import { defineStore } from 'pinia'
import { ref } from 'vue'
import { createResource } from 'frappe-ui'

export const studentStore = defineStore('education-student', () => {
  const studentInfo = ref({})
  const currentProgram = ref({})
  const studentGroups = ref([])

  const student = createResource({
    url: 'education_extension.education_extension.api.get_student_info',
    onSuccess(info) {
      if (!info) {
        // Returned, not just redirected. Setting `location.href` does not stop
        // this function, so the lines below went on to read a null payload --
        // and the TypeError that threw was caught as a failed fetch, so the
        // request that correctly reported "no student here" was recorded as an
        // error while the page waited for a navigation that had not happened
        // yet.
        window.location.href = '/app'
        return
      }
      currentProgram.value = info.current_program || {}
      // remove current_program from info
      delete info.current_program
      // Defaulted to an empty list rather than left undefined: every caller
      // iterates this, and a student with no groups is an ordinary state.
      studentGroups.value = info.student_groups || []
      delete info.student_groups
      studentInfo.value = info
    },
    onError(err) {
      console.error(err)
    },
  })

  // const s = createDocumentResource({
  // 	doctype:"Student",
  // 	whitelist: {
  // 		'get_student_info': get_student_info
  // 	}
  // })

  function getStudentInfo() {
    return studentInfo
  }
  function getCurrentProgram() {
    return currentProgram
  }

  function getStudentGroups() {
    return studentGroups
  }

  return {
    student,
    studentInfo,
    currentProgram,
    studentGroups,
    getStudentInfo,
    getCurrentProgram,
    getStudentGroups,
  }
})
