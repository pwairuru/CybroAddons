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

    def test_action_open_product_returns_linked_product(self):
        svc = self.env['hotel.service'].create(
            {'name': 'Spa Open Test', 'unit_price': 20.0})
        action = svc.action_open_product()
        self.assertEqual(action['res_id'], svc.product_id.id)
        self.assertEqual(action['res_model'], 'product.product')

    def test_hotel_sold_stat_counts_posted_folio_lines(self):
        svc = self.env['hotel.service'].create(
            {'name': 'Spa Sold Test', 'unit_price': 50.0})
        guest = self.env['res.partner'].create({'name': 'Sold Guest'})
        folio = self.env['hotel.folio'].create({'partner_id': guest.id})
        self.env['hotel.folio.line'].create({
            'folio_id': folio.id, 'product_id': svc.product_id.id,
            'quantity': 2.0, 'price_unit': 50.0})
        self.assertEqual(svc.hotel_sold_qty, 2.0)
        self.assertEqual(svc.hotel_revenue, 100.0)
        action = svc.action_view_hotel_sales()
        self.assertEqual(action['res_model'], 'hotel.folio.line')
