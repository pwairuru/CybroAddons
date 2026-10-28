# -*- coding: utf-8 -*-
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestRatePlans(TransactionCase):
    def setUp(self):
        super().setUp()
        self.company = self.env.company
        self.double_type = self.env['product.template'].create({
            'name': 'Test Double Room',
            'is_room': True,
            'room_type': 'double',
            'num_person': 2,
            'list_price': 10000.0,
        })
        self.room_product = self.double_type.product_variant_id
        self.peak_plan = self.env['hotel.rate.plan'].create({
            'name': 'Peak Plan',
            'company_id': self.company.id,
        })
        dec = self.env['hotel.rate.period'].search(
            [('start_md', '=', '12-01')], limit=1)
        jun = self.env['hotel.rate.period'].search(
            [('start_md', '=', '06-01')], limit=1)
        self.env['hotel.rate.rule'].create({
            'plan_id': self.peak_plan.id,
            'room_template_id': self.double_type.id,
            'period_id': dec.id, 'period_year': 2026,
            'date_from': '2026-12-20',
            'date_to': '2026-12-31',
            'adjustment_pct': 50.0,
            'min_stay': 1,
        })
        self.env['hotel.rate.rule'].create({
            'plan_id': self.peak_plan.id,
            'room_template_id': self.double_type.id,
            'period_id': jun.id, 'period_year': 2026,
            'date_from': '2026-06-01',
            'date_to': '2026-06-30',
            'adjustment_pct': -20.0,
            'min_stay': 1,
        })
        self.partner = self.company.partner_id
        self.folio = self.env['hotel.folio'].create({
            'partner_id': self.partner.id,
        })

    def test_seasonal_rate_applies(self):
        price_dec = self.env['hotel.rate.engine'].price_for(
            self.double_type.id, '2026-12-24', self.peak_plan.id, 2)
        price_low = self.env['hotel.rate.engine'].price_for(
            self.double_type.id, '2026-06-10', self.peak_plan.id, 2)
        assert price_dec > price_low, "peak must cost more than low season"

    def test_min_stay_rejection(self):
        dec = self.env['hotel.rate.period'].search(
            [('start_md', '=', '12-01')], limit=1)
        self.env['hotel.rate.rule'].create({
            'plan_id': self.peak_plan.id,
            'room_template_id': self.double_type.id,
            'period_id': dec.id, 'period_year': 2026,
            'date_from': '2026-12-24',
            'date_to': '2026-12-26',
            'adjustment_pct': 0.0,
            'min_stay': 3,
            'priority': 20,
        })
        with self.assertRaises(ValidationError):
            self.env['hotel.rate.engine'].post_stay_nights(
                self.folio.id, self.double_type.id,
                '2026-12-24', '2026-12-25', self.peak_plan.id, 2)

    def test_closed_restriction_rejects_posting(self):
        self.env['hotel.rate.restriction'].create({
            'plan_id': self.peak_plan.id,
            'room_template_id': self.double_type.id,
            'date_from': '2026-12-24',
            'date_to': '2026-12-24',
            'closed': True,
        })
        with self.assertRaises(ValidationError):
            self.env['hotel.rate.engine'].post_stay_nights(
                self.folio.id, self.double_type.id,
                '2026-12-24', '2026-12-25', self.peak_plan.id, 2)

    def test_nightly_posting_creates_one_line_per_night(self):
        lines = self.env['hotel.rate.engine'].post_stay_nights(
            self.folio.id, self.double_type.id,
            '2026-06-10', '2026-06-12', self.peak_plan.id, 2)
        self.assertEqual(len(lines), 2)
        dates = self.folio.line_ids.mapped('hotel_date')
        self.assertEqual(len(dates), 2)
        self.assertEqual(min(dates).isoformat(), '2026-06-10')
        self.assertEqual(max(dates).isoformat(), '2026-06-11')

    def test_nightly_posting_is_idempotent(self):
        self.env['hotel.rate.engine'].post_stay_nights(
            self.folio.id, self.double_type.id,
            '2026-06-10', '2026-06-12', self.peak_plan.id, 2)
        count_first = self.env['hotel.folio.line'].search_count([
            ('folio_id', '=', self.folio.id)])
        self.env['hotel.rate.engine'].post_stay_nights(
            self.folio.id, self.double_type.id,
            '2026-06-10', '2026-06-12', self.peak_plan.id, 2)
        count_second = self.env['hotel.folio.line'].search_count([
            ('folio_id', '=', self.folio.id)])
        self.assertEqual(count_first, 2)
        self.assertEqual(count_first, count_second)

    def test_over_capacity_rejects(self):
        with self.assertRaises(ValidationError):
            self.env['hotel.rate.engine'].price_for(
                self.double_type.id, '2026-06-10', self.peak_plan.id, 99)

    def test_partial_stay_posts_nothing_when_middle_night_closed(self):
        self.env['hotel.business.date'].create({
            'date': '2026-06-11', 'is_closed': True,
            'company_id': self.company.id})
        with self.assertRaises(ValidationError):
            self.env['hotel.rate.engine'].post_stay_nights(
                self.folio.id, self.double_type.id,
                '2026-06-10', '2026-06-12', self.peak_plan.id, 2)
        self.assertEqual(self.env['hotel.folio.line'].search_count([
            ('folio_id', '=', self.folio.id)]), 0,
            "closed middle night must leave zero partial lines")

    def test_stay_lines_carry_room_dedup_key(self):
        lines = self.env['hotel.rate.engine'].post_stay_nights(
            self.folio.id, self.double_type.id,
            '2026-06-10', '2026-06-12', self.peak_plan.id, 2)
        self.assertEqual(len(lines), 2)
        for line in lines:
            self.assertEqual(line.room_template_id.id, self.double_type.id)
