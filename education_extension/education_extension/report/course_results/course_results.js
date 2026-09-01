// Copyright (c) 2026, Asante Solutions and contributors
// For license information, please see license.txt

// Comments are written straight from the report, because checking a mark and
// deciding its comment is one job rather than two. The codes come from the
// server so the list here cannot drift from the one the legend explains.
let remark_codes = null

function get_remark_codes() {
	if (remark_codes) return Promise.resolve(remark_codes)
	return frappe
		.call('education_extension.education_extension.marking.get_remark_codes')
		.then((r) => {
			remark_codes = r.message || []
			return remark_codes
		})
}

function edit_remark(student, doctype, fieldname, title) {
	const report = frappe.query_report
	const keys = {
		student: student,
		course: report.get_filter_value('course'),
		academic_year: report.get_filter_value('academic_year'),
		academic_term: report.get_filter_value('academic_term'),
	}

	Promise.all([get_remark_codes(), frappe.db.get_value(doctype, keys, ['name', fieldname])]).then(
		([codes, res]) => {
			const existing = (res && res.message) || {}

			frappe.prompt(
				[
					{
						fieldname: fieldname,
						fieldtype: 'Select',
						label: __('Comment'),
						options: [''].concat(codes).join('\n'),
						default: existing[fieldname] || '',
					},
				],
				(values) => {
					const comment = values[fieldname] || ''
					const done = () => {
						frappe.show_alert({ message: __('Comment saved'), indicator: 'green' })
						report.refresh()
					}

					if (existing.name) {
						frappe.db.set_value(doctype, existing.name, fieldname, comment).then(done)
					} else {
						frappe.call({
							method: 'frappe.client.insert',
							args: {
								doc: Object.assign({ doctype: doctype, [fieldname]: comment }, keys),
							},
							callback: (r) => {
								if (!r.exc) done()
							},
						})
					}
				},
				__('{0} for {1}', [title, student]),
				__('Save'),
			)
		},
	)
}

frappe.query_reports['Course Results'] = {
	filters: [
		{
			fieldname: 'course',
			label: __('Module'),
			fieldtype: 'Link',
			options: 'Course',
			reqd: 1,
		},
		{
			fieldname: 'academic_year',
			label: __('Academic Year'),
			fieldtype: 'Link',
			options: 'Academic Year',
			reqd: 1,
		},
		{
			fieldname: 'academic_term',
			label: __('Academic Semester'),
			fieldtype: 'Link',
			options: 'Academic Term',
			reqd: 1,
			get_query: () => {
				const year = frappe.query_report.get_filter_value('academic_year')
				return year ? { filters: { academic_year: year } } : {}
			},
		},
	],

	formatter: function (value, row, column, data, default_formatter) {
		if (!data) return default_formatter(value, row, column, data)

		if (column.fieldname === 'action' || column.fieldname === 'supp_action') {
			const supplementary = column.fieldname === 'supp_action'
			return `<a class="course-results-edit" data-student="${frappe.utils.escape_html(
				data.student,
			)}" data-supplementary="${supplementary ? 1 : 0}">${__('Edit')}</a>`
		}

		// A mark that is not there reads as a dash, not an empty cell, so a
		// missing mark and a zero can never look the same.
		if (value === '-') {
			return `<span class="text-muted">${value}</span>`
		}

		return default_formatter(value, row, column, data)
	},

	onload: function (report) {
		// Delegated, because the report redraws its rows on every refresh.
		$(report.wrapper).on('click', '.course-results-edit', function () {
			const student = $(this).attr('data-student')
			if ($(this).attr('data-supplementary') === '1') {
				edit_remark(student, 'Supplementary Academic Remark', 'supp_remark', __('Supp comment'))
			} else {
				edit_remark(student, 'Academic Remark', 'remark', __('Comment'))
			}
		})
	},
}
