# -*- coding: utf-8 -*-
from datetime import date

from odoo.tests.common import TransactionCase


class TestAnchorPricing(TransactionCase):
    """First-night anchor: quote + audit charge use check-in date price.

    Stay 2027-01-30 -> 2027-02-02 on BB: Jan BB +10% of 12000 =
    13200/night, Feb BB +50% = 18000/night. Anchor => 13200 flat.
    """

    def setUp(self):
        super().setUp()
        self.dtype = self.env['hotel.room.type'].create({
            'name': 'AnchorT', 'base_rate': 10000.0})
        bb = self.env['hotel.meal.plan'].search(
            [('code', '=', 'BB')], limit=1)
        self.dtype.meal_price_ids.filtered(
            lambda l: l.meal_plan_id.id == bb.id).write(
                {'price': 12000.0})
        jan = self.env['hotel.rate.period'].search(
            [('start_md', '=', '01-01')], limit=1)
        jan.meal_line_ids.filtered(
            lambda l: l.meal_plan_id.id == bb.id).write(
                {'rate_type': 'percent', 'value': 10.0})
        feb = self.env['hotel.rate.period'].search(
            [('start_md', '=', '02-01')], limit=1)
        feb.meal_line_ids.filtered(
            lambda l: l.meal_plan_id.id == bb.id).write(
                {'rate_type': 'percent', 'value': 50.0})
        self.booking = self.env['room.booking'].create({
            'partner_id': self.env.company.partner_id.id,
            'checkin_date': '2027-01-30 14:00:00',
            'checkout_date': '2027-02-02 11:00:00',
            'meal_plan': 'BB',
        })
        self.plan = self.env['hotel.rate.plan']._plan_for_booking(
            self.booking)
        for period in (jan, feb):
            self.env['hotel.rate.rule'].create({
                'plan_id': self.plan.id,
                'room_type_id': self.dtype.id,
                'period_id': period.id,
                'period_year': 2027,
                'rate_type': 'percent',
                'adjustment_pct': 0.0,
            })
        self.room = self.env['product.template'].create({
            'name': 'RM301', 'is_room': True, 'room_type': 'double',
            'num_person': 2, 'list_price': 10000.0,
            'room_type_id': self.dtype.id})
        self.line = self.env['room.booking.line'].create({
            'booking_id': self.booking.id,
            'room_id': self.room.id,
            'checkin_date': '2027-01-30 14:00:00',
            'checkout_date': '2027-02-02 11:00:00',
            'uom_qty': 3.0,
            'adults': 2,
            'children': 0,
        })
        self.engine = self.env['hotel.rate.engine']

    def test_feb_night_differs_from_anchor(self):
        feb_price = self.engine.price_for(
            self.room.id, '2027-02-01', self.plan.id,
            adults=2, board='BB')
        self.assertEqual(feb_price, 18000.0)

    def test_quote_uses_first_night(self):
        self.assertEqual(self.line.price_unit, 13200.0)

    def test_quote_frozen_after_checkin(self):
        self.assertEqual(self.line.price_unit, 13200.0)
        self.booking.with_context(
            hotel_allow_state_write=True).write({'state': 'check_in'})
        self.assertEqual(self.line.price_unit, 13200.0)
        self.booking.write({'meal_plan': 'FB'})
        self.assertEqual(self.line.price_unit, 13200.0)

    def test_audit_posts_anchor_price(self):
        self.booking.with_context(
            hotel_allow_state_write=True).write({'state': 'check_in'})
        biz = self.env['hotel.business.date'].create(
            {'date': '2027-02-01'})
        audit = self.env['hotel.night.audit'].create(
            {'date': '2027-02-01'})
        audit._post_room_nights(date(2027, 2, 1))
        folio = self.env['hotel.folio'].search(
            [('booking_id', '=', self.booking.id)], limit=1)
        self.assertTrue(folio)
        night = folio.line_ids.filtered(
            lambda l: l.hotel_date == date(2027, 2, 1))
        self.assertTrue(night)
        self.assertEqual(night[:1].price_unit, 13200.0)
