app_name = "education_extension"
app_title = "Education Extension"
app_publisher = "Asante Solutions"
app_description = "Extension for the Frappe Education app"
app_email = "apile@asantesolutions.co.za"
app_license = "mit"

# Website route rules
# -------------------
# Map deep links under the student portal SPA back to its shell page, so that
# reloading a client-side route (e.g. /student-portal/schedule) serves the app
# instead of 404ing (Frappe has no server page at the sub-path).
website_route_rules = [
	{"from_route": "/student-portal/<path:app_path>", "to_route": "student-portal"},
]

# Apps
# ------------------

# Nearly everything here reads or writes the education app's doctypes — Student,
# Course, Program Enrollment, Academic Year, Academic Term, Assessment Result.
# Without it this app installs onto a site where none of that exists and fails at
# the first registration or mark, rather than at install time where the problem
# can be read. Frappe checks this before installing, so it fails early instead.
required_apps = ["education"]

# Shown as its own tile on the apps screen, next to Education rather than buried
# inside it. The route is this app own workspace; the permission check keeps the
# tile off the screen of anyone who has no business on that page.
add_to_apps_screen = [
	{
		"name": "education_extension",
		"logo": "/assets/education_extension/education-extension-logo.svg",
		"title": "Education Extension",
		"route": "/app/education-extension",
		"has_permission": "education_extension.education_extension.desk.has_app_permission",
	}
]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/education_extension/css/education_extension.css"
# app_include_js = "/assets/education_extension/js/education_extension.js"

# include js, css files in header of web template
# web_include_css = "/assets/education_extension/css/education_extension.css"
# web_include_js = "/assets/education_extension/js/education_extension.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "education_extension/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "education_extension/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# automatically load and sync documents of this doctype from downstream apps
# importable_doctypes = [doctype_1]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "education_extension.utils.jinja_methods",
# 	"filters": "education_extension.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "education_extension.install.before_install"
after_install = "education_extension.education_extension.desk.apply_desk_records"

# Runs last, after the education app has re-synced its own Workspace and
# Workspace Sidebar over whatever was in the database. Anything added to those
# by hand does not survive a migrate; this re-applies our links so they do.
after_migrate = ["education_extension.education_extension.desk.apply_desk_records"]

# Uninstallation
# ------------

# before_uninstall = "education_extension.uninstall.before_uninstall"
# after_uninstall = "education_extension.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "education_extension.utils.before_app_install"
# after_app_install = "education_extension.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "education_extension.utils.before_app_uninstall"
# after_app_uninstall = "education_extension.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "education_extension.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# Document Events
# ---------------
# Hook on document methods and events

# A provisional registration is one taken on a prerequisite whose result had not
# landed. The moment that result settles — submitted, corrected after submission,
# or withdrawn — the registration may need to change, so every event that can
# alter a remark re-checks the student. The work is queued rather than done
# inline: marking a whole sheet would otherwise pay for it on every row.
_RESOLVE_PROVISIONAL = {
	"on_submit": "education_extension.education_extension.registration.on_remark_change",
	"on_update_after_submit": "education_extension.education_extension.registration.on_remark_change",
	"on_cancel": "education_extension.education_extension.registration.on_remark_change",
}

# Mirroring between the education records and the LMS, which used to be six
# Server Scripts on before_insert and before_delete. On those events the mirror
# sat on the critical path of the thing being mirrored, so anything it threw took
# the original write down with it. These fire after the fact and only queue.
_LMS_SYNC = "education_extension.education_extension.lms_sync."
_STUDENT_PERMISSIONS = "education_extension.education_extension.student_permissions."

doc_events = {
	"Academic Remark": _RESOLVE_PROVISIONAL,
	"Supplementary Academic Remark": _RESOLVE_PROVISIONAL,
	"Program Enrollment": {
		"after_insert": _LMS_SYNC + "on_program_enrollment",
		"on_trash": _LMS_SYNC + "on_program_enrollment_trash",
	},
	"Course Enrollment": {
		"after_insert": _LMS_SYNC + "on_course_enrollment",
		"on_trash": _LMS_SYNC + "on_course_enrollment_trash",
	},
	"LMS Program": {"after_insert": _LMS_SYNC + "on_lms_program"},
	"LMS Course": {"after_insert": _LMS_SYNC + "on_lms_course"},
	# A student sees their own records and no one else's. Role permissions are
	# per doctype and cannot say "only your own", so it takes a User Permission,
	# created here for every new student and moved if their account changes.
	"Student": {
		"after_insert": _STUDENT_PERMISSIONS + "on_student_insert",
		"on_update": _STUDENT_PERMISSIONS + "on_student_update",
		"on_trash": _STUDENT_PERMISSIONS + "on_student_trash",
	},
}

# Scheduled Tasks
# ---------------

# A backstop for the doc events above. They cover the normal path; this catches a
# result that settled while the queue was down, or a registration that became
# resolvable because the window closed rather than because anything was marked.
scheduler_events = {
	"daily": [
		"education_extension.education_extension.registration.resolve_provisional_registrations",
	],
}

# scheduler_events = {
# 	"all": [
# 		"education_extension.tasks.all"
# 	],
# 	"daily": [
# 		"education_extension.tasks.daily"
# 	],
# 	"hourly": [
# 		"education_extension.tasks.hourly"
# 	],
# 	"weekly": [
# 		"education_extension.tasks.weekly"
# 	],
# 	"monthly": [
# 		"education_extension.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "education_extension.install.before_tests"

# Extend DocType Class
# ------------------------------
#
# Specify custom mixins to extend the standard doctype controller.
# extend_doctype_class = {
# 	"Task": "education_extension.custom.task.CustomTaskMixin"
# }

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "education_extension.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "education_extension.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["education_extension.utils.before_request"]
# after_request = ["education_extension.utils.after_request"]

# Job Events
# ----------
# before_job = ["education_extension.utils.before_job"]
# after_job = ["education_extension.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"education_extension.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []

