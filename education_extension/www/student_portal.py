import frappe

# The shell HTML embeds a session-specific CSRF token
# (window.csrf_token = '{{ frappe.session.csrf_token }}'). Frappe caches www
# pages by default, so without this the rendered HTML — token and all — is
# cached and served to other sessions with a stale/empty token, causing their
# API calls to 403 and the SPA to boot to a blank page until a hard refresh.
no_cache = 1


def get_context(context):
	context.no_cache = 1

	abbr = frappe.db.get_single_value(
		"Education Settings", "school_college_name_abbreviation"
	)
	logo = frappe.db.get_single_value("Education Settings", "school_college_logo")
	context.abbr = abbr or "Frappe Education"
	context.logo = logo or "/favicon.png"
