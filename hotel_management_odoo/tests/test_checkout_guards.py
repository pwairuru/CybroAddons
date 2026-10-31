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

    def _mk_checked_in_with_folios(self):
        bk = self._mk_booking()
        bk.action_checkin()
        folio_a = bk._ensure_folio()
        prod = bk.room_line_ids[:1].room_id.product_variant_id
        Svc = self.env['hotel.charge.service']
        Svc.post_charge(folio_a.id, prod.id, 1, 700.0, 'to_guest')
        guest_b = self.env['res.partner'].create({'name': 'Second Folio'})
        folio_b = self.env['hotel.folio'].create({
            'partner_id': guest_b.id, 'booking_id': bk.id,
            'company_id': bk.company_id.id})
        Svc.post_charge(folio_b.id, prod.id, 1, 300.0, 'to_guest')
        return bk, folio_a, folio_b

    def test_checkout_posts_all_open_folios(self):
        bk, folio_a, folio_b = self._mk_checked_in_with_folios()
        bk.action_checkout()
        move_a = folio_a.invoice_ids.filtered(
            lambda m: m.state == 'posted')
        move_b = folio_b.invoice_ids.filtered(
            lambda m: m.state == 'posted')
        self.assertEqual(len(move_a), 1)
        self.assertEqual(len(move_b), 1)
        self.assertEqual(move_a.amount_total, 700.0)
        self.assertEqual(move_b.amount_total, 300.0)

    def test_booking_pay_delegates_to_dues_folio(self):
        bk, folio_a, folio_b = self._mk_checked_in_with_folios()
        move_b = folio_b.action_post_invoice()
        wizard = bk.action_register_payment()
        self.assertEqual(wizard['context']['active_ids'], [move_b.id])

    def test_booking_pay_with_two_dues_folios_directs_per_folio(self):
        bk, folio_a, folio_b = self._mk_checked_in_with_folios()
        folio_a.action_post_invoice()
        folio_b.action_post_invoice()
        with self.assertRaises(ValidationError):
            bk.action_register_payment()
