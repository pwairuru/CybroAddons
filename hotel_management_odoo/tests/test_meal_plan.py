# -*- coding: utf-8 -*-
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestMealPlan(TransactionCase):
    def test_seed_five_plans_ordered_with_descriptions(self):
        plans = self.env['hotel.meal.plan'].with_context(
            active_test=False).search([], order='sequence')
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
        active_codes = sorted(
            self.env['hotel.meal.plan'].search(
                [('active', '=', True)]).mapped('code'))
        rtype = self.env['hotel.room.type'].create({
            'name': 'MealDeluxe', 'base_rate': 10000.0,
        })
        self.assertEqual(len(rtype.meal_price_ids), len(active_codes))
        self.assertEqual(
            sorted(rtype.meal_price_ids.mapped('meal_plan_id.code')),
            active_codes)
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
            self.assertTrue(
                set(plans.mapped('code')) <= set(
                    rtype.meal_price_ids.mapped('meal_plan_id.code')),
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

    def test_hidden_plan_excluded_from_website_but_usable_backend(self):
        plan = self.env['hotel.meal.plan'].search(
            [('code', '=', 'HB')], limit=1)
        self.assertTrue(plan, "Seed HB plan missing.")
        plan.write({'website_published': False})
        boards = self.env['hotel.public.booking'].allowed_boards()
        codes = [b['code'] for b in boards]
        self.assertNotIn('HB', codes)
        self.assertTrue(plan.active)

    def test_hidden_board_rejected_on_website_create(self):
        plan = self.env['hotel.meal.plan'].search(
            [('code', '=', 'HB')], limit=1)
        plan.write({'website_published': False})
        svc = self.env['hotel.public.booking']
        room = self.env['product.template'].search(
            [('is_room', '=', True), ('website_published', '=', True),
             ('active', '=', True)], limit=1)
        self.assertTrue(room, "Need one published room for gate.")
        with self.assertRaisesRegex(ValueError, 'bad board'):
            svc.create_booking({
                'room_id': room.id,
                'ci': '2026-12-10', 'co': '2026-12-12',
                'adults': 2, 'children': 0, 'board': 'HB',
                'name': 'Gate Guest', 'phone': '+254700000001',
            })

    def test_hidden_board_search_falls_back_to_visible(self):
        plan = self.env['hotel.meal.plan'].search(
            [('code', '=', 'FB')], limit=1)
        plan.write({'website_published': False})
        svc = self.env['hotel.public.booking']
        boards = svc.allowed_boards()
        self.assertNotIn('FB', [b['code'] for b in boards])
        # search_free must not price hidden board; falls back to default.
        rows = svc.search_free('2026-12-10', '2026-12-12',
                               adults=2, children=0, board='FB')
        self.assertIsInstance(rows, list)

    def test_new_plan_visible_on_website_by_default(self):
        plan = self.env['hotel.meal.plan'].create({
            'code': 'SP2', 'name': 'Special Two',
            'description': 'Gate default.',
        })
        self.assertTrue(plan.website_published)
        codes = [b['code']
                 for b in self.env['hotel.public.booking'].allowed_boards()]
        self.assertIn('SP2', codes)
