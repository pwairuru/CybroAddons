# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestOccupancyBoard(TransactionCase):
    def setUp(self):
        super().setUp()
        self.company = self.env.company
        self.dtype = self.env['hotel.room.type'].create({
            'name': 'Deluxe',
            'base_rate': 10000.0,
            'adult_capacity': 2,
            'child_capacity': 1,
            'max_occupants': 3,
        })
        self.plan = self.env['hotel.rate.plan'].create({
            'name': 'Rack',
            'company_id': self.company.id,
        })
        self.env['hotel.rate.rule'].create({
            'plan_id': self.plan.id,
            'room_type_id': self.dtype.id,
            'rate_type': 'percent',
            'adjustment_pct': 30.0,
            'priority': 50,
            'date_from': '2026-12-20',
            'date_to': '2026-12-31',
        })
        self.room = self.env['product.template'].create({
            'name': '101', 'is_room': True, 'room_type': 'double',
            'num_person': 3, 'list_price': 10000.0,
            'room_type_id': self.dtype.id,
        })
        self.env['hotel.rate.occupancy'].create({
            'room_type_id': self.dtype.id,
            'plan_id': self.plan.id,
            'band': 'child',
            'included_count': 0,
            'max_count': 2,
            'mode': 'percent',
            'value': 50.0,
            'basis': 'resolved_rate',
        })
        self.engine = self.env['hotel.rate.engine']

    def test_child_percent_of_resolved_rate(self):
        # Deluxe base 10000, Dec +30% => resolved 13000,
        # child 50% => 6500. Net for 2 adults + 1 child = 19500.
        price = self.engine.price_for(
            self.room.id, '2026-12-24', self.plan.id,
            adults=2, children=1)
        self.assertIsInstance(price, float)
        self.assertEqual(price, 19500.0)
        breakdown = self.engine.price_detailed(
            self.room.id, '2026-12-24', self.plan.id,
            adults=2, children=1)
        self.assertEqual(breakdown['net'], 19500.0)
        self.assertEqual(breakdown['lines'][1]['basis'], 'resolved_rate')

    def test_price_for_keeps_float_return(self):
        price = self.engine.price_for(
            self.room.id, '2026-12-24', self.plan.id,
            adults=2, children=1)
        self.assertIsInstance(price, float)

    def test_child_percent_of_bar_uses_type_rate(self):
        occ = self.env['hotel.rate.occupancy'].search([
            ('room_type_id', '=', self.dtype.id),
            ('band', '=', 'child'),
        ])
        occ.write({'basis': 'bar'})
        breakdown = self.engine.price_detailed(
            self.room.id, '2026-12-24', self.plan.id,
            adults=2, children=1)
        # 50% of type BAR 10000 = 5000; net = 13000 + 5000.
        self.assertEqual(breakdown['net'], 18000.0)

    def test_board_qty_is_nights_x_pax(self):
        meal_product = self.env['product.product'].create({
            'name': 'Meal Supplement', 'type': 'service',
            'list_price': 3500.0,
        })
        folio = self.env['hotel.folio'].create({
            'partner_id': self.company.partner_id.id,
        })
        room2 = self.env['product.template'].create({
            'name': '102', 'is_room': True, 'room_type': 'double',
            'num_person': 2, 'list_price': 10000.0,
            'room_type_id': self.dtype.id,
        })
        now = fields.Datetime.now()
        booking = self.env['room.booking'].create({
            'partner_id': self.company.partner_id.id,
            'meal_plan': 'HB',
        })
        self.env['room.booking.line'].create({
            'booking_id': booking.id,
            'room_id': room2.id,
            'checkin_date': now,
            'checkout_date': now + timedelta(days=2),
        })
        lines = booking.post_meal_supplement(
            folio.id, meal_product.id, nights=2)
        self.assertTrue(lines)
        self.assertEqual(sum(lines.mapped('quantity')), 4.0)
        for line in lines:
            self.assertTrue(line.hotel_date)
            self.assertTrue(line.room_template_id)

    def test_check_stay_min_stay_respects_type(self):
        stype = self.env['hotel.room.type'].create({
            'name': 'Standard', 'base_rate': 8000.0,
            'adult_capacity': 2, 'child_capacity': 0,
            'max_occupants': 2,
        })
        sroom = self.env['product.template'].create({
            'name': '103', 'is_room': True, 'room_type': 'double',
            'num_person': 2, 'list_price': 8000.0,
            'room_type_id': stype.id,
        })
        self.env['hotel.rate.rule'].create({
            'plan_id': self.plan.id,
            'room_type_id': self.dtype.id,
            'rate_type': 'percent',
            'adjustment_pct': 0.0,
            'priority': 10,
            'date_from': '2026-11-10',
            'date_to': '2026-11-12',
            'min_stay': 3,
        })
        # Standard room unaffected by Deluxe min-stay: 1 night passes.
        nights = self.engine.check_stay(
            sroom.id, '2026-11-10', '2026-11-11', self.plan.id)
        self.assertEqual(nights, 1)
        # Deluxe room hit by its own min-stay: 1 night raises.
        with self.assertRaises(ValidationError):
            self.engine.check_stay(
                self.room.id, '2026-11-10', '2026-11-11', self.plan.id)

    def test_stay_snapshots_written_per_night(self):
        folio = self.env['hotel.folio'].create({
            'partner_id': self.company.partner_id.id,
        })
        lines = self.engine.post_stay_nights(
            folio.id, self.room.id,
            '2026-12-24', '2026-12-26', self.plan.id,
            adults=1, children=0)
        self.assertEqual(len(lines), 2)
        snaps = self.env['hotel.rate.snapshot'].search([
            ('folio_id', '=', folio.id),
            ('room_template_id', '=', self.room.id),
        ])
        self.assertEqual(len(snaps), 2)
        for snap in snaps:
            self.assertTrue(snap.hotel_date)
            self.assertEqual(snap.base, 10000.0)
            self.assertEqual(snap.net, 13000.0)
            self.assertTrue(snap.source_rule_id)
            self.assertFalse(snap.override)

    def test_snapshot_immutable_after_rule_change(self):
        folio = self.env['hotel.folio'].create({
            'partner_id': self.company.partner_id.id,
        })
        lines = self.engine.post_stay_nights(
            folio.id, self.room.id,
            '2026-12-24', '2026-12-26', self.plan.id,
            adults=1, children=0)
        first_price = lines[0].price_unit
        first_ids = set(lines.ids)
        snaps_before = {
            s.hotel_date.isoformat(): s.net
            for s in self.env['hotel.rate.snapshot'].search([
                ('folio_id', '=', folio.id),
                ('room_template_id', '=', self.room.id),
            ])
        }
        rule = self.env['hotel.rate.rule'].search([
            ('plan_id', '=', self.plan.id),
            ('room_type_id', '=', self.dtype.id),
        ], limit=1)
        rule.write({'adjustment_pct': 99.0})
        # Live pricing moved but the posted line keeps its stored price.
        live = self.engine.price_for(
            self.room.id, '2026-12-24', self.plan.id,
            adults=1, children=0)
        self.assertNotEqual(live, first_price)
        self.assertEqual(lines[0].price_unit, first_price)
        # Repost dedups to the same lines; snapshots never rewritten.
        relines = self.engine.post_stay_nights(
            folio.id, self.room.id,
            '2026-12-24', '2026-12-26', self.plan.id,
            adults=1, children=0)
        self.assertEqual(set(relines.ids), first_ids)
        self.assertEqual(relines[0].price_unit, first_price)
        snaps_after = {
            s.hotel_date.isoformat(): s.net
            for s in self.env['hotel.rate.snapshot'].search([
                ('folio_id', '=', folio.id),
                ('room_template_id', '=', self.room.id),
            ])
        }
        self.assertEqual(snaps_after, snaps_before)
        self.assertEqual(len(snaps_after), 2)

    def test_plan_specific_occupancy_beats_type_default(self):
        self.env['hotel.rate.occupancy'].create({
            'room_type_id': self.dtype.id,
            'plan_id': False,
            'band': 'child',
            'included_count': 0,
            'max_count': 2,
            'mode': 'percent',
            'value': 10.0,
            'basis': 'resolved_rate',
        })
        # Plan-specific 50% wins over the 10% type default.
        breakdown = self.engine.price_detailed(
            self.room.id, '2026-12-24', self.plan.id,
            adults=2, children=1)
        self.assertEqual(breakdown['net'], 19500.0)
        # A plan with no specific record falls back to the default:
        # no rule => resolved 10000, child 10% => 1000, net 11000.
        other_plan = self.env['hotel.rate.plan'].create({
            'name': 'Other Plan',
            'company_id': self.company.id,
        })
        fallback = self.engine.price_detailed(
            self.room.id, '2026-12-24', other_plan.id,
            adults=2, children=1)
        self.assertEqual(fallback['net'], 11000.0)

    def test_ro_meal_supplement_returns_false_without_rule(self):
        meal_product = self.env['product.product'].create({
            'name': 'Meal Supplement RO', 'type': 'service',
            'list_price': 3500.0,
        })
        folio = self.env['hotel.folio'].create({
            'partner_id': self.company.partner_id.id,
        })
        now = fields.Datetime.now()
        booking = self.env['room.booking'].create({
            'partner_id': self.company.partner_id.id,
            'meal_plan': 'RO',
        })
        self.env['room.booking.line'].create({
            'booking_id': booking.id,
            'room_id': self.room.id,
            'checkin_date': now,
            'checkout_date': now + timedelta(days=2),
        })
        result = booking.post_meal_supplement(
            folio.id, meal_product.id, nights=2)
        self.assertFalse(result)
        self.assertEqual(self.env['hotel.folio.line'].search_count([
            ('folio_id', '=', folio.id)]), 0)


