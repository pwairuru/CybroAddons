# -*- coding: utf-8 -*-
"""Backfill website_published on meal plans.

New field defaults True for new plans, but existing rows get False
from the column default on upgrade. Preserve current /book behaviour:
all overnight plans stay visible, day-use DP stays hidden.
Idempotent: safe to re-run.
"""
from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    plans = env['hotel.meal.plan'].with_context(active_test=False).search([])
    for plan in plans:
        plan.website_published = (plan.code != 'DP')
