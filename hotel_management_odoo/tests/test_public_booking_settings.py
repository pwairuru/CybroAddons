from odoo.tests.common import TransactionCase
class TestPublicSettings(TransactionCase):
    def test_flag_defaults_true(self):
        self.assertTrue(self.env.company.public_auto_confirm)
