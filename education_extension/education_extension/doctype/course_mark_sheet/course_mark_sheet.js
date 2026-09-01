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
		render_mark_entry(frm)
		render_qa_review(frm)
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

// ---------------------------------------------------------------------------
// Mark entry grid: students down, assessments across
//
// The child-table grid pages at fifty rows, and a course of eighty students
// across eight assessments is six hundred and fifty rows — fourteen pages of
// scrolling to enter one column of marks. This lays the sheet out the way a
// mark sheet is actually read, a row per student, and keeps the keyboard on the
// numbers.
//
// A cell takes a mark, or "a" for absent, or nothing at all where a mark has
// not been awarded yet. Only the cells that changed are sent back.
// ---------------------------------------------------------------------------

const ABSENT_INPUT = /^(a|abs|absent|-)$/i

function render_mark_entry(frm) {
	const field = frm.get_field('mark_entry')
	if (!field) return

	const $wrapper = $(field.wrapper).empty()
	const entries = frm.doc.entries || []

	if (!entries.length) {
		$wrapper.html(
			'<div class="text-muted" style="padding:12px 0">' +
				__('No marks to enter yet. Generate Entries builds the sheet from the course mark scheme.') +
				'</div>',
		)
		return
	}

	const editable = ENTRY_STATES.includes(frm.doc.workflow_state) && frm.doc.docstatus === 0
	const students = []
	const assessments = []
	const cells = {}

	for (const entry of entries) {
		if (!students.some((student) => student.id === entry.student)) {
			students.push({ id: entry.student, name: entry.student_name || entry.student })
		}
		if (!assessments.includes(entry.assessment_group)) assessments.push(entry.assessment_group)
		cells[entry.student + '|' + entry.assessment_group] = entry
	}

	const escape = frappe.utils.escape_html
	const changed = new Map()

	const header = assessments
		.map((name) => '<th class="text-center" style="min-width:88px">' + escape(name) + '</th>')
		.join('')

	const body = students
		.map((student, row) => {
			const columns = assessments
				.map((assessment, column) => {
					const entry = cells[student.id + '|' + assessment]
					if (!entry) return '<td></td>'

					let value = ''
					if (entry.status === 'Marked') value = entry.raw_score
					else if (entry.status === 'Absent') value = 'A'

					return (
						'<td style="padding:2px">' +
						'<input type="text" class="form-control input-sm mark-cell text-center"' +
						' data-student="' + escape(student.id) + '"' +
						' data-assessment="' + escape(assessment) + '"' +
						' data-max="' + (entry.maximum_score || 100) + '"' +
						' data-row="' + row + '" data-col="' + column + '"' +
						' value="' + value + '"' + (editable ? '' : ' readonly') + '>' +
						'</td>'
					)
				})
				.join('')

			return (
				'<tr><td class="text-muted small" style="white-space:nowrap">' + escape(student.id) + '</td>' +
				'<td style="white-space:nowrap">' + escape(student.name) + '</td>' +
				columns +
				'</tr>'
			)
		})
		.join('')

	$wrapper.html(
		'<div class="mark-entry">' +
			'<div class="flex justify-between align-center" style="margin-bottom:8px">' +
				'<div class="text-muted small mark-entry-status"></div>' +
				'<button class="btn btn-primary btn-sm mark-entry-save"' + (editable ? '' : ' disabled') + '>' +
					__('Save Marks') +
				'</button>' +
			'</div>' +
			'<div style="overflow:auto;max-height:60vh;border:1px solid var(--border-color)">' +
				'<table class="table table-bordered table-condensed" style="margin:0">' +
					'<thead style="position:sticky;top:0;background:var(--fg-color);z-index:1"><tr>' +
						'<th style="min-width:96px">' + __('Student') + '</th>' +
						'<th style="min-width:180px">' + __('Name') + '</th>' +
						header +
					'</tr></thead>' +
					'<tbody>' + body + '</tbody>' +
				'</table>' +
			'</div>' +
			'<div class="text-muted small" style="margin-top:6px">' +
				__('Type a mark, or "a" for absent. An empty cell has not been marked yet. Enter moves down the column.') +
			'</div>' +
		'</div>',
	)

	const $status = $wrapper.find('.mark-entry-status')
	const $save = $wrapper.find('.mark-entry-save')

	function update_status() {
		const total = frm.doc.entries.length
		const outstanding = frm.doc.entries.filter((entry) => entry.status === 'Not Marked').length
		let text = __('{0} of {1} entered', [total - outstanding, total])
		if (changed.size) text += ' &middot; <b>' + __('{0} unsaved', [changed.size]) + '</b>'
		$status.html(text)
		$save.prop('disabled', !editable || !changed.size)
	}

	$wrapper.on('change', '.mark-cell', function () {
		const $input = $(this)
		const parsed = parse_mark($input.val(), Number($input.attr('data-max')))

		// A cell that cannot be read says so rather than saving a guess.
		$input.css('border-color', parsed ? '' : 'var(--red-500)')
		if (!parsed) return

		// .attr() rather than .data(): jQuery reads a numeric-looking student id
		// as a Number, and the sheet holds it as a string.
		const student = $input.attr('data-student')
		const assessment = $input.attr('data-assessment')

		changed.set(student + '|' + assessment, {
			student: student,
			assessment_group: assessment,
			status: parsed.status,
			raw_score: parsed.raw_score,
		})
		update_status()
	})

	// Enter and the arrows move down the column, which is how a column of marks
	// gets entered without reaching for the mouse.
	$wrapper.on('keydown', '.mark-cell', function (event) {
		let step = 0
		if (event.key === 'Enter' || event.key === 'ArrowDown') step = 1
		else if (event.key === 'ArrowUp') step = -1
		if (!step) return

		event.preventDefault()
		const row = Number($(this).attr('data-row')) + step
		const $next = $wrapper.find(
			'.mark-cell[data-row="' + row + '"][data-col="' + $(this).attr('data-col') + '"]',
		)
		if ($next.length) $next.trigger('focus').trigger('select')
	})

	$save.on('click', () => {
		if (!changed.size) return
		$save.prop('disabled', true)
		frm
			.call('save_marks', { changes: [...changed.values()] })
			.then((r) => {
				changed.clear()
				if (r.message && r.message.ignored) {
					frappe.msgprint({
						title: __('Some marks were not saved'),
						message: __(
							'{0} of {1} changes did not match a row on this sheet and were ignored.',
							[r.message.ignored, r.message.ignored + r.message.applied],
						),
						indicator: 'red',
					})
				} else if (r.message) {
					frappe.show_alert({
						message: __('{0} saved, {1} still to enter', [
							r.message.applied,
							r.message.outstanding,
						]),
						indicator: r.message.outstanding ? 'orange' : 'green',
					})
				}
				frm.reload_doc()
			})
			.catch(() => $save.prop('disabled', false))
	})

	update_status()
}

