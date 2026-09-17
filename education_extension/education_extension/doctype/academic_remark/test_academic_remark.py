# Copyright (c) 2026, Asante Solutions and Contributors
# See license.txt

# import frappe
from frappe.tests import IntegrationTestCase


# Stops Frappe walking this app link fields into every other app; see the
# note beside the list.
from education_extension.education_extension.testing import (  # noqa: F401
	IGNORE_TEST_RECORD_DEPENDENCIES,
)



class IntegrationTestAcademicRemark(IntegrationTestCase):
	"""
	Integration tests for AcademicRemark.
	Use this class for testing interactions between multiple components.
	"""

	pass
