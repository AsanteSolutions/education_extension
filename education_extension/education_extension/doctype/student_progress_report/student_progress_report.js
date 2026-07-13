// Copyright (c) 2026, Asante Solutions and contributors
// For license information, please see license.txt

// frappe.ui.form.on("Student Progress Report", {
// 	refresh(frm) {

// 	},
// });
frappe.ui.form.on('Student Progress Report', {
	onload: function (frm) {
		frm.set_query('academic_term', function () {
			return {
				filters: {
					academic_year: frm.doc.academic_year,
				},
			}
		})
	},

	refresh: function (frm) {
		frm.disable_save()
		frm.page.clear_indicator()
		frm.page.set_primary_action(__('Print Progress Report'), () => {
			let doc = frm.doc
			if (!doc.student || !doc.academic_year || !doc.academic_term) {
				frappe.throw(__('Please fill in all the mandatory fields.'))
			}
			let url =
				'/api/method/education_extension.education_extension.doctype.student_progress_report.student_progress_report.preview_progress_report'
			open_url_post(url, { doc: frm.doc }, true)
		})
		frappe.call({
			method: 'frappe.client.get_value',
			args: {
				doctype: 'Company',
				filters: { name: frm.doc.company },
				fieldname: 'default_letter_head',
			},
			callback: function (r) {
				if (r.message && r.message.default_letter_head) {
					frm.set_value('letterhead', r.message.default_letter_head)
				}
			},
		})
	},

	student: function (frm) {
		if (frm.doc.student) {
			frappe.call({
				method: 'education.education.api.get_current_enrollment',
				args: {
					student: frm.doc.student,
					academic_year: frm.doc.academic_year,
				},
				callback: function (r) {
					if (r) {
						console.log(r.message)
						$.each(r.message, function (i, d) {
							if (frm.fields_dict.hasOwnProperty(i)) {
								frm.set_value(i, d)
							}
						})
					}
				},
			})
		}
	},
})