// A cell holds a mark, an absence, or nothing yet. Anything else returns null so
// the cell can be flagged instead of guessed at.
function parse_mark(value, maximum) {
	const text = (value || '').trim()
	if (!text) return { status: 'Not Marked', raw_score: 0 }
	if (ABSENT_INPUT.test(text)) return { status: 'Absent', raw_score: 0 }

	const score = Number(text)
	if (Number.isNaN(score) || score < 0 || score > maximum) return null
	return { status: 'Marked', raw_score: score }
}

// ---------------------------------------------------------------------------
// QA review: the sheet in the shape the Course Results report shows it
//
// Once the marks are in, the sheet stops being a grid to fill and becomes a set
// of results to read: every score, the semester mark, the final mark and the
// comment, a row per student. The marks are not editable here — they are what
// is under review — but the comments are, because deciding a mark is sound and
// deciding what to call it is one job.
// ---------------------------------------------------------------------------

const REVIEW_STATES = ['Submitted for Checking', 'Checked', 'Moderated', 'Approved', 'Released']

let remark_codes = null

function get_remark_codes() {
	if (remark_codes) return Promise.resolve(remark_codes)
	return frappe
		.call('education_extension.education_extension.marking.get_remark_codes')
		.then((r) => (remark_codes = r.message || []))
}

function render_qa_review(frm) {
	const field = frm.get_field('qa_review')
	if (!field) return

	const $wrapper = $(field.wrapper).empty()
	if (!REVIEW_STATES.includes(frm.doc.workflow_state)) {
		$wrapper.html(
			'<div class="text-muted" style="padding:12px 0">' +
				__('Available once the sheet has been submitted for checking.') +
				'</div>',
		)
		return
	}

	frm.call('qa_review').then((r) => {
		if (!r.message) return
		draw_qa_table(frm, $wrapper, r.message)
	})
}

