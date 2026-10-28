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

    def _dec(self):
        return self.env['hotel.rate.period'].search(
            [('start_md', '=', '12-01')], limit=1)

    def test_matrix_returns_delta_and_closed(self):
        rtype, plan, room1, room2 = self._setup()
        self.env['hotel.rate.rule'].create({
            'plan_id': plan.id, 'room_type_id': rtype.id,
            'period_id': self._dec().id, 'period_year': 2026,
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
            'period_id': self._dec().id, 'period_year': 2026,
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
            'period_id': self._dec().id, 'period_year': 2026,
            'date_from': '2026-12-20', 'date_to': '2026-12-31',
            'rate_type': 'percent', 'adjustment_pct': 50.0,
            'priority': 10})
        data = self.env['hotel.rate.engine'].period_matrix(
            2026, [rtype.id], plan.id, board='RO')
        self.assertEqual(len(data['periods']), 12)
        dec = [c for c in data['rows'][0]['cells']
               if c['period_id'] == self.env.ref(
                   'hotel_management_odoo.hotel_rate_period_12').id][0]
        # Period-bound rule covers the whole December seed period
        # (dates derive from period), so min == max == uplifted.
        self.assertEqual(dec['min'], 15000.0)
        self.assertEqual(dec['max'], 15000.0)


class TestPeriodLineCalendar(TransactionCase):
    def setUp(self):
        super().setUp()
        self.plan = self.env['hotel.rate.plan'].search([], limit=1)
        self.dtype = self.env['hotel.room.type'].create({
            'name': 'CalT', 'base_rate': 10000.0})
        bb = self.env['hotel.meal.plan'].search(
            [('code', '=', 'BB')], limit=1)
        self.dtype.meal_price_ids.filtered(
            lambda l: l.meal_plan_id.id == bb.id).write(
                {'price': 12000.0})
        jan = self.env['hotel.rate.period'].search(
            [('start_md', '=', '01-01')], limit=1)
        jan_bb = jan.meal_line_ids.filtered(
            lambda l: l.meal_plan_id.id == bb.id)[:1]
        if not jan_bb:
            jan_bb = self.env['hotel.rate.period.meal.line'].create({
                'period_id': jan.id,
                'meal_plan_id': bb.id,
                'rate_type': 'percent',
                'value': 10.0,
            })
        else:
            jan_bb.write({'rate_type': 'percent', 'value': 10.0})
        self.rule = self.env['hotel.rate.rule'].create({
            'plan_id': self.plan.id,
            'room_type_id': self.dtype.id,
            'period_id': jan.id,
            'period_year': 2027,
            'rate_type': 'percent',
            'adjustment_pct': 20.0,
        })
        self.room = self.env['product.template'].create({
            'name': 'RM301', 'is_room': True, 'room_type': 'double',
            'num_person': 2, 'list_price': 10000.0,
            'room_type_id': self.dtype.id})
        self.engine = self.env['hotel.rate.engine']

    def test_matrix_total_uses_period_line(self):
        # RO proves the rule applied (12000 vs fallback 10000);
        # BB proves the period line applied (13200 vs fallback 12000).
        self.assertEqual(
            self.engine.price_for(
                self.room.id, '2027-01-15', self.plan.id,
                adults=2, board='RO'),
            12000.0)
        self.assertEqual(
            self.engine.price_for(
                self.room.id, '2027-01-15', self.plan.id,
                adults=2, board='BB'),
            13200.0)
        data = self.engine.matrix(
            [self.dtype.id], '2027-01-15', '2027-01-15',
            self.plan.id, board='BB')
        cell = data['rows'][0]['cells'][0]
        self.assertEqual(cell['total'], 13200.0)
        pdata = self.engine.period_matrix(
            2027, [self.dtype.id], self.plan.id, board='BB')
        jan_id = self.env['hotel.rate.period'].search(
            [('start_md', '=', '01-01')], limit=1).id
        jan_cell = [c for c in pdata['rows'][0]['cells']
                    if c['period_id'] == jan_id][0]
        self.assertEqual(jan_cell['min'], 13200.0)
        self.assertEqual(jan_cell['max'], 13200.0)
