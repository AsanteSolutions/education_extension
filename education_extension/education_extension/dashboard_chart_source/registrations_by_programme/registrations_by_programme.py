# Copyright (c) 2026, Asante Solutions and contributors
# For license information, please see license.txt

"""Which programmes the cohort registered into.

A thin wrapper. The counting lives in `dashboard.py` beside the other
numbers, so the chart and the cards cannot drift apart; all this adds is
the shape the chart widget expects and the caching that goes with it.
"""

import frappe
from frappe.utils.dashboard import cache_source

from education_extension.education_extension import dashboard


@frappe.whitelist()
@cache_source
def get(
	chart_name=None,
	chart=None,
	no_cache=None,
	filters=None,
	from_date=None,
	to_date=None,
	timespan=None,
	time_interval=None,
	heatmap_year=None,
):
	return dashboard.by_programme(filters)
