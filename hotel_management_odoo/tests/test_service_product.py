# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase


class TestServiceProduct(TransactionCase):
    def test_create_autocreates_product_and_syncs(self):
        svc = self.env['hotel.service'].create(
            {'name': 'Spa Test', 'unit_price': 50.0})
        self.assertTrue(svc.product_id)
        self.assertEqual(svc.product_id.list_price, 50.0)
        svc.write({'unit_price': 60.0, 'name': 'Spa Test 2'})
        self.assertEqual(svc.product_id.list_price, 60.0)
        self.assertEqual(svc.product_id.name, 'Spa Test 2')
