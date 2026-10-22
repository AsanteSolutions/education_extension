// Copyright (c) 2026, Asante Solutions and contributors
// For license information, please see license.txt

frappe.query_reports['Module Registrations'] = {
	filters: [
		{
			fieldname: 'course',
			label: __('Module'),
			fieldtype: 'Link',
			options: 'Course',
			reqd: 1,
		},
		{
			fieldname: 'academic_term',
			label: __('Academic Term'),
			fieldtype: 'Link',
			options: 'Academic Term',
			// Not required. A module runs every year, and "who has ever taken
			// this" is a fair question — the Term column is there either way.
		},
		{
			fieldname: 'program',
			label: __('Programme'),
			fieldtype: 'Link',
			options: 'Program',
		},
	],

	onload: (report) => {
		// Default to the term with a registration window, the same as
		// Registration Status, so the two open on the same period.
		education_extension.default_report_term(report);
	},

	// The two columns anyone scans this list for: a place still to be confirmed,
	// and one the resolution job would not decide on its own.
	formatter: (value, row, column, data, default_formatter) => {
		value = default_formatter(value, row, column, data);
		if (!data) return value;

		if (column.fieldname === 'provisional' && data.provisional) {
			value = `<span style="color: var(--orange-600)">${value}</span>`;
		}

		if (column.fieldname === 'needs_review' && data.needs_review) {
			value = `<span style="color: var(--red-600); font-weight: 600">${value}</span>`;
		}

		return value;
	},
};
