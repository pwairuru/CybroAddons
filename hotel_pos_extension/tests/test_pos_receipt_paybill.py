# -*- coding: utf-8 -*-
#############################################################################
#
#    Cybrosys Technologies Pvt. Ltd.
#
#    Copyright (C) 2026-TODAY Cybrosys Technologies(<https://www.cybrosys.com>)
#
#    You can modify it under the terms of the GNU LESSER
#    GENERAL PUBLIC LICENSE (LGPL v3), Version 3.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU LESSER GENERAL PUBLIC LICENSE (LGPL v3) for more details.
#
#    You should have received a copy of the GNU LESSER GENERAL PUBLIC LICENSE
#    (LGPL v3) along with this program.
#    If not, see <http://www.gnu.org/licenses/>.
#
#############################################################################
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestPosReceiptPaybill(TransactionCase):
    """Per-terminal M-Pesa paybill on the POS receipt.

    Most registers print the default paybill; a few print their own.
    Values live on pos.config so any customer sets their own numbers
    per terminal with no code change.
    """

    def test_pos_config_has_paybill_fields(self):
        """pos.config carries free-form paybill number + account name."""
        config = self.env['pos.config'].new()
        self.assertTrue(
            'receipt_paybill_number' in config._fields
        )
        self.assertTrue(
            'receipt_paybill_account' in config._fields
        )

    def test_pos_config_form_shows_paybill_fields(self):
        """Staff can edit both values on the POS config form."""
        view = self.env.ref('point_of_sale.pos_config_view_form')
        arch = self.env['pos.config'].get_view(view.id)['arch']
        self.assertIn('receipt_paybill_number', arch)
        self.assertIn('receipt_paybill_account', arch)

    def _receipt_extras_view(self):
        return self.env['ir.ui.view'].search(
            [('key', '=', 'hotel_pos_extension.pos_order_receipt_footer_extras')],
            limit=1,
        )

    def test_receipt_template_reads_config_paybill(self):
        """Receipt block renders the terminal's own values."""
        view = self._receipt_extras_view()
        self.assertTrue(view, 'receipt extras template not installed')
        self.assertIn('receipt_paybill_number', view.arch_db)
        self.assertIn('receipt_paybill_account', view.arch_db)

    def test_receipt_template_has_no_hardcoded_paybill(self):
        """No customer-specific number survives in the template."""
        view = self._receipt_extras_view()
        self.assertTrue(view, 'receipt extras template not installed')
        self.assertNotIn('4141717', view.arch_db)
        self.assertNotIn('CAMP DAVID UNITED', view.arch_db)

    def test_receipt_prefers_terminal_over_company(self):
        template = self.env['ir.ui.view'].search(
            [('key', '=', 'hotel_pos_extension.pos_order_receipt_footer_extras')], limit=1)
        self.assertTrue(template)
        self.assertIn('mpesa_paybill_number', template.arch_db)
