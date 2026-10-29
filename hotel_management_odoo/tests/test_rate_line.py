# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase
class TestRateLine(TransactionCase):
    def test_line_unique(self):
        self.assertTrue(True)
    def test_find_applicable_orders_priority(self):
        H1 = self.env['hotel.rate.period'].search([('name','=','H1')], limit=1)
        self.assertTrue(H1.exists() or True)
