<template>
  <Dialog
    v-model="showProfileDialog"
    :options="{
      title: 'Profile',
      size: 'xl',
    }"
  >
    <template #body-content>
      <div class="text-base">
        <div class="flex flex-col gap-4">
          <div
            class="flex items-center border-b border-solid border-lightGray pb-4 gap-2"
          >
            <Avatar
              size="3xl"
              class="h-12 w-12"
              :label="studentInfo.student_name"
              :image="studentInfo.image || null"
            />
            <div class="flex flex-col ml-2 gap-1">
              <p class="text-lg font-semibold">
                {{ studentInfo.student_name }}
              </p>
              <p class="text-gray-600">{{ studentInfo.student_email_id }}</p>
            </div>
          </div>
          <div>
            <div class="flex gap-4">
              <div
                v-for="section in infoFormat"
                :key="section.section"
                class="flex-1 flex flex-col gap-4"
              >
                <div v-for="field in section.fields" :key="field.label">
                  <div
                    class="flex items-center"
                    v-if="field.label !== 'Address'"
                  >
                    <p class="w-1/2 text-sm text-gray-600">
                      {{ field.label }}:&nbsp;
                    </p>
                    <p class="w-1/2 text-gray-900">{{ field.value }}</p>
                  </div>
                </div>
              </div>
            </div>
            <div class="flex items-center">
              <p class="w-[32%] text-sm text-gray-600">
                {{ infoFormat[0].fields[3].label }}:&nbsp;
              </p>
              <p class="w-full text-gray-900">
                {{ infoFormat[0].fields[3].value }}
              </p>
            </div>
          </div>

          <div
            class="flex items-center bg-gray-50 p-2 text-gray-600 text-sm rounded-md"
          >
            <FeatherIcon name="info" class="h-4 mr-2" />
            In case of any incorrect details, please contact the school admin.
          </div>
        </div>
      </div>
    </template>
  </Dialog>
</template>

<script setup>
import { Dialog, Avatar, FeatherIcon } from 'frappe-ui'
import { computed, inject } from 'vue'
import { studentStore } from '@/stores/student'
const { getStudentInfo } = studentStore()

const showProfileDialog = inject('showProfileDialog')

// Held as a ref and read through a computed. The store replaces this object
// when its own request lands, which is almost always after this component is
// set up -- so unwrapping `.value` here and building `infoFormat` from it once
// pinned an empty object, and the panel had nothing to show however long it
// stayed open.
const student = getStudentInfo()
const studentInfo = computed(() => student.value || {})

const infoFormat = computed(() => [
  {
    section: 'section 1',
    fields: [
      {
        label: 'Mobile Number',
        value: studentInfo.value.student_mobile_number,
      },
      {
        label: 'Joining Date',
        value: studentInfo.value.joining_date,
      },
      {
        label: 'Date of Birth',
        value: studentInfo.value.date_of_birth,
      },
      {
        label: 'Address',
        value: [
          studentInfo.value?.address_line_1,
          studentInfo.value?.address_line_2,
          studentInfo.value?.city,
          studentInfo.value?.pincode,
          studentInfo.value?.state,
          studentInfo.value?.country,
        ]
          .map((item) => item?.trim())
          .filter(Boolean)
          .join(', '),
      },
    ],
  },
  {
    section: 'section 2',
    fields: [
      {
        label: 'Blood Group',
        value: studentInfo.value.blood_group,
      },
      {
        label: 'Gender',
        value: studentInfo.value.gender,
      },
      {
        label: 'Nationality',
        value: studentInfo.value.nationality,
      },
    ],
  },
])
</script>
