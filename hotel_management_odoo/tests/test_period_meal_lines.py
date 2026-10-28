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

    def test_sql_unique_constraint_declared(self):
        keys = [key for key, _sql, _msg in self.env[
            'hotel.rate.period.meal.line']._sql_constraints]
        self.assertIn('unique_period_plan', keys)


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


class TestPeriodBoundRules(TransactionCase):
    def _period(self):
        return self.env['hotel.rate.period'].search(
            [('start_md', '=', '01-01')], limit=1)

    def _plan(self):
        return self.env['hotel.rate.plan'].search([], limit=1)

    def test_period_required(self):
        with self.assertRaises(Exception):
            self.env['hotel.rate.rule'].create({
                'plan_id': self._plan().id,
                'period_id': False,
                'rate_type': 'percent',
                'adjustment_pct': 10.0,
            })

    def test_dates_derived_from_period(self):
        rule = self.env['hotel.rate.rule'].create({
            'plan_id': self._plan().id,
            'period_id': self._period().id,
            'period_year': 2027,
            'rate_type': 'percent',
            'adjustment_pct': 10.0,
        })
        self.assertEqual(str(rule.date_from), '2027-01-01')
        self.assertEqual(str(rule.date_to), '2027-01-31')

    def test_year_must_match_applies_year(self):
        promo = self.env['hotel.rate.period'].create({
            'name': 'Xmas', 'start_md': '12-24', 'end_md': '12-31',
            'applies_year': 2026, 'sequence': 100})
        with self.assertRaises(ValidationError):
            self.env['hotel.rate.rule'].create({
                'plan_id': self._plan().id,
                'period_id': promo.id,
                'period_year': 2027,
                'rate_type': 'percent',
            })

    def test_weekday_mask_defaults_all_true(self):
        rule = self.env['hotel.rate.rule'].create({
            'plan_id': self._plan().id,
            'period_id': self._period().id,
            'period_year': 2027,
            'rate_type': 'percent',
        })
        for day in ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'):
            self.assertTrue(rule[day])


class TestPeriodBoardEngine(TransactionCase):
    def setUp(self):
        super().setUp()
        self.plan = self.env['hotel.rate.plan'].search([], limit=1)
        self.dtype = self.env['hotel.room.type'].create({
            'name': 'EngT', 'base_rate': 10000.0})
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
            # Seed periods predate period lines (backfilled in Task 6),
            # so ensure the BB line exists instead of assuming it.
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
            'adjustment_pct': 0.0,
        })
        self.room = self.env['product.template'].create({
            'name': 'RM201', 'is_room': True, 'room_type': 'double',
            'num_person': 2, 'list_price': 10000.0,
            'room_type_id': self.dtype.id})
        self.engine = self.env['hotel.rate.engine']

    def test_board_uplift_comes_from_period(self):
        self.assertEqual(
            self.engine.price_for(
                self.room.id, '2027-01-15', self.plan.id,
                adults=2, board='BB'),
            13200.0)

    def test_ro_ignores_period_lines(self):
        jan_bb = self.env['hotel.rate.period.meal.line'].search([
            ('period_id', '=', self.rule.period_id.id),
            ('meal_plan_id.code', '=', 'BB')], limit=1)
        jan_bb.write({'rate_type': 'fixed', 'value': 99999.0})
        self.assertEqual(
            self.engine.price_for(
                self.room.id, '2027-01-15', self.plan.id,
                adults=2, board='RO'),
            10000.0)

    def test_weekday_mask_skips_rule(self):
        self.rule.write({'sat': False, 'sun': False})
        # 2027-01-16 is a Saturday: no rule -> base fallback.
        self.assertEqual(
            self.engine.price_for(
                self.room.id, '2027-01-16', self.plan.id,
                adults=2, board='RO'),
            10000.0)
        self.assertEqual(
            self.engine.price_for(
                self.room.id, '2027-01-18', self.plan.id,
                adults=2, board='RO'),
            10000.0)

    def test_narrower_higher_priority_wins(self):
        promo = self.env['hotel.rate.period'].create({
            'name': 'JanPromo', 'start_md': '01-10',
            'end_md': '01-20', 'sequence': 100})
        self.env['hotel.rate.rule'].create({
            'plan_id': self.plan.id,
            'room_type_id': self.dtype.id,
            'period_id': promo.id,
            'period_year': 2027,
            'rate_type': 'percent',
            'adjustment_pct': 50.0,
            'priority': 60,
        })
        self.assertEqual(
            self.engine.price_for(
                self.room.id, '2027-01-15', self.plan.id,
                adults=2, board='RO'),
            15000.0)
        self.assertEqual(
            self.engine.price_for(
                self.room.id, '2027-01-05', self.plan.id,
                adults=2, board='RO'),
            10000.0)


