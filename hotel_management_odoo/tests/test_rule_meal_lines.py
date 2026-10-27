# -*- coding: utf-8 -*-
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestRuleMealLines(TransactionCase):
    def _type_plan(self):
        company = self.env.company
        dtype = self.env['hotel.room.type'].create({
            'name': 'RuleMealDeluxe', 'base_rate': 10000.0,
            'company_id': company.id,
        })
        plan = self.env['hotel.rate.plan'].create({
            'name': 'RuleMealRack', 'company_id': company.id})
        rule = self.env['hotel.rate.rule'].create({
            'plan_id': plan.id, 'room_type_id': dtype.id,
            'rate_type': 'percent', 'adjustment_pct': 0.0,
            'priority': 50, 'date_from': '2026-12-20',
            'date_to': '2026-12-31'})
        return dtype, plan, rule

    def test_rule_gets_five_lines(self):
        _dtype, _plan, rule = self._type_plan()
        self.assertEqual(len(rule.meal_line_ids), 5)
        self.assertEqual(
            sorted(rule.meal_line_ids.mapped('meal_plan_id.code')),
            ['BB', 'DP', 'FB', 'HB', 'RO'])

    def test_line_delete_blocked(self):
        _dtype, _plan, rule = self._type_plan()
        with self.assertRaises(ValidationError):
            rule.meal_line_ids[0].unlink()

    def test_percent_adjusts_plan_price(self):
        dtype, plan, rule = self._type_plan()
        dtype.meal_price_ids.filtered(
            lambda l: l.meal_plan_id.code == 'BB').write(
                {'price': 12000.0})
        rule.meal_line_ids.filtered(
            lambda l: l.meal_plan_id.code == 'BB').write(
                {'rate_type': 'percent', 'value': 10.0})
        room = self.env['product.template'].create({
            'name': 'RM101', 'is_room': True, 'room_type': 'double',
            'num_person': 2, 'list_price': 10000.0,
            'room_type_id': dtype.id})
        price = self.env['hotel.rate.engine'].price_for(
            room.id, '2026-12-24', plan.id, adults=2, board='BB')
        self.assertEqual(price, 13200.0)

    def test_period_fills_dates(self):
        _dtype, plan, _rule = self._type_plan()
        period = self.env['hotel.rate.period'].search(
            [('start_md', '=', '12-01')], limit=1)
        rule = self.env['hotel.rate.rule'].create({
            'plan_id': plan.id, 'period_id': period.id,
            'period_year': 2026,
            'rate_type': 'percent', 'adjustment_pct': 0.0,
            'priority': 10})
        self.assertEqual(rule.date_from.isoformat(), '2026-12-01')
        self.assertEqual(rule.date_to.isoformat(), '2026-12-31')
