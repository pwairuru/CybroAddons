# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase


class TestRateCalendarMatrix(TransactionCase):
    def _setup(self):
        rtype = self.env['hotel.room.type'].create({
            'name': 'Deluxe', 'base_rate': 10000.0})
        plan = self.env['hotel.rate.plan'].create({'name': 'Rack'})
        vals = {'is_room': True, 'room_type': 'double',
                'num_person': 2, 'list_price': 10000.0,
                'room_type_id': rtype.id}
        room1 = self.env['product.template'].create(dict(vals, name='201'))
        room2 = self.env['product.template'].create(dict(vals, name='202'))
        return rtype, plan, room1, room2

    def test_matrix_returns_delta_and_closed(self):
        rtype, plan, room1, room2 = self._setup()
        self.env['hotel.rate.rule'].create({
            'plan_id': plan.id, 'room_type_id': rtype.id,
            'date_from': '2026-12-24', 'date_to': '2026-12-26',
            'rate_type': 'percent', 'adjustment_pct': 50.0,
            'priority': 10})
        data = self.env['hotel.rate.engine'].matrix(
            [rtype.id], '2026-12-24', '2026-12-26', plan.id)
        self.assertEqual(len(data['dates']), 3)
        self.assertIn('delta_pct', data['rows'][0]['cells'][0])
        self.assertAlmostEqual(
            data['rows'][0]['cells'][0]['delta_pct'], 50.0)
        self.assertIn('closed', data['rows'][0]['cells'][0])
        self.assertFalse(data['rows'][0]['cells'][0]['closed'])

    def test_matrix_closed_min_stay_available(self):
        rtype, plan, room1, room2 = self._setup()
        self.env['hotel.rate.rule'].create({
            'plan_id': plan.id, 'room_type_id': rtype.id,
            'date_from': '2026-12-24', 'date_to': '2026-12-26',
            'rate_type': 'percent', 'adjustment_pct': 0.0,
            'priority': 10, 'min_stay': 3})
        self.env['hotel.rate.restriction'].create({
            'plan_id': plan.id, 'room_template_id': room1.id,
            'date_from': '2026-12-25', 'date_to': '2026-12-25',
            'closed': True})
        self.env['hotel.business.date'].create({
            'date': '2026-12-26', 'is_closed': True,
            'company_id': self.env.company.id})
        booking = self.env['room.booking'].create({
            'partner_id': self.env.company.partner_id.id,
            'checkin_date': '2026-12-24 14:00:00',
            'checkout_date': '2026-12-25 11:00:00',
            'room_line_ids': [(0, 0, {
                'room_id': room1.id,
                'checkin_date': '2026-12-24 14:00:00',
                'checkout_date': '2026-12-25 11:00:00',
            })],
        })
        booking.action_reserve()
        data = self.env['hotel.rate.engine'].matrix(
            [rtype.id], '2026-12-24', '2026-12-26', plan.id)
        cells = {c['date']: c for c in data['rows'][0]['cells']}
        self.assertEqual(cells['2026-12-24']['min_stay'], 3)
        self.assertFalse(cells['2026-12-24']['closed'])
        self.assertEqual(cells['2026-12-24']['available'], 1)
        self.assertTrue(cells['2026-12-25']['closed'])
        self.assertTrue(cells['2026-12-26']['closed'])

    def test_matrix_all_plans(self):
        rtype, plan, room1, room2 = self._setup()
        data = self.env['hotel.rate.engine'].matrix(
            [rtype.id], '2026-12-20', '2026-12-21', plan.id,
            False)
        cell = data['rows'][0]['cells'][0]
        self.assertEqual(
            sorted(cell['plans'].keys()), ['BB', 'DP', 'FB', 'HB', 'RO'])
        self.assertEqual(cell['plans']['RO'], cell['price'])
        self.assertEqual(cell['period'], 'December')
        self.assertEqual(data['periods'][0], 'December')

    def test_matrix_caps_at_42_days(self):
        rtype, plan, room1, room2 = self._setup()
        data = self.env['hotel.rate.engine'].matrix(
            [rtype.id], '2026-01-01', '2026-12-31')
        self.assertEqual(len(data['dates']), 42)

    def test_matrix_ignores_other_company_ooo_and_board(self):
        rtype, plan, room1, room2 = self._setup()
        other = self.env['res.company'].create({'name': 'Other Co'})
        other_team = self.env['maintenance.team'].create({
            'name': 'Other Maint', 'company_id': other.id})
        self.env['maintenance.request'].create({
            'name': 'OOO other co',
            'type': 'room',
            'company_id': other.id,
            'maintenance_team_id': other_team.id,
            'room_maintenance_ids': [(6, 0, [room1.id])],
        })
        self.env['hotel.board.rule'].create({
            'company_id': other.id,
            'room_type_id': rtype.id,
            'plan_id': plan.id,
            'board': 'BB',
            'date_from': '2026-12-24', 'date_to': '2026-12-26',
            'supplement': 5000.0,
        })
        data = self.env['hotel.rate.engine'].matrix(
            [rtype.id], '2026-12-24', '2026-12-26', plan.id, board='BB')
        cells = {c['date']: c for c in data['rows'][0]['cells']}
        self.assertEqual(cells['2026-12-24']['available'], 2)
        self.assertAlmostEqual(cells['2026-12-24']['board'], 0.0)
        self.assertAlmostEqual(cells['2026-12-24']['total'],
                               cells['2026-12-24']['price'])

    def test_period_matrix_range(self):
        rtype, plan, room1, room2 = self._setup()
        self.env['hotel.rate.rule'].create({
            'plan_id': plan.id, 'room_type_id': rtype.id,
            'date_from': '2026-12-20', 'date_to': '2026-12-31',
            'rate_type': 'percent', 'adjustment_pct': 50.0,
            'priority': 10})
        data = self.env['hotel.rate.engine'].period_matrix(
            2026, [rtype.id], plan.id, board='RO')
        self.assertEqual(len(data['periods']), 12)
        dec = [c for c in data['rows'][0]['cells']
               if c['period_id'] == self.env.ref(
                   'hotel_management_odoo.hotel_rate_period_12').id][0]
        self.assertEqual(dec['min'], 10000.0)
        self.assertEqual(dec['max'], 15000.0)
