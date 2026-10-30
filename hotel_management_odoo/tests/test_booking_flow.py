# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase


class TestBookingFlow(TransactionCase):
    def test_payment_carries_both_links(self):
        folio = self.env['hotel.folio'].create(
            {'partner_id': self.env.company.partner_id.id})
        booking = self.env['room.booking'].create(
            {'partner_id': folio.partner_id.id})
        move = folio.action_generate_draft_invoice()
        self.assertTrue(move)
        move.write({'hotel_folio_id': folio.id,
                    'hotel_booking_id': booking.id})
        pay = self.env['account.payment'].create({
            'payment_type': 'inbound',
            'partner_id': folio.partner_id.id,
            'amount': 10.0,
            'invoice_ids': [(6, 0, move.ids)],
        })
        self.assertEqual(pay.hotel_folio_id.id, folio.id)
        self.assertEqual(pay.hotel_booking_id.id, booking.id)

    def test_deposit_cancel_and_refund(self):
        folio = self.env['hotel.folio'].create(
            {'partner_id': self.env.company.partner_id.id})
        dep = self.env['hotel.deposit'].create(
            {'folio_id': folio.id, 'amount': 2000.0})
        dep.action_cancel_draft()
        self.assertEqual(dep.state, 'cancelled')
        dep2 = self.env['hotel.deposit'].create(
            {'folio_id': folio.id, 'amount': 1500.0})
        dep2.action_collect()
        rev = dep2.action_refund(reason="guest cancelled")
        self.assertEqual(dep2.state, 'refunded')
        self.assertTrue(rev)
        self.assertEqual(dep2.reversal_move_id.id, rev.id)
        again = dep2.action_refund()
        self.assertEqual(again.id, rev.id)

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

    def test_checkout_posts_invoice_and_done_needs_paid(self):
        from datetime import date, timedelta
        guest = self.env['res.partner'].create({'name': 'Flow Guest'})
        room = self._available_room()
        booking = self.env['room.booking'].create({
            'partner_id': guest.id,
            'room_line_ids': [(0, 0, {'room_id': room.id,
                                      'checkin_date': '2026-11-01 14:00:00',
                                      'checkout_date': '2026-11-03 11:00:00'})]})
        booking.action_reserve()
        booking.action_checkin()
        folio = self.env['hotel.folio'].search(
            [('booking_id', '=', booking.id)], limit=1)
        self.assertTrue(folio, "reserve must auto-create folio")
        prod = booking.room_line_ids[:1].room_id.product_variant_id
        past = (date.today() - timedelta(days=5)).isoformat()
        self.env['hotel.charge.service'].post_charge(
            folio.id, prod.id, 1, 10.0, 'to_guest', hotel_date=past)
        booking.action_checkout()
        self.assertEqual(booking.state, 'check_out')
        folio.invalidate_recordset()
        posted = folio.invoice_ids.filtered(lambda m: m.state == 'posted')
        self.assertTrue(posted, "checkout must auto-post an invoice")
        booking.invalidate_recordset()
        self.assertEqual(booking.invoice_status, 'invoiced')
        self.assertTrue(all(line.locked for line in booking.room_line_ids),
                        "posted invoice must lock booking lines")
        with self.assertRaises(Exception):
            booking.action_done()
        recept = self.env['res.users'].create({
            'name': 'Flow Reception', 'login': 'flow-recept',
            'group_ids': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref(
                    'hotel_management_odoo.hotel_group_reception').id,
            ])],
        })
        # Gate must hold for reception (no journal access): without
        # sudo() the move search would see nothing and unpaid Done
        # would slip through.
        with self.assertRaises(Exception):
            booking.with_user(recept).action_done()
        pay = self.env['account.payment'].create({
            'payment_type': 'inbound',
            'partner_id': guest.id,
            'amount': 5.0,
            'hotel_folio_id': folio.id,
            'hotel_booking_id': booking.id,
        })
        self.assertTrue(pay)
        booking.invalidate_recordset()
        self.assertGreaterEqual(booking.payment_count, 1)
        self.assertGreater(booking.amount_due, 0.0)

    def test_booking_views_have_payment_flow(self):
        view = self.env.ref(
            'hotel_management_odoo.room_booking_view_form')
        arch = view.arch_db
        self.assertIn('action_view_payments', arch)
        self.assertIn('action_register_payment', arch)
        self.assertIn('payment_count', arch)
        self.assertIn('state != \'check_out\'', arch)


class TestQuoteExtras(TransactionCase):
    def test_quote_includes_occupancy_extras(self):
        co = self.env.company
        rtype = self.env['hotel.room.type'].create(
            {'name': 'QuoteFam', 'base_rate': 20000.0,
             'adult_capacity': 2, 'child_capacity': 3,
             'max_occupants': 5, 'charge_mode': 'per_person'})
        rtype = self.env['hotel.room.type'].create(
            {'name': 'QuoteFam2', 'base_rate': 20000.0,
             'adult_capacity': 2, 'child_capacity': 3,
             'max_occupants': 5, 'charge_mode': 'per_room'})
        meal_ro = self.env['hotel.meal.plan'].search(
            [('code', '=', 'BB')], limit=1)
        period = self.env['hotel.rate.period'].create(
            {'name': 'QuoteH', 'start_md': '01-01', 'end_md': '12-31',
             'sequence': 10, 'priority': 10, 'company_id': co.id})
        self.env['hotel.rate.plan'].create(
            {'name': 'QuoteBB', 'code': 'BB', 'company_id': co.id})
        self.env['hotel.rate.line'].create(
            {'company_id': co.id, 'period_id': period.id,
             'room_type_id': rtype.id, 'meal_plan_id': meal_ro.id,
             'price': 20000.0, 'included_adults': 2,
             'included_children': 0, 'extra_adult_mode': 'fixed',
             'extra_adult_value': 3000.0})
        room = self.env['product.template'].create(
            {'name': 'Quote-101', 'is_room': True, 'num_person': 5,
             'list_price': 20000.0, 'room_type_id': rtype.id})
        booking = self.env['room.booking'].create({
            'partner_id': self.env.company.partner_id.id,
            'company_id': co.id, 'meal_plan': 'BB',
            'checkin_date': '2027-05-01 14:00:00',
            'checkout_date': '2027-05-02 11:00:00'})
        line = self.env['room.booking.line'].create({
            'booking_id': booking.id, 'room_id': room.id,
            'checkin_date': '2027-05-01 14:00:00',
            'checkout_date': '2027-05-02 11:00:00',
            'adults': 3, 'company_id': co.id})
        self.assertEqual(line.price_unit, 23000.0)
        self.assertEqual(line.extra_per_night, 3000.0)
