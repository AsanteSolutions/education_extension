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
			download_progress_report(frm)
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

const PROGRESS_REPORT_METHOD =
	'education_extension.education_extension.doctype.student_progress_report.student_progress_report.preview_progress_report'

/**
 * Generate the report and hand the browser the PDF file itself.
 *
 * The endpoint streams PDF bytes back, so posting a form at it (open_url_post)
 * only parked the user on an /api/method URL rendered by the browser's PDF
 * viewer. Fetching the response as a blob instead keeps the user on the form and
 * saves a real, correctly named .pdf.
 */
async function download_progress_report(frm) {
	frappe.dom.freeze(__('Generating Progress Report...'))
	try {
		const response = await fetch(`/api/method/${PROGRESS_REPORT_METHOD}`, {
			method: 'POST',
			credentials: 'same-origin',
			headers: {
				'Content-Type': 'application/json',
				'X-Frappe-CSRF-Token': frappe.csrf_token,
			},
			// The endpoint expects `doc` as a JSON string, not a nested object.
			body: JSON.stringify({ doc: JSON.stringify(frm.doc) }),
		})

		// Failures come back as JSON (or an HTML error page), never as a PDF.
		const content_type = response.headers.get('Content-Type') || ''
		if (!response.ok || !content_type.includes('application/pdf')) {
			frappe.msgprint({
				title: __('Could not generate the Progress Report'),
				message: progress_report_error(await response.text()),
				indicator: 'red',
			})
			return
		}

		const blob = await response.blob()
		const url = URL.createObjectURL(blob)
		const link = document.createElement('a')
		link.href = url
		link.download =
			filename_from_response(response) ||
			`Progress Report - ${frm.doc.student_name || frm.doc.student}.pdf`
		document.body.appendChild(link)
		link.click()
		link.remove()
		// Released on the next tick, once the click has been handled.
		setTimeout(() => URL.revokeObjectURL(url), 0)
	} catch (error) {
		frappe.msgprint({
			title: __('Could not generate the Progress Report'),
			message: error.message || __('An unknown error occurred.'),
			indicator: 'red',
		})
	} finally {
		frappe.dom.unfreeze()
	}
}

/** Filename the server set on the response, e.g. `inline; filename="X.pdf"`. */
function filename_from_response(response) {
	const disposition = response.headers.get('Content-Disposition') || ''
	// The RFC 5987 form (filename*=UTF-8'') is percent-encoded; the plain one is not.
	const encoded = disposition.match(/filename\*=UTF-8''([^;]+)/i)
	if (encoded) {
		return decodeURIComponent(encoded[1])
	}
	const plain = disposition.match(/filename="?([^";]+)"?/i)
	return plain ? plain[1].trim() : ''
}

/** Pull a readable message out of a Frappe error response body. */
function progress_report_error(body) {
	try {
		const data = JSON.parse(body)
		const messages = JSON.parse(data._server_messages || '[]').map((message) => {
			try {
				return JSON.parse(message).message
			} catch (error) {
				return message
			}
		})
		return (
			messages.join('<br>') ||
			data.exception ||
			data.message ||
			__('An unknown error occurred.')
		)
	} catch (error) {
		return __('An unknown error occurred.')
	}
}
