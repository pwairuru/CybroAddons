# -*- coding: utf-8 -*-
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestPerPerson(TransactionCase):
    def _setup(self, mode='per_person'):
        company = self.env.company
        dtype = self.env['hotel.room.type'].create({
            'name': 'PPDeluxe', 'base_rate': 10000.0,
            'adult_capacity': 2, 'max_occupants': 2,
            'charge_mode': mode, 'standard_heads': 2,
            'company_id': company.id,
        })
        dtype.meal_price_ids.filtered(
            lambda l: l.meal_plan_id.code == 'RO').write(
                {'price': 10000.0})
        plan = self.env['hotel.rate.plan'].create({
            'name': 'PPRack', 'company_id': company.id})
        room = self.env['product.template'].create({
            'name': 'PP101', 'is_room': True, 'room_type': 'double',
            'num_person': 2, 'list_price': 10000.0,
            'room_type_id': dtype.id})
        return dtype, plan, room

    def test_solo_pays_half(self):
        _dtype, plan, room = self._setup()
        price = self.env['hotel.rate.engine'].price_for(
            room.id, '2026-11-10', plan.id, adults=1, board='RO')
        self.assertEqual(price, 5000.0)

    def test_child_is_half_head(self):
        _dtype, plan, room = self._setup()
        price = self.env['hotel.rate.engine'].price_for(
            room.id, '2026-11-10', plan.id, adults=1, children=1,
            board='RO')
        self.assertEqual(price, 7500.0)

    def test_per_room_uses_occupancy_extra(self):
        # NOTE (Task 3): brief used board RO with RO table 20000, but
        # Ruling 4 pins RO to the legacy base path (RO has no meal
        # component; routing it through meal lines would change live
        # RO pricing), so the RO table never prices — BB is used here
        # to exercise the same per-room occupancy path via the
        # phase-1 table. Caps bumped to fit 2A+3C (caps stay enforced
        # in both modes).
        dtype, plan, room = self._setup(mode='per_room')
        dtype.meal_price_ids.filtered(
            lambda l: l.meal_plan_id.code == 'BB').write(
                {'price': 20000.0})
        dtype.write({'max_occupants': 5})
        room.write({'num_person': 5})
        self.env['hotel.rate.occupancy'].create({
            'room_type_id': dtype.id, 'band': 'child',
            'included_count': 2, 'mode': 'fixed', 'value': 1500.0,
            'basis': 'resolved_rate'})
        price = self.env['hotel.rate.engine'].price_for(
            room.id, '2026-11-10', plan.id, adults=2, children=3,
            board='BB')
        self.assertEqual(price, 21500.0)

    def test_meal_plan_basis_percent_of_resolved(self):
        dtype, plan, room = self._setup(mode='per_room')
        dtype.meal_price_ids.filtered(
            lambda l: l.meal_plan_id.code == 'BB').write(
                {'price': 20000.0})
        dtype.write({'max_occupants': 4})
        room.write({'num_person': 4})
        self.env['hotel.rate.occupancy'].create({
            'room_type_id': dtype.id, 'band': 'child',
            'included_count': 0, 'mode': 'percent', 'value': 10.0,
            'basis': 'meal_plan'})
        engine = self.env['hotel.rate.engine']
        detailed = engine.price_detailed(
            room.id, '2026-11-10', plan.id, adults=2, children=1,
            board='BB')
        child_lines = [l for l in detailed['lines']
                       if l['band'] == 'child']
        self.assertEqual(len(child_lines), 1)
        self.assertEqual(child_lines[0]['basis'], 'meal_plan')
        expected = round(detailed['resolved'] * 10.0 / 100.0, 2)
        self.assertEqual(child_lines[0]['total'], expected)
        self.assertEqual(detailed['net'],
                         detailed['resolved'] + expected)
        self.assertEqual(
            engine.price_for(
                room.id, '2026-11-10', plan.id, adults=2,
                children=1, board='BB'),
            detailed['net'])

    def test_per_person_skips_occupancy_extras(self):
        _dtype, plan, room = self._setup()
        self.env['hotel.rate.occupancy'].create({
            'room_type_id': _dtype.id, 'band': 'child',
            'included_count': 0, 'mode': 'fixed', 'value': 1500.0,
            'basis': 'resolved_rate'})
        engine = self.env['hotel.rate.engine']
        solo = engine.price_detailed(
            room.id, '2026-11-10', plan.id, adults=1, board='RO')
        self.assertEqual(solo['net'], 5000.0)
        self.assertEqual(solo['occupancy'], 0.0)
        self.assertEqual(len(solo['lines']), 1)
        family = engine.price_detailed(
            room.id, '2026-11-10', plan.id, adults=1, children=1,
            board='RO')
        self.assertEqual(family['net'], 7500.0)
        self.assertEqual(family['occupancy'], 0.0)
        self.assertEqual(len(family['lines']), 1)

    def test_toddler_kwarg_gone(self):
        _dtype, plan, room = self._setup()
        engine = self.env['hotel.rate.engine']
        self.assertFalse('toddlers' in engine.price_detailed.__code__.co_varnames)

    def test_caps_raise_in_both_modes(self):
        # Per-person: room fits but type max_occupants does not, so
        # the raise comes from the type guard.
        dtype_pp, plan_pp, room_pp = self._setup()
        room_pp.write({'num_person': 5})
        with self.assertRaises(ValidationError):
            self.env['hotel.rate.engine'].price_for(
                room_pp.id, '2026-11-10', plan_pp.id, adults=2,
                children=1, board='RO')
        # Per-room: room/type caps fit, band max_count does not, so
        # the raise comes from the band guard.
        dtype_pr, plan_pr, room_pr = self._setup(mode='per_room')
        dtype_pr.write({'max_occupants': 5})
        room_pr.write({'num_person': 5})
        self.env['hotel.rate.occupancy'].create({
            'room_type_id': dtype_pr.id, 'band': 'child',
            'included_count': 0, 'max_count': 1,
            'mode': 'fixed', 'value': 1500.0,
            'basis': 'resolved_rate'})
        with self.assertRaises(ValidationError):
            self.env['hotel.rate.engine'].price_for(
                room_pr.id, '2026-11-10', plan_pr.id, adults=1,
                children=2, board='RO')
