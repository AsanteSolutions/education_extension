// Copyright (c) 2026, Asante Solutions and contributors
// For license information, please see license.txt

frappe.query_reports['Academic Exclusions'] = {
	filters: [
		{
			fieldname: 'academic_term',
			label: __('Academic Term'),
			fieldtype: 'Link',
			options: 'Academic Term',
			reqd: 1,
		},
		{
			fieldname: 'standing',
			label: __('Standing'),
			fieldtype: 'Select',
			// Kept in step with academic_standing.py by a test, because two
			// spellings of the same state read as two different states.
			options: ['', 'Cannot register', 'Allowed anyway'].join('\n'),
			default: '',
		},
	],

	onload: (report) => {
		// The whole reason to be on this page is to decide about somebody, so the
		// way to act on it is here rather than on a doctype nobody knows the name
		// of. The term comes across with it: a permission for the wrong term
		// silently covers nothing.
		report.page.add_inner_button(__('Allow a Student to Register'), () => {
			frappe.new_doc('Registration Override', {
				academic_term: report.get_filter_value('academic_term'),
			});
		});

		// Default to the term being registered, which is the one the exclusion
		// bites on.
		if (report.get_filter_value('academic_term')) return;
		frappe.db
			.get_list('Registration Period', {
				fields: ['academic_term'],
				order_by: 'opens_on desc',
				limit: 1,
			})
			.then((periods) => {
				if (periods && periods.length) {
					report.set_filter_value('academic_term', periods[0].academic_term);
				}
			});
	},

	// Colour carries the triage: who still needs a decision, and how bad each
	// record is.
	formatter: (value, row, column, data, default_formatter) => {
		value = default_formatter(value, row, column, data);
		if (!data) return value;

		if (column.fieldname === 'standing') {
			const colour =
				data.standing === 'Cannot register' ? 'var(--red-600)' : 'var(--blue-600)';
			value = `<span style="color: ${colour}; font-weight: 500">${value}</span>`;
		}

		// A student with nothing due this term is not being kept out of anything,
		// so they are dimmed rather than removed — they are still excluded, and
		// still worth seeing.
		if (column.fieldname === 'expected' && data.expected === __('Nothing this term')) {
			value = `<span style="color: var(--text-muted)">${value}</span>`;
		}

		if (column.fieldname === 'registered' && data.registered === __('Yes')) {
			value = `<span style="color: var(--green-600)">${value}</span>`;
		}

		return value;
	},
};
