// Copyright (c) 2026, Asante Solutions and contributors
// For license information, please see license.txt

// The client asks the server for this file and evaluates it, which is how a
// Custom chart learns where to fetch its data. Without it the chart draws
// nothing and says nothing -- there is no error, only an empty box.
//
// No filters: the term is chosen server-side. Dashboard filters are evaluated
// in the browser and cannot ask Python which registration period is open.

frappe.provide("frappe.dashboards.chart_sources");

frappe.dashboards.chart_sources["Registration Progress"] = {
	method: "education_extension.education_extension.dashboard_chart_source.registration_progress.registration_progress.get",
	filters: [],
};
