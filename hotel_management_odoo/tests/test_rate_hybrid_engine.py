# -*- coding: utf-8 -*-
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestHybridEngine(TransactionCase):
    def _setup(self, name='HybT', base_rate=20000.0):
        co = self.env.company
        rtype = self.env['hotel.room.type'].create({
            'name': name, 'base_rate': base_rate, 'max_occupants': 5})
        ro = self.env['hotel.meal.plan'].search(
            [('code', '=', 'RO')], limit=1)
        bb = self.env['hotel.meal.plan'].search(
            [('code', '=', 'BB')], limit=1)
        h1 = self.env['hotel.rate.period'].create({
            'name': 'HybH1-%s' % name, 'start_md': '01-01',
            'end_md': '06-30', 'company_id': co.id,
            'priority': 50, 'sequence': 5})
        room = self.env['product.template'].create({
            'name': 'HYB-%s' % name, 'is_room': True,
            'room_type': 'double', 'num_person': 5,
            'list_price': base_rate, 'room_type_id': rtype.id})
        return co, rtype, ro, bb, h1, room

    def test_meal_uplift(self):
        co, rtype, ro, bb, h1, room = self._setup('HybT')
        self.env['hotel.rate.line'].create({
            'company_id': co.id, 'period_id': h1.id,
            'room_type_id': rtype.id, 'meal_plan_id': ro.id,
            'price': 20000.0})
        self.env['hotel.rate.meal.supplement'].create({
            'room_type_id': rtype.id, 'meal_plan_id': bb.id,
            'active_uplift': True, 'mode': 'percent', 'value': 15.0})
        eng = self.env['hotel.rate.engine']
        self.assertEqual(
            eng.price_for(room.id, '2027-02-01', None, adults=2,
                          board='BB'), 23000.0)
        detailed = eng.price_detailed(
            room.id, '2027-02-01', None, adults=2, board='BB')
        self.assertEqual(detailed['basis'], 'meal-uplift')
        self.assertEqual(detailed['board'], 3000.0)

    def test_explicit_wins_over_uplift(self):
        co, rtype, ro, bb, h1, room = self._setup('HybE')
        self.env['hotel.rate.line'].create({
            'company_id': co.id, 'period_id': h1.id,
            'room_type_id': rtype.id, 'meal_plan_id': ro.id,
            'price': 20000.0})
        self.env['hotel.rate.meal.supplement'].create({
            'room_type_id': rtype.id, 'meal_plan_id': bb.id,
            'active_uplift': True, 'mode': 'percent', 'value': 15.0})
        self.env['hotel.rate.line'].create({
            'company_id': co.id, 'period_id': h1.id,
            'room_type_id': rtype.id, 'meal_plan_id': bb.id,
            'price': 25000.0})
        eng = self.env['hotel.rate.engine']
        self.assertEqual(
            eng.price_for(room.id, '2027-02-01', None, adults=2,
                          board='BB'), 25000.0)
        detailed = eng.price_detailed(
            room.id, '2027-02-01', None, adults=2, board='BB')
        self.assertEqual(detailed['basis'], 'explicit')

    def test_strict_still_raises(self):
        co, rtype, ro, bb, h1, room = self._setup('HybS')
        eng = self.env['hotel.rate.engine']
        with self.assertRaises(ValidationError):
            eng.price_for(room.id, '2027-02-01', None, adults=2,
                          board='BB')

    def test_uplift_fixed(self):
        co, rtype, ro, bb, h1, room = self._setup('HybF')
        self.env['hotel.rate.line'].create({
            'company_id': co.id, 'period_id': h1.id,
            'room_type_id': rtype.id, 'meal_plan_id': ro.id,
            'price': 20000.0})
        self.env['hotel.rate.meal.supplement'].create({
            'room_type_id': rtype.id, 'meal_plan_id': bb.id,
            'active_uplift': True, 'mode': 'fixed', 'value': 3000.0})
        eng = self.env['hotel.rate.engine']
        self.assertEqual(
            eng.price_for(room.id, '2027-02-01', None, adults=2,
                          board='BB'), 23000.0)

    def test_uplift_inactive_ignored(self):
        co, rtype, ro, bb, h1, room = self._setup('HybI')
        self.env['hotel.rate.line'].create({
            'company_id': co.id, 'period_id': h1.id,
            'room_type_id': rtype.id, 'meal_plan_id': ro.id,
            'price': 20000.0})
        self.env['hotel.rate.meal.supplement'].create({
            'room_type_id': rtype.id, 'meal_plan_id': bb.id,
            'active_uplift': False, 'mode': 'percent', 'value': 15.0})
        eng = self.env['hotel.rate.engine']
        with self.assertRaises(ValidationError):
            eng.price_for(room.id, '2027-02-01', None, adults=2,
                          board='BB')

    def test_period_fallback_basis(self):
        co, rtype, ro, bb, h1, room = self._setup('HybP')
        promo = self.env['hotel.rate.period'].create({
            'name': 'HybPromo', 'start_md': '04-18', 'end_md': '04-21',
            'sequence': 5, 'priority': 100, 'company_id': co.id,
            'applies_year': 2027})
        self.env['hotel.rate.line'].create({
            'company_id': co.id, 'period_id': h1.id,
            'room_type_id': rtype.id, 'meal_plan_id': bb.id,
            'price': 20000.0})
        eng = self.env['hotel.rate.engine']
        detailed = eng.price_detailed(
            room.id, '2027-04-19', None, adults=2, board='BB')
        self.assertEqual(detailed['net'], 20000.0)
        self.assertEqual(detailed['basis'], 'period-fallback')

    def test_plan_adjustment_percent(self):
        co, rtype, ro, bb, h1, room = self._setup('HybA')
        plan = self.env['hotel.rate.plan'].create({
            'name': 'Corp', 'code': 'CORP', 'company_id': co.id})
        self.env['hotel.rate.line'].create({
            'company_id': co.id, 'period_id': h1.id,
            'room_type_id': rtype.id, 'meal_plan_id': ro.id,
            'price': 20000.0})
        self.env['hotel.rate.plan.adjustment'].create({
            'plan_id': plan.id, 'mode': 'percent', 'value': -10.0})
        eng = self.env['hotel.rate.engine']
        detailed = eng.price_detailed(
            room.id, '2027-02-01', plan.id, adults=2, board='RO')
        self.assertEqual(detailed['net'], 18000.0)
        self.assertEqual(detailed['adjustment'], -2000.0)
        self.assertEqual(detailed['fallback_reason'], 'plan-adjustment')

    def test_plan_override_line_wins(self):
        co, rtype, ro, bb, h1, room = self._setup('HybO')
        plan = self.env['hotel.rate.plan'].create({
            'name': 'OTA', 'code': 'OTA', 'company_id': co.id})
        self.env['hotel.rate.line'].create({
            'company_id': co.id, 'period_id': h1.id,
            'room_type_id': rtype.id, 'meal_plan_id': ro.id,
            'price': 20000.0})
        self.env['hotel.rate.line'].create({
            'company_id': co.id, 'period_id': h1.id,
            'room_type_id': rtype.id, 'meal_plan_id': ro.id,
            'plan_id': plan.id, 'price': 15000.0})
        self.env['hotel.rate.plan.adjustment'].create({
            'plan_id': plan.id, 'mode': 'percent', 'value': -10.0})
        eng = self.env['hotel.rate.engine']
        detailed = eng.price_detailed(
            room.id, '2027-02-01', plan.id, adults=2, board='RO')
        self.assertEqual(detailed['net'], 15000.0)
        self.assertEqual(detailed['adjustment'], 0.0)
        self.assertEqual(detailed['fallback_reason'], 'explicit')

    def test_adjustment_specificity(self):
        co, rtype, ro, bb, h1, room = self._setup('HybG')
        plan = self.env['hotel.rate.plan'].create({
            'name': 'Spec', 'code': 'SPEC', 'company_id': co.id})
        self.env['hotel.rate.line'].create({
            'company_id': co.id, 'period_id': h1.id,
            'room_type_id': rtype.id, 'meal_plan_id': ro.id,
            'price': 20000.0})
        self.env['hotel.rate.plan.adjustment'].create({
            'plan_id': plan.id, 'mode': 'percent', 'value': -10.0})
        self.env['hotel.rate.plan.adjustment'].create({
            'plan_id': plan.id, 'room_type_id': rtype.id,
            'period_id': h1.id, 'mode': 'percent', 'value': -25.0})
        eng = self.env['hotel.rate.engine']
        detailed = eng.price_detailed(
            room.id, '2027-02-01', plan.id, adults=2, board='RO')
        self.assertEqual(detailed['net'], 15000.0)

    def test_cross_company_adjustment_ignored(self):
        co, rtype, ro, bb, h1, room = self._setup('HybX')
        plan = self.env['hotel.rate.plan'].create({
            'name': 'XCorp', 'code': 'XC', 'company_id': co.id})
        self.env['hotel.rate.line'].create({
            'company_id': co.id, 'period_id': h1.id,
            'room_type_id': rtype.id, 'meal_plan_id': ro.id,
            'price': 20000.0})
        other = self.env['res.company'].create({'name': 'Other Hyb Co'})
        other_type = self.env['hotel.room.type'].create({
            'name': 'HybX-o', 'base_rate': 10000.0,
            'company_id': other.id})
        other_period = self.env['hotel.rate.period'].create({
            'name': 'HybH1-o', 'start_md': '01-01', 'end_md': '06-30',
            'company_id': other.id})
        self.env['hotel.rate.plan.adjustment'].create({
            'plan_id': plan.id, 'room_type_id': other_type.id,
            'mode': 'percent', 'value': -50.0})
        self.env['hotel.rate.plan.adjustment'].create({
            'plan_id': plan.id, 'period_id': other_period.id,
            'mode': 'percent', 'value': -50.0})
        eng = self.env['hotel.rate.engine']
        detailed = eng.price_detailed(
            room.id, '2027-02-01', plan.id, adults=2, board='RO')
        self.assertEqual(detailed['net'], 20000.0)
        self.assertEqual(detailed['fallback_reason'], 'explicit')

    def test_fallback_mode_base_rate(self):
        co, rtype, ro, bb, h1, room = self._setup('HybB', 20000.0)
        co.write({'rate_missing_mode': 'fallback'})
        eng = self.env['hotel.rate.engine']
        detailed = eng.price_detailed(
            room.id, '2027-02-01', None, adults=2, board='BB')
        self.assertEqual(detailed['net'], 20000.0)
        self.assertEqual(detailed['basis'], 'base-rate')
        self.assertEqual(detailed['fallback_reason'], 'base-rate')

    def test_warn_posts_chatter(self):
        co, rtype, ro, bb, h1, room = self._setup('HybW', 20000.0)
        co.write({'rate_missing_mode': 'warn'})
        plan = self.env['hotel.rate.plan'].create({
            'name': 'WarnRack', 'company_id': co.id})
        folio = self.env['hotel.folio'].create({
            'partner_id': co.partner_id.id,
            'company_id': co.id,
        })
        eng = self.env['hotel.rate.engine']
        eng.post_stay_nights(
            folio.id, room.id, '2027-02-01', '2027-02-02', plan.id,
            adults=2)
        snaps = self.env['hotel.rate.snapshot'].search([
            ('folio_id', '=', folio.id)])
        self.assertTrue(snaps)
        self.assertTrue(all(s.override for s in snaps))
        self.assertTrue(
            all(s.fallback_reason == 'base-rate' for s in snaps))
        self.assertTrue(
            any('Rate fallback used (base-rate)' in str(b)
                for b in folio.message_ids.mapped('body')))

    def test_matrix_basis_passthrough(self):
        co, rtype, ro, bb, h1, room = self._setup('HybM')
        plan = self.env['hotel.rate.plan'].create({
            'name': 'MtrxRack', 'company_id': co.id})
        self.env['hotel.rate.line'].create({
            'company_id': co.id, 'period_id': h1.id,
            'room_type_id': rtype.id, 'meal_plan_id': ro.id,
            'price': 20000.0})
        eng = self.env['hotel.rate.engine']
        data = eng.matrix(
            [rtype.id], '2027-02-01', '2027-02-02', plan.id,
            board='RO')
        cell = data['rows'][0]['cells'][0]
        self.assertEqual(cell['basis'], 'explicit')
        self.assertEqual(cell['fallback_reason'], 'explicit')
        self.assertEqual(cell['price'], 20000.0)
