<template>
  <div v-if="tableData.rows.length > 0" class="px-5 py-4">
    <ListView
      :columns="tableData.columns"
      :rows="tableData.rows"
      :options="{
        selectable: false,
        showTooltip: false,
        onRowClick: () => {},
      }"
      row-key="id"
      v-if="tableData.rows.length > 0"
    >
      <ListHeader>
        <ListHeaderItem
          v-for="column in tableData.columns"
          :key="column.key"
          :item="column"
        />
      </ListHeader>
      <ListRow
        v-for="row in tableData.rows"
        :key="row.id"
        :row="row"
        v-slot="{ column, item }"
      >
        <ListRowItem :item="item" :align="column.align">
          <Badge
            v-if="column.key === 'status'"
            variant="subtle"
            :theme="badgeColor(row.status) || 'gray'"
            size="md"
            :label="item"
          />
          <Button
            v-if="column.key === 'cta' && row.status === 'Paid'"
            @click="openInvoicePDF(row)"
            class="hover:bg-gray-900 hover:text-white"
            icon-left="download"
            label="Download Invoice"
          />

          <Button
            v-if="column.key === 'cta' && row.status !== 'Paid'"
            @click="openModal(row)"
            class="hover:bg-gray-900 hover:text-white flex flex-column items-center justify-center"
            icon-left="credit-card"
            label="Pay Now"
          />
        </ListRowItem>
      </ListRow>
    </ListView>
    <FeesPaymentDialog
      v-if="currentRow"
      :row="currentRow"
      :student="studentInfo"
      v-model="showPaymentDialog"
      @success="success()"
    />
  </div>

  <div v-else>
    <MissingData message="No Fees found" />
  </div>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import {
  ListView,
  ListHeader,
  ListHeaderItem,
  ListRow,
  ListRowItem,
  Badge,
  createResource,
} from 'frappe-ui'
import FeesPaymentDialog from '@/components/FeesPaymentDialog.vue'
import { studentStore } from '@/stores/student'
import MissingData from '@/components/MissingData.vue'
import { createToast } from '@/utils'

const { getStudentInfo } = studentStore()

// Held as a ref. The store replaces this when its own request lands, usually
// after this page is set up, so reading `.value` once pinned an empty object
// and the invoice request went out naming no student at all.
const studentInfo = getStudentInfo()
const student = computed(() => studentInfo.value?.name)

// What the student should deal with first. Every status the page can show is
// named, "Partly Paid" included -- it was missing here while `badgeColor`
// handled it, so it scored `undefined` and the comparator returned NaN. A
// comparator that answers NaN, or nothing at all for two equal rows, is not a
// comparator: the ordering it produces is whatever the engine's sort happens
// to do with it. Anything unrecognised sorts last rather than scoring NaN, and
// equal statuses fall back to the due date so the order is at least stable.
const STATUS_ORDER = { Overdue: 0, Unpaid: 1, 'Partly Paid': 2, Paid: 3 }

const byUrgency = (a, b) => {
  const rank = (status) =>
    status in STATUS_ORDER ? STATUS_ORDER[status] : Object.keys(STATUS_ORDER).length

  const difference = rank(a.status) - rank(b.status)
  if (difference) return difference

  return String(a.due_date || '').localeCompare(String(b.due_date || ''))
}

const feesResource = createResource({
  url: 'education.education.api.get_student_invoices',
  // Fetched from the watch below, once there is a student to ask about.
  auto: false,
  onSuccess: (response) => {
    printFormat = response?.print_format
    tableData.rows = [...(response?.invoices || [])].sort(byUrgency)
  },
})

watch(
  student,
  (name) => {
    if (!name) return
    feesResource.update({ params: { student: name } })
    feesResource.reload()
  },
  { immediate: true },
)

const tableData = reactive({
  rows: [],
  columns: [
    {
      label: 'Program',
      key: 'program',
      width: 1,
    },
    {
      label: 'Status',
      key: 'status',
      width: 1,
    },
    {
      label: 'Payment Date',
      key: 'payment_date',
      width: 1,
    },
    {
      label: 'Due Date',
      key: 'due_date',
      width: 1,
    },
    {
      label: 'Amount',
      key: 'amount',
      width: 1,
    },
    {
      label: 'Invoice',
      key: 'cta',
      width: 1,
    },
  ],
})

const currentRow = ref(null)
const showPaymentDialog = ref(false)

let printFormat = 'Standard'
const openInvoicePDF = (row) => {
  let url = `/api/method/frappe.utils.print_format.download_pdf?
		doctype=${encodeURIComponent('Sales Invoice')}
		&name=${encodeURIComponent(row.invoice)}
		&format=${encodeURIComponent(printFormat)}
	`
  window.open(url, '_blank')
}

const openModal = (row) => {
  currentRow.value = row
  showPaymentDialog.value = true
}

const success = () => {
  feesResource.reload()
  createToast({
    title: 'Payment successful',
    icon: 'check',
    iconClasses: 'text-green-600',
  })
}

const badgeColor = (status) => {
  const badgeColorMap = {
    Paid: 'green',
    Unpaid: 'red',
    Overdue: 'red',
    'Partly Paid': 'orange',
  }
  return badgeColorMap[status]
}
</script>
