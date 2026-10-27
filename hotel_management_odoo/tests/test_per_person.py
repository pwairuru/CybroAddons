# -*- coding: utf-8 -*-
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
        # RO stays on the legacy base path (Ruling 4), so RO table
        # never prices; BB exercises the same per-room occupancy
        # path via the phase-1 table. Caps bumped to fit 2A+3C
        # (caps stay enforced in both modes).
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
