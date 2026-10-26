# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import fields
from odoo.tests.common import TransactionCase


class TestRatePlanSelection(TransactionCase):
    """Board code must drive the plan used for pricing/posting."""

    def setUp(self):
        super().setUp()
        self.company = self.env.company
        self.company.default_rate_plan_id = False
        self.env['hotel.rate.plan'].search([]).write({'active': False})
        self.room_type = self.env['hotel.room.type'].create({
            'name': 'Deluxe',
            'base_rate': 10000.0,
            'adult_capacity': 3,
            'child_capacity': 1,
            'max_occupants': 4,
        })
        self.room = self.env['product.template'].create({
            'name': 'Board Test Room',
            'is_room': True,
            'room_type': 'double',
            'num_person': 3,
            'list_price': 10000.0,
            'room_type_id': self.room_type.id,
        })
        self.bb = self.env['hotel.rate.plan'].create({
            'name': 'BB Board',
            'code': 'BB',
            'company_id': self.company.id,
        })
        self.hb = self._plan_with_price('HB Board', 'HB', 12000.0)
        self._plan_with_price('FB Board', 'FB', 15000.0)
        self.env['hotel.rate.occupancy'].create({
            'room_type_id': self.room_type.id,
            'plan_id': self.hb.id,
            'band': 'adult',
            'included_count': 1,
            'max_count': 3,
            'mode': 'percent',
            'value': 100.0,
            'basis': 'resolved_rate',
        })
        self.company.default_rate_plan_id = self.bb.id

    def _plan_with_price(self, name, code, price):
        pricelist = self.env['product.pricelist'].create({
            'name': '%s Rates' % code,
            'currency_id': self.company.currency_id.id,
        })
        self.env['product.pricelist.item'].create({
            'pricelist_id': pricelist.id,
            'applied_on': '1_product',
            'product_tmpl_id': self.room.id,
            'compute_price': 'fixed',
            'fixed_price': price,
            'min_quantity': 0,
        })
        return self.env['hotel.rate.plan'].create({
            'name': name,
            'code': code,
            'company_id': self.company.id,
            'pricelist_id': pricelist.id,
        })

    def _booking(self, meal_plan='HB', state='reserved',
                 checkin_days=-1, checkout_days=1):
        now = fields.Datetime.now()
        booking = self.env['room.booking'].create({
            'partner_id': self.company.partner_id.id,
            'checkin_date': now + timedelta(days=checkin_days),
            'checkout_date': now + timedelta(days=checkout_days),
            'state': state,
            'meal_plan': meal_plan,
        })
        self.env['room.booking.line'].create({
            'booking_id': booking.id,
            'room_id': self.room.id,
            'checkin_date': now + timedelta(days=checkin_days),
            'checkout_date': now + timedelta(days=checkout_days),
            'adults': 2,
        })
        return booking

    def test_plan_for_booking_uses_meal_plan_code(self):
        booking = self._booking('HB')
        plan = self.env['hotel.rate.plan']._plan_for_booking(booking)
        self.assertEqual(plan, self.hb)

    def test_ro_falls_back_to_company_default(self):
        booking = self._booking('RO')
        plan = self.env['hotel.rate.plan']._plan_for_booking(booking)
        self.assertEqual(plan, self.bb)

    def test_post_stay_defaults_to_booking_plan(self):
        booking = self._booking('HB')
        wizard = self.env['hotel.post.stay'].with_context(
            default_booking_id=booking.id).create({})
        self.assertEqual(wizard.plan_id, self.hb)

    def test_extra_estimate_uses_booking_plan(self):
        booking = self._booking('HB')
        line = booking.room_line_ids
        self.assertEqual(line.extra_per_night, 12000.0)

    def test_night_audit_posts_matching_board_rate(self):
        booking = self._booking('HB', state='check_in')
        audit_date = fields.Date.today() - timedelta(days=1)
        self.env['hotel.night.audit'].run(audit_date.isoformat())
        folio = self.env['hotel.folio'].search(
            [('booking_id', '=', booking.id)], limit=1)
        room_lines = folio.line_ids.filtered(
            lambda line: line.hotel_date == audit_date)
        self.assertEqual(len(room_lines), 1)
        self.assertEqual(room_lines.price_unit, 24000.0)
