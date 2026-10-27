# -*- coding: utf-8 -*-
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestRatePeriods(TransactionCase):
    def test_seed_twelve_months(self):
        periods = self.env['hotel.rate.period'].search(
            [('active', '=', True)], order='sequence')
        self.assertEqual(len(periods), 12)
        self.assertEqual(periods[0].start_md, '01-01')
        self.assertEqual(periods[0].end_md, '01-31')

    def test_covers_wrap_year(self):
        festive = self.env['hotel.rate.period'].create({
            'name': 'Festive', 'start_md': '12-20', 'end_md': '01-05',
            'sequence': 100,
        })
        self.assertTrue(festive.covers(12, 25))
        self.assertTrue(festive.covers(1, 3))
        self.assertFalse(festive.covers(1, 10))

    def test_bad_month_day_rejected(self):
        with self.assertRaises(ValidationError):
            self.env['hotel.rate.period'].create({
                'name': 'Bad', 'start_md': '13-01', 'end_md': '13-31',
            })

    def test_february_clamps_non_leap_year(self):
        feb = self.env['hotel.rate.period'].search(
            [('start_md', '=', '02-01')], limit=1)
        self.assertEqual(feb.end_md, '02-29')
        date_from, date_to = self.env['hotel.rate.rule']._dates_from_period(
            feb, 2026)
        self.assertEqual(date_from.isoformat(), '2026-02-01')
        self.assertEqual(date_to.isoformat(), '2026-02-28')

    def test_february_keeps_leap_day(self):
        feb = self.env['hotel.rate.period'].search(
            [('start_md', '=', '02-01')], limit=1)
        date_from, date_to = self.env['hotel.rate.rule']._dates_from_period(
            feb, 2024)
        self.assertEqual(date_from.isoformat(), '2024-02-01')
        self.assertEqual(date_to.isoformat(), '2024-02-29')

    def test_impossible_month_day_rejected(self):
        with self.assertRaises(ValidationError):
            self.env['hotel.rate.period'].create({
                'name': 'Bad Feb', 'start_md': '02-30', 'end_md': '02-30',
            })

    def test_covers_rejects_garbage(self):
        period = self.env['hotel.rate.period'].search(
            [('active', '=', True)], limit=1)
        for month, day in [('x', 'y'), (None, None), (13, 1), (1, 32)]:
            with self.assertRaises(ValidationError):
                period.covers(month, day)