class TestOccupancyItemizedData(TransactionCase):
    def test_per_unit_capacity_validation(self):
        dtype = self.env['hotel.room.type'].create({
            'name': 'DataType', 'base_rate': 5000.0})
        from odoo.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            self.env['hotel.rate.occupancy'].create({
                'room_type_id': dtype.id, 'band': 'adult',
                'mode': 'fixed', 'value': 1000.0, 'basis': 'board',
                'per': 'per_unit', 'unit_capacity': 0,
            })


class TestOccupancyItemizedEngine(TransactionCase):
    def setUp(self):
        super().setUp()
        self.company = self.env.company
        self.dtype = self.env['hotel.room.type'].create({
            'name': 'EngDeluxe', 'base_rate': 10000.0,
            'max_occupants': 8,
        })
        self.plan = self.env['hotel.rate.plan'].create({
            'name': 'EngRack', 'company_id': self.company.id})
        self.env['hotel.rate.rule'].create({
            'plan_id': self.plan.id, 'room_type_id': self.dtype.id,
            'rate_type': 'percent', 'adjustment_pct': 30.0,
            'priority': 50, 'date_from': '2026-12-20',
            'date_to': '2026-12-31'})
        self.room = self.env['product.template'].create({
            'name': 'ENG101', 'is_room': True, 'room_type': 'double',
            'num_person': 8, 'list_price': 10000.0,
            'room_type_id': self.dtype.id})
        self.env['hotel.board.rule'].create({
            'company_id': self.company.id, 'room_type_id': self.dtype.id,
            'plan_id': self.plan.id, 'board': 'BB',
            'date_from': '2026-12-20', 'date_to': '2026-12-31',
            'supplement': 3500.0})
        self.env['hotel.rate.occupancy'].create({
            'room_type_id': self.dtype.id, 'plan_id': self.plan.id,
            'band': 'child', 'included_count': 0, 'mode': 'percent',
            'value': 50.0, 'basis': 'board'})
        self.engine = self.env['hotel.rate.engine']

    def test_board_percent_uses_nightly_supplement(self):
        # resolved 13000; child 50% of BB 3500 = 1750; net 14750.
        breakdown = self.engine.price_detailed(
            self.room.id, '2026-12-24', self.plan.id,
            adults=2, children=1, board='BB')
        self.assertEqual(breakdown['net'], 14750.0)
        line = breakdown['lines'][1]
        self.assertEqual(line['band'], 'child')
        self.assertEqual(line['qty'], 1)
        self.assertEqual(line['supplement'], 3500.0)
        self.assertFalse(line['reason'])

    def test_ro_board_basis_zero_with_reason(self):
        breakdown = self.engine.price_detailed(
            self.room.id, '2026-12-24', self.plan.id,
            adults=2, children=1, board='RO')
        self.assertEqual(breakdown['net'], 13000.0)
        line = breakdown['lines'][1]
        self.assertEqual(line['total'], 0.0)
        self.assertEqual(line['reason'], 'no-board-price')

    def test_per_unit_steps_with_capacity(self):
        self.env['hotel.rate.occupancy'].create({
            'room_type_id': self.dtype.id, 'plan_id': self.plan.id,
            'band': 'adult', 'included_count': 0, 'mode': 'fixed',
            'value': 2000.0, 'basis': 'resolved_rate',
            'per': 'per_unit', 'unit_capacity': 4})
        breakdown = self.engine.price_detailed(
            self.room.id, '2026-12-24', self.plan.id,
            adults=5, children=0, board='RO')
        line = [l for l in breakdown['lines'] if l['band'] == 'adult'][0]
        self.assertEqual(line['qty'], 2)
        self.assertEqual(line['total'], 4000.0)


