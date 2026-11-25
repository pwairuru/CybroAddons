# -*- coding: utf-8 -*-
"""Per-person quoting must scale with head count on every path.

Regression tests for the bug where ``hotel.room.type`` set to
``per_person`` still quoted 1x line price when 2 adults were entered:
``compute_night`` scaled correctly but ``price_detailed`` reassembled
``net = resolved + extras`` and dropped the adult multiplier, so the
booking form, folio posting and snapshots all stayed flat.
"""
from odoo import fields
from odoo.tests.common import TransactionCase


class TestPerPersonQuote(TransactionCase):
    def setUp(self):
        super().setUp()
        self.co = self.env.company
        self.bb = self.env['hotel.meal.plan'].search(
            [('code', '=', 'BB')], limit=1)
        self.assertTrue(self.bb, "BB meal plan must exist")
        self.rtype = self.env['hotel.room.type'].create({
            'name': 'PPQuote', 'base_rate': 10000.0,
            'adult_capacity': 2, 'child_capacity': 2,
            'max_occupants': 4, 'charge_mode': 'per_person',
            'company_id': self.co.id,
        })
        self.period = self.env['hotel.rate.period'].create({
            'name': 'PPQ-H1', 'start_md': '01-01', 'end_md': '12-31',
            'sequence': 10, 'priority': 10, 'company_id': self.co.id})
        self.env['hotel.rate.line'].create({
            'company_id': self.co.id, 'period_id': self.period.id,
            'room_type_id': self.rtype.id, 'meal_plan_id': self.bb.id,
            'price': 10000.0, 'included_adults': 2,
            'included_children': 1, 'extra_child_mode': 'fixed',
            'extra_child_value': 1500.0})
        self.room = self.env['product.template'].create({
            'name': 'PPQ-101', 'is_room': True, 'room_type': 'double',
            'num_person': 4, 'list_price': 10000.0,
            'room_type_id': self.rtype.id})
        self.plan = self.env['hotel.rate.plan'].create({
            'name': 'PPQ Rack', 'company_id': self.co.id})
        self.engine = self.env['hotel.rate.engine']

    def test_engine_scales_with_adults(self):
        one = self.engine.price_detailed(
            self.room.id, '2027-05-01', self.plan.id,
            adults=1, children=0, board='BB')
        two = self.engine.price_detailed(
            self.room.id, '2027-05-01', self.plan.id,
            adults=2, children=0, board='BB')
        self.assertEqual(one['net'], 10000.0)
        self.assertEqual(two['net'], 20000.0)

    def test_engine_per_person_child_extra_on_top(self):
        detailed = self.engine.price_detailed(
            self.room.id, '2027-05-01', self.plan.id,
            adults=2, children=2, board='BB')
        # 2 x 10000 + 1 extra child x 1500 (1 child included)
        self.assertEqual(detailed['net'], 21500.0)

    def test_engine_per_room_control_unchanged(self):
        self.rtype.write({'charge_mode': 'per_room'})
        line = self.env['hotel.rate.line'].search([
            ('room_type_id', '=', self.rtype.id)], limit=1)
        line.write({'extra_adult_mode': 'fixed',
                    'extra_adult_value': 3000.0})
        two = self.engine.price_detailed(
            self.room.id, '2027-05-01', self.plan.id,
            adults=2, children=0, board='BB')
        three = self.engine.price_detailed(
            self.room.id, '2027-05-01', self.plan.id,
            adults=3, children=0, board='BB')
        self.assertEqual(two['net'], 10000.0)
        self.assertEqual(three['net'], 13000.0)

    def _booking_line(self, adults=1):
        booking = self.env['room.booking'].create({
            'partner_id': self.co.partner_id.id,
            'company_id': self.co.id, 'meal_plan': 'BB',
            'checkin_date': '2027-05-01 14:00:00',
            'checkout_date': '2027-05-02 11:00:00'})
        return self.env['room.booking.line'].create({
            'booking_id': booking.id, 'room_id': self.room.id,
            'checkin_date': '2027-05-01 14:00:00',
            'checkout_date': '2027-05-02 11:00:00',
            'meal_plan': 'BB', 'adults': adults, 'children': 0})

    def test_booking_line_requotes_on_adult_change(self):
        """Booking page: 1 adult quotes 1x, switching to 2 requotes 2x."""
        line = self._booking_line(adults=1)
        self.assertEqual(line.price_unit, 10000.0)
        line.write({'adults': 2})
        self.assertEqual(line.price_unit, 20000.0)
        # price_subtotal is VAT-excluded (16% VAT on top).
        self.assertAlmostEqual(line.price_subtotal, 20000.0 / 1.16, places=2)

    def test_booking_line_tax_scales_with_per_person(self):
        """'net' is the pre-tax nightly total; taxes apply on top."""
        line = self._booking_line(adults=1)
        group = self.env['account.tax.group'].create(
            {'name': 'PPQ VAT Group'})
        tax = self.env['account.tax'].create({
            'name': 'PPQ 10%', 'amount': 10.0, 'amount_type': 'percent',
            'type_tax_use': 'sale', 'tax_group_id': group.id,
            'price_include_override': 'tax_excluded',
        })
        line.write({'tax_ids': [(6, 0, [tax.id])]})
        self.assertEqual(line.price_subtotal, 10000.0)
        self.assertEqual(line.price_tax, 1000.0)
        self.assertEqual(line.price_total, 11000.0)
        line.write({'adults': 2})
        self.assertEqual(line.price_subtotal, 20000.0)
        self.assertEqual(line.price_tax, 2000.0)
        self.assertEqual(line.price_total, 22000.0)

    def test_folio_posts_scaled_per_person_per_night(self):
        booking = self.env['room.booking'].create({
            'partner_id': self.co.partner_id.id,
            'company_id': self.co.id, 'meal_plan': 'BB'})
        folio = booking._ensure_folio()
        lines = self.engine.post_stay_nights(
            folio.id, self.room.id, '2027-05-01', '2027-05-03',
            self.plan.id, adults=2)
        self.assertEqual(len(lines), 2)
        # 10000 x 2 adults = 20000/night x 2 nights
        self.assertAlmostEqual(folio.amount_total, 40000.0, places=2)

    def test_period_priority_with_per_person_scaling(self):
        """Promo (higher priority) beats base season; both scale."""
        promo = self.env['hotel.rate.period'].create({
            'name': 'PPQ-Promo', 'start_md': '03-01', 'end_md': '03-31',
            'sequence': 5, 'priority': 100, 'company_id': self.co.id})
        self.env['hotel.rate.line'].create({
            'company_id': self.co.id, 'period_id': promo.id,
            'room_type_id': self.rtype.id, 'meal_plan_id': self.bb.id,
            'price': 15000.0, 'included_adults': 2,
            'included_children': 1, 'extra_child_mode': 'fixed',
            'extra_child_value': 1500.0})
        march = self.engine.price_detailed(
            self.room.id, '2027-03-15', self.plan.id,
            adults=2, children=0, board='BB')
        april = self.engine.price_detailed(
            self.room.id, '2027-04-15', self.plan.id,
            adults=2, children=0, board='BB')
        self.assertEqual(march['net'], 30000.0)
        self.assertEqual(april['net'], 20000.0)
