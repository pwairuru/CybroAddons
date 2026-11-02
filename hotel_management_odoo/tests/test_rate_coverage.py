# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase


class TestCoverage(TransactionCase):
    def _setup(self, name='CovT', base_rate=20000.0):
        co = self.env.company
        co.rate_missing_mode = 'fallback'
        rtype = self.env['hotel.room.type'].create({
            'name': name, 'base_rate': base_rate, 'max_occupants': 5})
        ro = self.env['hotel.meal.plan'].search(
            [('code', '=', 'RO')], limit=1)
        period = self.env['hotel.rate.period'].create({
            'name': 'CovP-%s' % name, 'start_md': '01-01',
            'end_md': '06-30', 'company_id': co.id,
            'priority': 50, 'sequence': 5})
        room = self.env['product.template'].create({
            'name': 'COV-%s' % name, 'is_room': True,
            'room_type': 'double', 'num_person': 5,
            'list_price': base_rate, 'room_type_id': rtype.id})
        self.env['hotel.rate.line'].create({
            'company_id': co.id, 'period_id': period.id,
            'room_type_id': rtype.id, 'meal_plan_id': ro.id,
            'price': base_rate})
        return co, rtype, period, room

    def test_coverage_counts(self):
        # 1 period x 1 type x 2 meals, only RO line -> covered RO, missing BB
        co, rtype, period, room = self._setup()
        meals = self.env['hotel.meal.plan'].search(
            [('active', '=', True)], order='code')
        cov = self.env['hotel.rate.engine'].matrix(
            [rtype.id], '2027-02-01', '2027-02-01', False, board=False)
        cell = cov['rows'][0]['cells'][0]
        self.assertIn('plans', cell)
        reasons = cell['plan_reasons']
        self.assertEqual(reasons['RO'], 'explicit')
        self.assertEqual(reasons['BB'], 'base-rate')
        action = self.env.ref(
            'hotel_management_odoo.action_rate_coverage')
        result = action.with_context(
            coverage_type_ids=[rtype.id],
            coverage_date_from='2027-02-01',
            coverage_date_to='2027-02-01').run()
        msg = result['params']['message']
        self.assertIn('1 green', msg)
        self.assertIn('0 yellow', msg)
        self.assertIn('%d red' % (len(meals) - 1), msg)
