# -*- coding: utf-8 -*-
"""Negotiated (locked) room rates must flow to folio + invoice.

Receptionists negotiate rates on the booking line (price_unit is
editable). Folio posting (checkout auto-post and night audit) must
bill the locked quote, not the engine rate, so the guest invoice
matches the reservation.
"""
from datetime import date, timedelta

from odoo import fields
from odoo.tests.common import TransactionCase


class TestLockedNegotiatedRate(TransactionCase):
    def _setup(self, name='LockFam'):
        co = self.env.company
        rtype = self.env['hotel.room.type'].create(
            {'name': name, 'base_rate': 20000.0,
             'adult_capacity': 2, 'child_capacity': 3,
             'max_occupants': 5, 'charge_mode': 'per_room'})
        meal = self.env['hotel.meal.plan'].search(
            [('code', '=', 'BB')], limit=1)
        period = self.env['hotel.rate.period'].create(
            {'name': name + 'H', 'start_md': '01-01', 'end_md': '12-31',
             'sequence': 10, 'priority': 10, 'company_id': co.id})
        self.env['hotel.rate.plan'].create(
            {'name': name + 'BB', 'code': 'BB', 'company_id': co.id})
        self.env['hotel.rate.line'].create(
            {'company_id': co.id, 'period_id': period.id,
             'room_type_id': rtype.id, 'meal_plan_id': meal.id,
             'price': 20000.0, 'included_adults': 2,
             'included_children': 0, 'extra_adult_mode': 'fixed',
             'extra_adult_value': 3000.0})
        room = self.env['product.template'].create(
            {'name': name + '-101', 'is_room': True, 'num_person': 5,
             'list_price': 20000.0, 'room_type_id': rtype.id})
        return co, room

    def _booking(self, co, room, name='LockFam'):
        now = fields.Datetime.now()
        booking = self.env['room.booking'].create({
            'partner_id': self.env.company.partner_id.id,
            'company_id': co.id, 'meal_plan': 'BB',
            'checkin_date': now + timedelta(days=-1),
            'checkout_date': now})
        line = self.env['room.booking.line'].create({
            'booking_id': booking.id, 'room_id': room.id,
            'checkin_date': now + timedelta(days=-1),
            'checkout_date': now,
            'adults': 2, 'company_id': co.id})
        return booking, line

    def test_checkout_posts_locked_price(self):
        """Checkout bills the negotiated rent; invoice == reservation."""
        co, room = self._setup()
        booking, line = self._booking(co, room)
        # Engine quote first, then receptionist negotiates down.
        self.assertEqual(line.price_unit, 20000.0)
        line.write({'price_unit': 18000.0})
        booking.action_reserve()
        booking.action_checkin()
        booking.action_checkout()
        folio = self.env['hotel.folio'].search(
            [('booking_id', '=', booking.id)], limit=1)
        room_lines = folio.line_ids.filtered(
            lambda l: l.product_id.id == room.product_variant_id.id)
        self.assertTrue(room_lines, "checkout must post room nights")
        for fl in room_lines:
            self.assertEqual(fl.price_unit, 18000.0,
                             "folio must bill the locked quote")
        room_total = sum(room_lines.mapped('price_total'))
        self.assertEqual(room_total, 18000.0)
        posted = folio.invoice_ids.filtered(
            lambda m: m.state == 'posted')
        self.assertTrue(posted, "checkout must invoice posted nights")
        self.assertEqual(posted[:1].amount_total, booking.amount_total,
                         "invoice must match the reservation total")

    def test_unedited_line_uses_engine_price(self):
        """No negotiation -> engine pricing unchanged (fallback)."""
        co, room = self._setup(name='LockFb')
        booking, line = self._booking(co, room, name='LockFb')
        self.assertEqual(line.price_unit, 20000.0)
        booking.action_reserve()
        booking.action_checkin()
        booking.action_checkout()
        folio = self.env['hotel.folio'].search(
            [('booking_id', '=', booking.id)], limit=1)
        room_lines = folio.line_ids.filtered(
            lambda l: l.product_id.id == room.product_variant_id.id)
        self.assertTrue(room_lines)
        for fl in room_lines:
            self.assertEqual(fl.price_unit, 20000.0)


class TestNightAuditLockedRate(TransactionCase):
    def test_audit_posts_locked_price(self):
        """Night audit bills the negotiated rent for the covered night."""
        co = self.env.company
        rtype = self.env['hotel.room.type'].create(
            {'name': 'LockAud', 'base_rate': 20000.0,
             'adult_capacity': 2, 'child_capacity': 3,
             'max_occupants': 5, 'charge_mode': 'per_room'})
        meal = self.env['hotel.meal.plan'].search(
            [('code', '=', 'BB')], limit=1)
        period = self.env['hotel.rate.period'].create(
            {'name': 'LockAudH', 'start_md': '01-01', 'end_md': '12-31',
             'sequence': 10, 'priority': 10, 'company_id': co.id})
        self.env['hotel.rate.plan'].create(
            {'name': 'LockAudBB', 'code': 'BB', 'company_id': co.id})
        self.env['hotel.rate.line'].create(
            {'company_id': co.id, 'period_id': period.id,
             'room_type_id': rtype.id, 'meal_plan_id': meal.id,
             'price': 20000.0, 'included_adults': 2,
             'included_children': 0})
        room = self.env['product.template'].create(
            {'name': 'LockAud-101', 'is_room': True, 'num_person': 5,
             'list_price': 20000.0, 'room_type_id': rtype.id})
        booking = self.env['room.booking'].create({
            'partner_id': self.env.company.partner_id.id,
            'company_id': co.id, 'meal_plan': 'BB',
            'checkin_date': '2027-03-10 14:00:00',
            'checkout_date': '2027-03-12 11:00:00'})
        line = self.env['room.booking.line'].create({
            'booking_id': booking.id, 'room_id': room.id,
            'checkin_date': '2027-03-10 14:00:00',
            'checkout_date': '2027-03-12 11:00:00',
            'uom_qty': 2.0, 'adults': 2, 'company_id': co.id})
        self.assertEqual(line.price_unit, 20000.0)
        line.write({'price_unit': 17000.0})
        booking.with_context(hotel_allow_state_write=True).write(
            {'state': 'check_in'})
        self.env['hotel.business.date'].create({'date': '2027-03-10'})
        audit = self.env['hotel.night.audit'].create(
            {'date': '2027-03-10'})
        audit._post_room_nights(date(2027, 3, 10))
        folio = self.env['hotel.folio'].search(
            [('booking_id', '=', booking.id)], limit=1)
        night = folio.line_ids.filtered(
            lambda l: l.hotel_date == date(2027, 3, 10))
        self.assertTrue(night, "audit must post the covered night")
        self.assertEqual(night[:1].price_unit, 17000.0,
                         "audit must bill the locked quote")
