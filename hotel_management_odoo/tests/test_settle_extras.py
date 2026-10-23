# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase


class TestSettleExtras(TransactionCase):
    def test_settle_accrues_loyalty_and_names_folio(self):
        prog = self.env['hotel.loyalty.program'].search([], limit=1)
        if not prog:
            prog = self.env['hotel.loyalty.program'].create(
                {'name': 'Stay Points', 'points_per_1000': 10.0})
        guest = self.env['res.partner'].create({'name': 'Loyal Guest'})
        folio = self.env['hotel.folio'].create(
            {'partner_id': guest.id})
        self.assertTrue(folio.name and folio.name != 'New')
        prod = self.env['product.product'].create({
            'name': 'Settle Extras Charge',
            'sale_ok': True,
            'list_price': 2000.0,
            'taxes_id': [(6, 0, [])],
        })
        self.env['hotel.charge.service'].post_charge(
            folio.id, prod.id, 1, 2000.0)
        folio.action_settle()
        entry = self.env['hotel.loyalty.entry'].search(
            [('program_id', '=', prog.id), ('folio_id', '=', folio.id)])
        self.assertTrue(entry)
        self.assertGreater(entry.points, 0)

    def test_view_folio_action_single_and_multi(self):
        guest = self.env['res.partner'].create({'name': 'Folio Btn Guest'})
        booking = self.env['room.booking'].create(
            {'partner_id': guest.id})
        f1 = self.env['hotel.folio'].create(
            {'partner_id': guest.id, 'booking_id': booking.id})
        f2 = self.env['hotel.folio'].create(
            {'partner_id': guest.id, 'booking_id': booking.id})
        multi = booking.action_view_folio()
        self.assertEqual(multi['res_model'], 'hotel.folio')
        self.assertIn('list', multi['view_mode'])
        f2.unlink()
        single = booking.action_view_folio()
        self.assertEqual(single.get('res_id'), f1.id)
        self.assertEqual(single['view_mode'], 'form')
