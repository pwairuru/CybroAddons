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
