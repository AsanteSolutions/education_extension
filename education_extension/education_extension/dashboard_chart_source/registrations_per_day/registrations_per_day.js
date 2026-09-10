// Copyright (c) 2026, Asante Solutions and contributors
// For license information, please see license.txt

// The client asks the server for this file and evaluates it, which is how a
// Custom chart learns where to fetch its data, and what to offer in its filter
// dialog. Without it the chart draws nothing and says nothing -- there is no
// error, only an empty box.
//
// The term has no default. Dashboard filters are evaluated in the browser and
// cannot ask Python which registration period is open, so the server chooses
// when this is left empty -- which is the ordinary case. Setting it is for
// looking back at a window that has already closed.

frappe.provide("frappe.dashboards.chart_sources");

frappe.dashboards.chart_sources["Registrations Per Day"] = {
	method: "education_extension.education_extension.dashboard_chart_source.registrations_per_day.registrations_per_day.get",
	filters: [
		{
			fieldname: "academic_term",
			label: __("Academic Term"),
			fieldtype: "Link",
			options: "Academic Term",
			description: __("Leave empty for the registration window in focus"),
		},
	],
};
