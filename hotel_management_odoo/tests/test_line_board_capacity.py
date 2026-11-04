# -*- coding: utf-8 -*-
from datetime import date, timedelta

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestLineBoardCapacity(TransactionCase):
    """Per-line meal plan + configurable over-capacity policy.

    Fixtures are self-contained: LB Season (priority 100) beats any
    seeded season, so engine answers come only from LB rate lines.
    """
    tags = {'line_board'}

    def setUp(self):
        super().setUp()
        self.company = self.env.company
        self.company.write({'hotel_capacity_policy': 'block'})
        for code in ('BB', 'FB'):
            if not self.env['hotel.meal.plan'].search(
                    [('code', '=', code)], limit=1):
                self.env['hotel.meal.plan'].create({
                    'code': code, 'name': code})
        self.period = self.env['hotel.rate.period'].create({
            'name': 'LB Season', 'start_md': '01-01', 'end_md': '12-31',
            'sequence': 1, 'priority': 100,
            'company_id': self.company.id})
        self.dtype = self.env['hotel.room.type'].create({
            'name': 'LBType', 'code': 'LBT',
            'adult_capacity': 2, 'child_capacity': 1,
            'max_occupants': 3, 'base_rate': 25000.0,
            'company_id': self.company.id})
        kes = self.company.currency_id
        for code, price in (('BB', 25000.0), ('FB', 38500.0)):
            mp = self.env['hotel.meal.plan'].search(
                [('code', '=', code)], limit=1)
            self.env['hotel.rate.line'].create({
                'period_id': self.period.id,
                'room_type_id': self.dtype.id,
                'meal_plan_id': mp.id,
                'company_id': self.company.id,
                'plan_id': False,
                'currency_id': kes.id,
                'price': price,
                'included_adults': 2,
                'included_children': 0,
            })
        self.room = self.env['product.template'].create({
            'name': 'LB Room', 'is_room': True, 'room_type': 'double',
            'num_person': 2, 'list_price': 25000.0,
            'room_type_id': self.dtype.id})
        now = fields.Datetime.now()
        self.booking = self.env['room.booking'].create({
            'partner_id': self.company.partner_id.id,
            'checkin_date': now,
            'checkout_date': now + timedelta(days=1),
            'meal_plan': 'BB',
        })

    def _make_line(self, **kw):
        vals = {
            'booking_id': self.booking.id,
            'room_id': self.room.id,
            'checkin_date': self.booking.checkin_date,
            'checkout_date': self.booking.checkout_date,
            'adults': 1,
            'children': 0,
        }
        vals.update(kw)
        return self.env['room.booking.line'].create(vals)

    def test_line_inherits_booking_board(self):
        line = self._make_line()
        self.assertEqual(line.meal_plan, 'BB')

    def test_mixed_boards_price_per_line(self):
        bb_line = self._make_line()
        fb_line = self._make_line(meal_plan='FB')
        self.assertEqual(bb_line.price_unit, 25000.0)
        self.assertEqual(fb_line.price_unit, 38500.0)

    def test_block_mode_rejects_over_capacity(self):
        with self.assertRaises(ValidationError):
            self._make_line(adults=3)

    def test_warn_mode_allows_with_flag(self):
        self.company.write({'hotel_capacity_policy': 'warn'})
        line = self._make_line(adults=3)
        self.assertTrue(line.over_capacity)
        self.assertEqual(line.price_unit, 25000.0)

    def test_toddlers_never_count(self):
        line = self._make_line(adults=2, toddlers=2)
        self.assertFalse(line.over_capacity)

    def test_audit_posts_line_board(self):
        self.booking.with_context(
            hotel_allow_state_write=True).write({'state': 'check_in'})
        room2 = self.env['product.template'].create({
            'name': 'LB Room 2', 'is_room': True, 'room_type': 'double',
            'num_person': 2, 'list_price': 25000.0,
            'room_type_id': self.dtype.id})
        bb_line = self._make_line()
        fb_line = self._make_line(room_id=room2.id, meal_plan='FB')
        day = fields.Date.to_string(
            fields.Datetime.context_timestamp(
                self.booking, self.booking.checkin_date).date())
        self.env['hotel.night.audit']._post_room_nights(
            fields.Date.from_string(day))
        folio = self.env['hotel.folio'].search(
            [('booking_id', '=', self.booking.id)], limit=1)
        amounts = sorted(folio.line_ids.mapped('price_unit'))
        self.assertEqual(amounts, [25000.0, 38500.0])
