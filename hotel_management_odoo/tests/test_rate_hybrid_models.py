# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase


class TestHybridModels(TransactionCase):
    def test_models_exist(self):
        self.assertIn('hotel.rate.meal.supplement', self.env)
        self.assertIn('hotel.rate.plan.adjustment', self.env)
        self.assertIn('rate_missing_mode', self.env['res.company']._fields)
        self.assertIn('plan_id', self.env['hotel.rate.line']._fields)
        self.assertIn('fallback_reason', self.env['hotel.rate.snapshot']._fields)
