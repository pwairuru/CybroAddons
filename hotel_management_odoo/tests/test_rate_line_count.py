# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase


class TestRateLineCount(TransactionCase):
    def setUp(self):
        super().setUp()
        self.co = self.env.company
        self.type = self.env['hotel.room.type'].create({
            'name': 'CountStd', 'base_rate': 10000.0,
        })
        self.meal_ro = self.env['hotel.meal.plan'].with_context(
            active_test=False).search([('code', '=', 'RO')], limit=1)
        self.h1 = self.env['hotel.rate.period'].create({
            'name': 'C1', 'start_md': '01-01', 'end_md': '06-30',
            'sequence': 10, 'priority': 10, 'company_id': self.co.id})
        self.h2 = self.env['hotel.rate.period'].create({
            'name': 'C2', 'start_md': '07-01', 'end_md': '12-31',
            'sequence': 10, 'priority': 10, 'company_id': self.co.id})

    def _make_line(self, room_type, period):
        return self.env['hotel.rate.line'].create({
            'company_id': self.co.id,
            'period_id': period.id,
            'room_type_id': room_type.id,
            'meal_plan_id': self.meal_ro.id,
            'price': 10000.0,
        })

    def test_rate_line_count(self):
        self.assertEqual(self.type.rate_line_count, 0)
        self._make_line(self.type, self.h1)
        self._make_line(self.type, self.h2)
        # Non-stored compute caches per recordset: refresh after writes.
        self.type.invalidate_recordset(['rate_line_count'])
        self.assertEqual(self.type.rate_line_count, 2)
        other = self.env['hotel.room.type'].create({
            'name': 'CountDlx', 'base_rate': 20000.0,
        })
        self._make_line(other, self.h1)
        (self.type + other).invalidate_recordset(['rate_line_count'])
        counts = {t.id: t.rate_line_count for t in (self.type + other)}
        self.assertEqual(counts[self.type.id], 2)
        self.assertEqual(counts[other.id], 1)
