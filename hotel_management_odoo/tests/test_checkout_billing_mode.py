# -*- coding: utf-8 -*-
"""Checkout billing modes (RES/2026/2085 regression).

Default Check-Out bills the full stay: future uninvoiced folio lines
survive. The cog-menu "consumed only" variant keeps the old
early-checkout sweep (future lines cleared, past kept).
"""
from datetime import date, timedelta

from odoo.tests.common import TransactionCase


class TestCheckoutBillingMode(TransactionCase):
    def _mk_checked_in(self):
        co = self.env.company
        rtype = self.env['hotel.room.type'].create({
            'name': 'Billing Mode Type',
            'base_rate': 10000.0,
            'adult_capacity': 2,
            'child_capacity': 2,
            'max_occupants': 4,
            'charge_mode': 'per_room',
        })
        meal_ro = self.env['hotel.meal.plan'].search(
            [('code', '=', 'RO')], limit=1)
        if not meal_ro:
            meal_ro = self.env['hotel.meal.plan'].create({
                'name': 'Room Only', 'code': 'RO'})
        period = self.env['hotel.rate.period'].create({
            'name': 'BillingMode All Year',
            'start_md': '01-01', 'end_md': '12-31',
            'sequence': 1, 'priority': 200,
            'company_id': co.id,
        })
        self.env['hotel.rate.line'].create({
            'company_id': co.id,
            'period_id': period.id,
            'room_type_id': rtype.id,
            'meal_plan_id': meal_ro.id,
            'price': 10000.0,
        })
        if not self.env['hotel.rate.plan'].search(
                [('company_id', '=', co.id)], limit=1):
            self.env['hotel.rate.plan'].create({
                'name': 'Rack', 'code': 'RO', 'company_id': co.id})
        partner = self.env['res.partner'].create(
            {'name': 'Billing Mode Guest'})
        room_template = self.env['product.template'].create({
            'name': 'Billing Mode Room',
            'is_room': True,
            'list_price': 10000.0,
            'num_person': 2,
            'room_type_id': rtype.id,
        })
        bk = self.env['room.booking'].create({
            'partner_id': partner.id,
            'meal_plan': 'RO',
            'checkin_date': '2026-11-01 14:00:00',
            'checkout_date': '2026-11-03 11:00:00',
            'state': 'check_in',
            'room_line_ids': [(0, 0, {
                'room_id': room_template.id,
                'checkin_date': '2026-11-01 14:00:00',
                'checkout_date': '2026-11-03 11:00:00',
            })],
        })
        return bk, room_template

    def _sentinel_lines(self, folio, prod):
        Svc = self.env['hotel.charge.service']
        future = (date.today() + timedelta(days=13)).isoformat()
        past = (date.today() - timedelta(days=5)).isoformat()
        Svc.post_charge(folio.id, prod.id, 1, 777.0, 'to_guest',
                        hotel_date=future, source='rate')
        Svc.post_charge(folio.id, prod.id, 1, 888.0, 'to_guest',
                        hotel_date=past, source='rate')
        return future, past

    def test_default_checkout_keeps_future_lines(self):
        """Full-stay default: future rate lines survive checkout."""
        bk, room_template = self._mk_checked_in()
        folio = bk._ensure_folio()
        prod = room_template.product_variant_id
        future, past = self._sentinel_lines(folio, prod)
        bk.action_checkout()
        dates = sorted(str(line.hotel_date) for line in folio.line_ids)
        self.assertIn(
            future, dates,
            "default checkout must not clear future stay lines")
        self.assertIn(past, dates)

    def test_consumed_only_checkout_clears_future_lines(self):
        """Early-checkout variant: future cleared, past kept."""
        bk, room_template = self._mk_checked_in()
        folio = bk._ensure_folio()
        prod = room_template.product_variant_id
        future, past = self._sentinel_lines(folio, prod)
        bk.action_checkout_consumed_only()
        dates = sorted(str(line.hotel_date) for line in folio.line_ids)
        self.assertNotIn(future, dates)
        self.assertIn(past, dates)
