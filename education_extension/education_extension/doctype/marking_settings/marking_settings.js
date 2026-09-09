// Copyright (c) 2026, Asante Solutions and contributors
// For license information, please see license.txt

frappe.ui.form.on('Marking Settings', {
	refresh: function (frm) {
		frm.set_intro(
			__('These apply across mark entry and anywhere else a class is listed in order.'),
			'blue',
		)
	},
})