class TestOccupancyItemizedPosting(TransactionCase):
    def setUp(self):
        super().setUp()
        self.company = self.env.company
        self.dtype = self.env['hotel.room.type'].create({
            'name': 'ItemDeluxe', 'base_rate': 10000.0,
            'max_occupants': 8,
        })
        self.plan = self.env['hotel.rate.plan'].create({
            'name': 'ItemRack', 'company_id': self.company.id})
        self.env['hotel.rate.rule'].create({
            'plan_id': self.plan.id, 'room_type_id': self.dtype.id,
            'rate_type': 'percent', 'adjustment_pct': 30.0,
            'priority': 50, 'date_from': '2026-12-20',
            'date_to': '2026-12-31'})
        self.room = self.env['product.template'].create({
            'name': 'ITEM101', 'is_room': True, 'room_type': 'double',
            'num_person': 8, 'list_price': 10000.0,
            'room_type_id': self.dtype.id})
        self.env['hotel.board.rule'].create({
            'company_id': self.company.id, 'room_type_id': self.dtype.id,
            'plan_id': self.plan.id, 'board': 'BB',
            'date_from': '2026-12-20', 'date_to': '2026-12-31',
            'supplement': 3500.0})
        self.extra_product = self.env['product.product'].create({
            'name': 'Extra Child', 'type': 'service',
            'list_price': 1750.0,
        })
        self.env['hotel.rate.occupancy'].create({
            'room_type_id': self.dtype.id, 'plan_id': self.plan.id,
            'band': 'child', 'included_count': 0, 'mode': 'percent',
            'value': 50.0, 'basis': 'board',
            'service_product_id': self.extra_product.id})
        self.engine = self.env['hotel.rate.engine']

    def _folio_for_board(self, board):
        booking = self.env['room.booking'].create({
            'partner_id': self.company.partner_id.id,
            'meal_plan': board,
        })
        return self.env['hotel.folio'].create({
            'partner_id': self.company.partner_id.id,
            'booking_id': booking.id,
        })

    def test_band_lines_posted_separately_with_product_taxes(self):
        # 2 nights BB, 2 adults + 1 child: per night room 13000 +
        # child 1750. Folio = 2 base + 2 band lines; total 29500.
        folio = self._folio_for_board('BB')
        lines = self.engine.post_stay_nights(
            folio.id, self.room.id,
            '2026-12-24', '2026-12-26', self.plan.id,
            adults=2, children=1)
        self.assertEqual(len(lines), 4)
        band = lines.filtered(
            lambda l: l.product_id == self.extra_product)
        self.assertEqual(len(band), 2)
        self.assertEqual(sum(band.mapped('price_total')), 3500.0)
        base = lines - band
        self.assertEqual(sum(base.mapped('price_total')), 26000.0)
        self.assertEqual(sum(lines.mapped('price_total')), 29500.0)
        for line in band:
            self.assertEqual(
                set(line.tax_ids.ids),
                set(self.extra_product.taxes_id.ids))
        snaps = self.env['hotel.rate.snapshot'].search([
            ('folio_id', '=', folio.id),
            ('room_template_id', '=', self.room.id),
        ])
        self.assertEqual(len(snaps), 4)
        for line in base:
            snap = snaps.filtered(
                lambda s: s.folio_line_id.id == line.id)
            self.assertEqual(len(snap), 1)
            self.assertEqual(snap.occupancy, 0.0)
            self.assertEqual(snap.net, 13000.0)
        for line in band:
            snap = snaps.filtered(
                lambda s: s.folio_line_id.id == line.id)
            self.assertEqual(len(snap), 1)
            self.assertEqual(snap.occupancy, 1750.0)
            self.assertEqual(snap.net, 1750.0)

    def test_repost_dedups_band_lines(self):
        folio = self._folio_for_board('BB')
        lines = self.engine.post_stay_nights(
            folio.id, self.room.id,
            '2026-12-24', '2026-12-26', self.plan.id,
            adults=2, children=1)
        first_ids = set(lines.ids)
        self.assertEqual(len(first_ids), 4)
        before = {
            s.folio_line_id.id: (s.net, s.occupancy)
            for s in self.env['hotel.rate.snapshot'].search([
                ('folio_id', '=', folio.id),
                ('room_template_id', '=', self.room.id),
            ])
        }
        relines = self.engine.post_stay_nights(
            folio.id, self.room.id,
            '2026-12-24', '2026-12-26', self.plan.id,
            adults=2, children=1)
        self.assertEqual(set(relines.ids), first_ids)
        after = {
            s.folio_line_id.id: (s.net, s.occupancy)
            for s in self.env['hotel.rate.snapshot'].search([
                ('folio_id', '=', folio.id),
                ('room_template_id', '=', self.room.id),
            ])
        }
        self.assertEqual(after, before)
        self.assertEqual(len(after), 4)

    def test_zero_reason_lines_not_posted(self):
        # RO board-basis child: only 2 base lines, no band lines.
        folio = self._folio_for_board('RO')
        lines = self.engine.post_stay_nights(
            folio.id, self.room.id,
            '2026-12-24', '2026-12-26', self.plan.id,
            adults=2, children=1)
        self.assertEqual(len(lines), 2)
        band = lines.filtered(
            lambda l: l.product_id == self.extra_product)
        self.assertEqual(len(band), 0)
        self.assertEqual(sum(lines.mapped('price_total')), 26000.0)
        snaps = self.env['hotel.rate.snapshot'].search([
            ('folio_id', '=', folio.id),
            ('room_template_id', '=', self.room.id),
        ])
        self.assertEqual(len(snaps), 2)
