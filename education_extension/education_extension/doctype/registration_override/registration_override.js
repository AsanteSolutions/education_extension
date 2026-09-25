// Copyright (c) 2026, Asante Solutions and contributors
// For license information, please see license.txt

/* Two conveniences, no rules — the rules are on the server.
 *
 * The term defaults to the one being registered, because that is the only term
 * anyone is granting a permission for while a window is open, and getting it
 * wrong produces a permission that silently does nothing.
 *
 * The standing the rule counted is shown as soon as a student is picked, so the
 * decision is taken in front of the figures rather than beside them.
 */

frappe.ui.form.on('Registration Override', {
	onload: (frm) => {
		if (frm.is_new() && !frm.doc.academic_term) set_current_term(frm)
	},

	student: (frm) => show_standing(frm),
	academic_term: (frm) => show_standing(frm),
})

const set_current_term = (frm) => {
	frappe.db
		.get_list('Registration Period', {
			fields: ['academic_term'],
			order_by: 'opens_on desc',
			limit: 1,
		})
		.then((periods) => {
			if (periods && periods.length) frm.set_value('academic_term', periods[0].academic_term)
		})
}

const show_standing = (frm) => {
	frm.dashboard.clear_headline()
	if (!frm.doc.student || !frm.doc.academic_term) return

	frappe
		.call({
			method: 'education_extension.education_extension.academic_standing.student_standing',
			args: { student: frm.doc.student, academic_term: frm.doc.academic_term },
		})
		.then((r) => {
			const standing = r.message
			if (!standing) return

			// Said plainly either way. A registrar who is about to allow a student
			// the rule was never going to stop should know that before signing a
			// reason for it.
			if (!standing.excluded) {
				frm.dashboard.set_headline(
					__('{0} is not blocked by the academic standing rule: {1} of {2} modules failed.', [
						frappe.utils.escape_html(frm.doc.student_name || frm.doc.student),
						standing.failed,
						standing.attempted,
					]),
					'blue'
				)
				return
			}

			frm.dashboard.set_headline(
				__('Failed {0} of {1} modules{2} — {3}%.{4}', [
					standing.failed,
					standing.attempted,
					standing.window ? ' ' + __('in {0}', [standing.window]) : '',
					standing.rate,
					standing.failed_modules.length
						? ' ' + frappe.utils.escape_html(standing.failed_modules.join(', '))
						: '',
				]),
				'orange'
			)
		})
}
