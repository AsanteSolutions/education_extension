// Copyright (c) 2026, Asante Solutions and contributors
// For license information, please see license.txt

frappe.ui.form.on('Course Mark Scheme', {
	refresh: function (frm) {
		if (frm.doc.docstatus === 1) {
			frm.add_custom_button(__('Copy to Another Year'), () => copy_to_year(frm))
		}
	},
})

// Starting a new year from last year's breakdown, rather than an empty table.
function copy_to_year(frm) {
	const dialog = new frappe.ui.Dialog({
		title: __('Copy Mark Scheme'),
		fields: [
			{
				fieldname: 'academic_year',
				fieldtype: 'Link',
				options: 'Academic Year',
				label: __('Copy to Academic Year'),
				reqd: 1,
			},
		],
		primary_action_label: __('Copy'),
		primary_action: ({ academic_year }) => {
			frappe.call({
				method:
					'education_extension.education_extension.doctype.course_mark_scheme.course_mark_scheme.copy_to_academic_year',
				args: { name: frm.doc.name, academic_year: academic_year },
				callback: (r) => {
					dialog.hide()
					if (r.message) frappe.set_route('Form', 'Course Mark Scheme', r.message)
				},
			})
		},
	})
	dialog.show()
}
