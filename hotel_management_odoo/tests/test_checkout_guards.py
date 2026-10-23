# -*- coding: utf-8 -*-
from datetime import date, timedelta

from odoo.tests.common import TransactionCase
from odoo.exceptions import ValidationError


class TestCheckoutGuards(TransactionCase):
    def _available_room(self):
        for room in self.env['product.template'].search(
                [('is_room', '=', True)]):
            try:
                self.env['room.booking']._check_room_available(
                    room, '2026-11-01 14:00:00', '2026-11-03 11:00:00')
            except Exception:
                continue
            return room
        self.fail('no available room for 2026-11-01..03')

    def _mk_booking(self):
        guest = self.env['res.partner'].create({'name': 'Guard Guest'})
        room = self._available_room()
        bk = self.env['room.booking'].create({
            'partner_id': guest.id,
            'room_line_ids': [(0, 0, {'room_id': room.id,
                                      'checkin_date': '2026-11-01 14:00:00',
                                      'checkout_date': '2026-11-03 11:00:00'})]})
        bk.action_reserve()
        return bk

    def test_cancel_blocked_by_draft_deposit(self):
        bk = self._mk_booking()
        folio = self.env['hotel.folio'].search(
            [('booking_id', '=', bk.id)])
        self.env['hotel.deposit'].create(
            {'folio_id': folio.id, 'amount': 100.0})
        with self.assertRaises(ValidationError):
            bk.action_cancel()

    def test_checkout_clears_future_uninvoiced_lines(self):
        bk = self._mk_booking()
        bk.action_checkin()
        folio = self.env['hotel.folio'].search(
            [('booking_id', '=', bk.id)])
        prod = bk.room_line_ids[:1].room_id.product_variant_id
        Svc = self.env['hotel.charge.service']
        future = (date.today() + timedelta(days=13)).isoformat()
        past = (date.today() - timedelta(days=5)).isoformat()
        Svc.post_charge(folio.id, prod.id, 1, 10.0, 'to_guest',
                        hotel_date=future)
        Svc.post_charge(folio.id, prod.id, 1, 10.0, 'to_guest',
                        hotel_date=past)
        bk.action_checkout()
        dates = sorted(str(l.hotel_date) for l in folio.line_ids)
        self.assertNotIn(future, dates)
        self.assertIn(past, dates)