class TestWeekdayOverlapGuard(TransactionCase):
    def setUp(self):
        super().setUp()
        self.plan = self.env['hotel.rate.plan'].search([], limit=1)
        self.dtype = self.env['hotel.room.type'].create({
            'name': 'WkGuardT', 'base_rate': 10000.0})
        self.period = self.env['hotel.rate.period'].search(
            [('start_md', '=', '01-01')], limit=1)

    def _rule_vals(self, adjustment, weekdays):
        vals = {
            'plan_id': self.plan.id,
            'room_type_id': self.dtype.id,
            'period_id': self.period.id,
            'period_year': 2027,
            'rate_type': 'percent',
            'adjustment_pct': adjustment,
            'priority': 10,
        }
        vals.update(weekdays)
        return vals

    def test_complementary_masks_allow_different_rates(self):
        weekday = self._rule_vals(10.0, {
            'mon': True, 'tue': True, 'wed': True, 'thu': True,
            'fri': True, 'sat': False, 'sun': False})
        weekend = self._rule_vals(20.0, {
            'mon': False, 'tue': False, 'wed': False,
            'thu': False, 'fri': False,
            'sat': True, 'sun': True})
        rule1 = self.env['hotel.rate.rule'].create(weekday)
        rule2 = self.env['hotel.rate.rule'].create(weekend)
        self.assertTrue(rule1.id and rule2.id)
        with self.assertRaises(ValidationError):
            rule2.write({'mon': True})
        with self.assertRaises(ValidationError):
            self.env['hotel.rate.rule'].create(
                self._rule_vals(30.0, {}))


class TestWeekdayMinStay(TransactionCase):
    def setUp(self):
        super().setUp()
        self.plan = self.env['hotel.rate.plan'].create({
            'name': 'WkMinPlan'})
        self.dtype = self.env['hotel.room.type'].create({
            'name': 'WkMinT', 'base_rate': 10000.0})
        self.period = self.env['hotel.rate.period'].search(
            [('start_md', '=', '01-01')], limit=1)
        self.env['hotel.rate.rule'].create({
            'plan_id': self.plan.id,
            'room_type_id': self.dtype.id,
            'period_id': self.period.id,
            'period_year': 2027,
            'rate_type': 'percent',
            'adjustment_pct': 0.0,
            'min_stay': 5,
            'mon': False, 'tue': False, 'wed': False,
            'thu': False, 'fri': False,
            'sat': True, 'sun': True,
        })
        self.room = self.env['product.template'].create({
            'name': 'RMWK1', 'is_room': True, 'room_type': 'double',
            'num_person': 2, 'list_price': 10000.0,
            'room_type_id': self.dtype.id})
        self.engine = self.env['hotel.rate.engine']

    def test_matrix_min_stay_ignores_weekday_mismatch(self):
        monday = self.engine.matrix(
            [self.dtype.id], '2027-01-18', '2027-01-18',
            self.plan.id)
        self.assertEqual(
            monday['rows'][0]['cells'][0]['min_stay'], 1)
        saturday = self.engine.matrix(
            [self.dtype.id], '2027-01-16', '2027-01-16',
            self.plan.id)
        self.assertEqual(
            saturday['rows'][0]['cells'][0]['min_stay'], 5)

    def test_check_stay_allows_weekday_stay(self):
        nights = self.engine.check_stay(
            self.room.id, '2027-01-18', '2027-01-22',
            self.plan.id)
        self.assertEqual(nights, 4)
