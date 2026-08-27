// Copyright (c) 2026, Asante Solutions and contributors
// For license information, please see license.txt

const ENTRY_STATES = ['Awaiting Entry', 'In Entry']
const MODERATION_STATES = ['Checked', 'Moderated']

frappe.ui.form.on('Course Mark Sheet', {
	refresh: function (frm) {
		if (frm.is_new()) return

		if (ENTRY_STATES.includes(frm.doc.workflow_state)) {
			frm.add_custom_button(__('Generate Entries'), () => generate_entries(frm))
		}

		if (MODERATION_STATES.includes(frm.doc.workflow_state)) {
			frm.add_custom_button(__('Moderate Marks'), () => moderate(frm), __('Moderation'))
			if (frm.doc.moderation_method && frm.doc.moderation_method !== 'None') {
				frm.add_custom_button(
					__('Clear Moderation'),
					() => clear_moderation(frm),
					__('Moderation'),
				)
			}
		}

		if (frm.doc.docstatus === 0 && !ENTRY_STATES.includes(frm.doc.workflow_state)) {
			frm.add_custom_button(__('Return for Correction'), () => return_for_correction(frm))
		}

		show_progress(frm)
	},
})

// How much of the sheet is still outstanding, which is most of what the
// checking step consists of asking.
function show_progress(frm) {
	const entries = frm.doc.entries || []
	if (!entries.length) return

	const done = entries.filter((entry) => entry.status !== "Not Marked").length
	frm.dashboard.add_indicator(
		__('{0} of {1} marks entered', [done, entries.length]),
		done === entries.length ? 'green' : 'orange',
	)
}

function generate_entries(frm) {
	frm.call('generate_entries').then((r) => {
		if (!r.message) return
		frappe.show_alert({
			message: __('{0} students, {1} marks to enter', [r.message.students, r.message.entries]),
			indicator: 'green',
		})
		frm.reload_doc()
	})
}

function moderate(frm) {
	const dialog = new frappe.ui.Dialog({
		title: __('Moderate Marks'),
		fields: [
			{
				fieldname: 'method',
				fieldtype: 'Select',
				label: __('Method'),
				options: ['Linear Scale', 'Flat Adjustment'],
				reqd: 1,
				default: 'Flat Adjustment',
			},
			{
				fieldname: 'value',
				fieldtype: 'Float',
				label: __('Value'),
				reqd: 1,
				description: __('The factor to scale by, or the marks to add.'),
			},
			{
				fieldname: 'reason',
				fieldtype: 'Small Text',
				label: __('Reason'),
				reqd: 1,
				description: __('Approved along with the marks, so say what prompted it.'),
			},
		],
		primary_action_label: __('Apply'),
		primary_action: (values) => {
			frm.call('apply_moderation', values).then((r) => {
				dialog.hide()
				if (r.message && r.message.adjusted) {
					frappe.show_alert({
						message: __('{0} marks adjusted, average {1} to {2}', [
							r.message.adjusted,
							r.message.average_before.toFixed(1),
							r.message.average_after.toFixed(1),
						]),
						indicator: 'green',
					})
				}
				frm.reload_doc()
			})
		},
	})
	dialog.show()
}

function clear_moderation(frm) {
	frappe.confirm(__('Put the raw marks back?'), () => {
		frm.call('clear_moderation').then(() => frm.reload_doc())
	})
}

function return_for_correction(frm) {
	const dialog = new frappe.ui.Dialog({
		title: __('Return for Correction'),
		fields: [
			{
				fieldname: 'reason',
				fieldtype: 'Small Text',
				label: __('Reason'),
				reqd: 1,
				description: __('Recorded on the sheet, so the lecturer knows what to fix.'),
			},
		],
		primary_action_label: __('Return'),
		primary_action: ({ reason }) => {
			frappe.call({
				method:
					'education_extension.education_extension.doctype.course_mark_sheet.course_mark_sheet.return_for_correction',
				args: { name: frm.doc.name, reason: reason },
				callback: () => {
					dialog.hide()
					frm.reload_doc()
				},
			})
		},
	})
	dialog.show()
}