function draw_qa_table(frm, $wrapper, data) {
	const escape = frappe.utils.escape_html
	const coursework = data.criteria.filter((c) => c.component === 'Coursework')
	const examination = data.criteria.filter((c) => c.component !== 'Coursework')
	const editable = frm.doc.docstatus === 0

	const head = []
		.concat(
			['<th style="min-width:96px">' + __('Student') + '</th>'],
			['<th style="min-width:200px">' + __('Name') + '</th>'],
			coursework.map((c) => '<th class="text-center">' + escape(c.assessment_group) + '</th>'),
			['<th class="text-center">' + __('Semester Mark') + '</th>'],
			examination.map((c) => '<th class="text-center">' + escape(c.assessment_group) + '</th>'),
			[
				'<th class="text-center">' + __('Final Mark') + '</th>',
				'<th class="text-center">' + __('Supp Mark') + '</th>',
				'<th class="text-center">' + __('Remark') + '</th>',
				'<th class="text-center">' + __('Supp Remark') + '</th>',
			],
		)
		.join('')

	const cell = (value) =>
		value === '-'
			? '<td class="text-center text-muted">-</td>'
			: '<td class="text-center">' + escape(String(value)) + '</td>'

	const comment_cell = (student, value, supplementary) =>
		'<td class="text-center">' +
		'<a class="qa-comment" data-student="' + escape(student) + '"' +
		' data-supplementary="' + (supplementary ? 1 : 0) + '">' +
		(value ? '<b>' + escape(value) + '</b>' : (editable ? __('add') : '—')) +
		'</a></td>'

	const body = data.rows
		.map((row) => {
			// A student still missing a mark is the thing a checker is looking for,
			// so the row says so rather than leaving them to spot a dash.
			const outstanding = row.missing && row.missing.length
			return (
				'<tr' + (outstanding ? ' class="text-danger"' : '') + '>' +
				'<td class="text-muted small" style="white-space:nowrap">' + escape(row.student) + '</td>' +
				'<td style="white-space:nowrap">' + escape(row.student_name) +
				(outstanding
					? ' <span class="text-danger small">(' + __('missing {0}', [escape(row.missing.join(', '))]) + ')</span>'
					: '') +
				'</td>' +
				coursework.map((c) => cell(row.scores[c.assessment_group])).join('') +
				cell(row.dp) +
				examination.map((c) => cell(row.scores[c.assessment_group])).join('') +
				cell(row.final_mark) +
				cell(row.supplementary) +
				comment_cell(row.student, row.remark, false) +
				comment_cell(row.student, row.supp_remark, true) +
				'</tr>'
			)
		})
		.join('')

	const commented = data.rows.filter((r) => r.remark).length
	const incomplete = data.rows.filter((r) => r.missing && r.missing.length).length

	$wrapper.html(
		'<div class="qa-review">' +
			'<div class="text-muted small" style="margin-bottom:8px">' +
				__('{0} students &middot; {1} commented &middot; {2} incomplete', [
					data.rows.length, commented, incomplete,
				]) +
				(data.moderated ? ' &middot; <b>' + __('showing moderated marks') + '</b>' : '') +
			'</div>' +
			'<div style="overflow:auto;max-height:60vh;border:1px solid var(--border-color)">' +
				'<table class="table table-bordered table-condensed" style="margin:0">' +
					'<thead style="position:sticky;top:0;background:var(--fg-color);z-index:1"><tr>' +
						head +
					'</tr></thead><tbody>' + body + '</tbody>' +
				'</table>' +
			'</div>' +
		'</div>',
	)

	$wrapper.on('click', '.qa-comment', function () {
		if (!editable) return
		edit_comment(frm, $(this).attr('data-student'), $(this).attr('data-supplementary') === '1')
	})
}

// Comments are stored as Academic Remarks against the course and term, the same
// records the printed report reads, so nothing has to be copied across on
// approval.
function edit_comment(frm, student, supplementary) {
	const doctype = supplementary ? 'Supplementary Academic Remark' : 'Academic Remark'
	const fieldname = supplementary ? 'supp_remark' : 'remark'
	const keys = {
		student: student,
		course: frm.doc.course,
		academic_year: frm.doc.academic_year,
		academic_term: frm.doc.academic_term,
	}

	Promise.all([get_remark_codes(), frappe.db.get_value(doctype, keys, [fieldname])]).then(
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
						render_qa_review(frm)
					}
					frappe.call({
						method: 'education_extension.education_extension.marking.set_course_remark',
						args: {
							student: student,
							course: frm.doc.course,
							academic_year: frm.doc.academic_year,
							academic_term: frm.doc.academic_term,
							comment: comment,
							supplementary: supplementary ? 1 : 0,
						},
						callback: (r) => {
							if (!r.exc) done()
						},
					})
				},
				__('Comment for {0}', [student]),
				__('Save'),
			)
		},
	)
}
