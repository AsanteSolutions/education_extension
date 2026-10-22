// Copyright (c) 2026, Asante Solutions and contributors
// For license information, please see license.txt

/**
 * The two things every registration screen on the desk does the same way.
 *
 * Both were copy-pasted across five files: the three registration reports, the
 * signing page and the override form. The term default in particular has to
 * agree everywhere -- a report opening on one term while the override form
 * opens on another is how a registrar grants a permission that silently covers
 * nothing -- and five copies of a rule is five chances for it to stop agreeing.
 *
 * Loaded through `app_include_js` as a plain file. It is served straight off
 * the app's public directory, which `/assets/education_extension` is a symlink
 * to, so it needs no build step: a path that does not say `.bundle.` is passed
 * through to the page as written.
 */

frappe.provide('education_extension')

/**
 * The term registration is open for, as a promise of a name or null.
 *
 * The most recently opened window. A site can have more than one open at once
 * -- different programmes register on different dates -- and this is only a
 * default for a field the person can change, so the newest is the one they are
 * most likely asking about.
 */
education_extension.term_being_registered = () =>
	frappe.db
		.get_list('Registration Period', {
			fields: ['academic_term'],
			order_by: 'opens_on desc',
			limit: 1,
		})
		.then((periods) => (periods && periods.length ? periods[0].academic_term : null))

/**
 * Open a report on the term being registered, unless it already has one.
 *
 * Leaves a term the person has chosen alone, including one restored from a
 * saved filter, so this only ever fills an empty field.
 */
education_extension.default_report_term = (report, fieldname = 'academic_term') => {
	if (report.get_filter_value(fieldname)) return Promise.resolve()

	return education_extension.term_being_registered().then((term) => {
		if (term) report.set_filter_value(fieldname, term)
	})
}

/**
 * The button that starts a registrar's override from the report they spotted
 * the student on, rather than from a doctype they would have to know the name
 * of. The term goes with it: a permission for the wrong term covers nothing.
 */
education_extension.add_override_button = (report, fieldname = 'academic_term') => {
	report.page.add_inner_button(__('Allow a Student to Register'), () => {
		frappe.new_doc('Registration Override', {
			academic_term: report.get_filter_value(fieldname),
		})
	})
}
