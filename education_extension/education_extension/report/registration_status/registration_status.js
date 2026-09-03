// Copyright (c) 2026, Asante Solutions and contributors
// For license information, please see license.txt

frappe.query_reports['Registration Status'] = {
	filters: [
		{
			fieldname: 'academic_term',
			label: __('Academic Term'),
			fieldtype: 'Link',
			options: 'Academic Term',
			reqd: 1,
			// The term with a registration window on it is almost always the one
			// being asked about, so it is the default when there is one.
			get_query: () => ({}),
		},
		{
			fieldname: 'status',
			label: __('Status'),
			fieldtype: 'Select',
			options: ['', 'Not registered', 'Registered', 'Not their term'].join('\n'),
			default: '',
		},
		{
			fieldname: 'program',
			label: __('Programme'),
			fieldtype: 'Link',
			options: 'Program',
		},
	],

	onload: (report) => {
		// Default the term to whichever one has a registration period, so the
		// report opens on the question being asked rather than empty.
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

	// Colour carries the triage: who to chase, and what needs deciding.
	formatter: (value, row, column, data, default_formatter) => {
		value = default_formatter(value, row, column, data);
		if (!data) return value;

		if (column.fieldname === 'status') {
			if (data.status === 'Not registered') {
				value = `<span style="color: var(--red-600); font-weight: 500">${value}</span>`;
			} else if (data.status === 'Registered') {
				value = `<span style="color: var(--green-600)">${value}</span>`;
			} else {
				value = `<span style="color: var(--gray-500)">${value}</span>`;
			}
		}

		if (column.fieldname === 'needs_review' && data.needs_review) {
			value = `<span style="color: var(--red-600); font-weight: 600">${value}</span>`;
		}

		if (column.fieldname === 'provisional' && data.provisional) {
			value = `<span style="color: var(--orange-600)">${value}</span>`;
		}

		return value;
	},
};
