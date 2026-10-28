# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase


class TestRatePriority(TransactionCase):
    def test_event_priority_beats_season(self):
        rtype = self.env['hotel.room.type'].create({
            'name': 'Deluxe', 'base_rate': 10000.0})
        plan = self.env['hotel.rate.plan'].create({'name': 'Rack'})
        dec = self.env['hotel.rate.period'].search(
            [('start_md', '=', '12-01')], limit=1)
        self.env['hotel.rate.rule'].create({
            'plan_id': plan.id, 'room_type_id': rtype.id,
            'period_id': dec.id, 'period_year': 2026,
            'date_from': '2026-12-20', 'date_to': '2026-12-31',
            'rate_type': 'percent', 'adjustment_pct': 30.0, 'priority': 50})
        self.env['hotel.rate.rule'].create({
            'plan_id': plan.id, 'room_type_id': rtype.id,
            'period_id': dec.id, 'period_year': 2026,
            'date_from': '2026-12-24', 'date_to': '2026-12-26',
            'rate_type': 'fixed', 'fixed_price': 25000.0, 'priority': 100})
        engine = self.env['hotel.rate.engine']
        # need room template linked to type for price_for compat shim
        room = self.env['product.template'].create({
            'name': '101', 'is_room': True, 'room_type': 'double',
            'num_person': 2, 'list_price': 10000.0, 'room_type_id': rtype.id})
        price = engine.price_for(room.id, '2026-12-25', plan.id)
        self.assertEqual(price, 25000.0)
        self.assertIsInstance(price, float)
