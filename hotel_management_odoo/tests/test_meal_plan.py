# -*- coding: utf-8 -*-
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestMealPlan(TransactionCase):
    def test_seed_five_plans_ordered_with_descriptions(self):
        plans = self.env['hotel.meal.plan'].search(
            [('active', '=', True)], order='sequence')
        self.assertEqual(plans.mapped('code'),
                         ['DP', 'RO', 'BB', 'HB', 'FB'])
        self.assertEqual(plans.mapped('name'),
                         ['Day Pass', 'Room Only', 'Bed & Breakfast',
                          'Half Board', 'Full Board'])
        for plan in plans:
            self.assertTrue(plan.description,
                            "Meal plan %s misses a description."
                            % plan.code)

    def test_duplicate_code_rejected(self):
        with self.assertRaises(ValidationError):
            self.env['hotel.meal.plan'].create({
                'code': 'BB', 'name': 'Bed & Breakfast Dupe',
                'description': 'Dupe.',
            })

    def test_new_room_type_gets_five_zero_lines(self):
        rtype = self.env['hotel.room.type'].create({
            'name': 'MealDeluxe', 'base_rate': 10000.0,
        })
        self.assertEqual(len(rtype.meal_price_ids), 5)
        self.assertEqual(
            sorted(rtype.meal_price_ids.mapped('meal_plan_id.code')),
            ['BB', 'DP', 'FB', 'HB', 'RO'])
        for line in rtype.meal_price_ids:
            self.assertEqual(line.price, 0.0)

    def test_meal_line_delete_blocked(self):
        rtype = self.env['hotel.room.type'].create({
            'name': 'MealNoDelete', 'base_rate': 8000.0,
        })
        with self.assertRaises(ValidationError):
            rtype.meal_price_ids[0].unlink()

    def test_negative_price_rejected(self):
        rtype = self.env['hotel.room.type'].create({
            'name': 'MealNoNeg', 'base_rate': 8000.0,
        })
        with self.assertRaises(ValidationError):
            rtype.meal_price_ids[0].write({'price': -1.0})

    def test_duplicate_type_plan_rejected(self):
        rtype = self.env['hotel.room.type'].create({
            'name': 'MealNoDupe', 'base_rate': 8000.0,
        })
        plan = rtype.meal_price_ids[0].meal_plan_id
        with self.assertRaises(ValidationError):
            self.env['hotel.room.type.meal.price'].create({
                'room_type_id': rtype.id,
                'meal_plan_id': plan.id,
                'price': 5000.0,
            })

    def test_all_types_fully_covered(self):
        plans = self.env['hotel.meal.plan'].search(
            [('active', '=', True)])
        for rtype in self.env['hotel.room.type'].search([]):
            self.assertEqual(
                sorted(rtype.meal_price_ids.mapped('meal_plan_id.code')),
                sorted(plans.mapped('code')),
                "Room type %s misses meal price lines."
                % rtype.display_name)

    def test_new_plan_backfills_existing_types(self):
        rtype = self.env['hotel.room.type'].create({
            'name': 'MealBackfill', 'base_rate': 8000.0,
        })
        plan = self.env['hotel.meal.plan'].create({
            'code': 'SP', 'name': 'Special',
            'description': 'Limited special.',
        })
        line = self.env['hotel.room.type.meal.price'].search([
            ('room_type_id', '=', rtype.id),
            ('meal_plan_id', '=', plan.id),
        ])
        self.assertEqual(len(line), 1)
        self.assertEqual(line.price, 0.0)
