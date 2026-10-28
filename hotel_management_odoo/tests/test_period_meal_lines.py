# -*- coding: utf-8 -*-
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestPeriodMealLines(TransactionCase):
    def test_new_period_prefills_five_lines(self):
        defaults = self.env['hotel.rate.period'].default_get(
            ['meal_line_ids'])
        commands = defaults.get('meal_line_ids', [])
        self.assertEqual(len(commands), 5)
        plan_ids = set()
        for cmd in commands:
            self.assertEqual(cmd[0], 0)
            self.assertEqual(cmd[2].get('rate_type'), 'percent')
            self.assertEqual(cmd[2].get('value'), 0.0)
            plan_ids.add(cmd[2].get('meal_plan_id'))
        plans = self.env['hotel.meal.plan'].search(
            [('active', '=', True)])
        self.assertEqual(plan_ids, set(plans.ids))

    def test_lines_not_removable(self):
        period = self.env['hotel.rate.period'].create({
            'name': 'T1', 'start_md': '03-01', 'end_md': '03-31'})
        with self.assertRaises(ValidationError):
            period.meal_line_ids.unlink()

    def test_duplicate_plan_rejected(self):
        period = self.env['hotel.rate.period'].create({
            'name': 'T1', 'start_md': '03-01', 'end_md': '03-31'})
        line = period.meal_line_ids[:1]
        with self.assertRaises(ValidationError):
            self.env['hotel.rate.period.meal.line'].create({
                'period_id': period.id,
                'meal_plan_id': line.meal_plan_id.id,
                'rate_type': 'percent',
                'value': 5.0,
            })


class TestNewPlanBackfillsPeriods(TransactionCase):
    def test_new_plan_covers_all_periods(self):
        plan = self.env['hotel.meal.plan'].create({
            'name': 'Test Plan', 'code': 'TP', 'sequence': 60})
        periods = self.env['hotel.rate.period'].search([])
        lines = self.env['hotel.rate.period.meal.line'].search([
            ('meal_plan_id', '=', plan.id)])
        self.assertEqual(
            set(lines.mapped('period_id.id')), set(periods.ids))
        self.assertTrue(all(
            line.rate_type == 'percent' and line.value == 0.0
            for line in lines))
