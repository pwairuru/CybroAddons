# -*- coding: utf-8 -*-
"""Post-migration for 20.0.1.15.0: toddler merge + meal-line backfills.

Step 1 (toddler band removal): reassigns every ``hotel.rate.occupancy``
row still on band ``toddler`` to ``child``. When a child row already
exists for the same room type + plan, the duplicate merges by keeping
the lowest id row and deleting the other (constraint
``_check_unique_band`` would otherwise reject the rewrite).

Step 2 (rule meal-line backfill): rules created before the
``hotel.rate.rule.meal.line`` model existed (or before the rule-create
backfill hook) have no per-plan lines. Creates the missing lines at
0% percent — one per active meal plan.

Step 3 (type meal-line coverage): calls ``ensure_meal_price_lines``
on every room type so each type keeps one price line per active
meal plan.

Idempotent: reruns find no toddler rows and no missing lines and do
nothing.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def _migrate_toddler_to_child(env):
    occ_model = env['hotel.rate.occupancy']
    toddlers = occ_model.search([('band', '=', 'toddler')], order='id')
    if not toddlers:
        _logger.info("TODDLER_MIGRATION: no toddler rows; nothing to do.")
        return
    rewritten = 0
    merged = 0
    for rec in toddlers:
        sibling = occ_model.search([
            ('id', '!=', rec.id),
            ('room_type_id', '=', rec.room_type_id.id),
            ('plan_id', '=', rec.plan_id.id or False),
            ('band', '=', 'child'),
        ], limit=1, order='id')
        if not sibling:
            rec.write({'band': 'child'})
            rewritten += 1
        elif sibling.id < rec.id:
            rec.unlink()
            merged += 1
        else:
            sibling.unlink()
            rec.write({'band': 'child'})
            merged += 1
    _logger.info("TODDLER_MIGRATION: rewrote %s row(s) to child, "
                 "merged %s duplicate(s).", rewritten, merged)


def _backfill_rule_meal_lines(env):
    plans = env['hotel.meal.plan'].search([('active', '=', True)])
    if not plans:
        _logger.info("RULE_LINE_MIGRATION: no active meal plans; "
                     "nothing to do.")
        return
    line_model = env['hotel.rate.rule.meal.line']
    created = 0
    for rule in env['hotel.rate.rule'].search([]):
        have = set(rule.meal_line_ids.mapped('meal_plan_id.id'))
        for plan in plans:
            if plan.id not in have:
                line_model.create({
                    'rule_id': rule.id,
                    'meal_plan_id': plan.id,
                    'rate_type': 'percent',
                    'value': 0.0,
                })
                created += 1
    _logger.info("RULE_LINE_MIGRATION: created %s missing rule meal "
                 "line(s) at 0%%.", created)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    _migrate_toddler_to_child(env)
    _backfill_rule_meal_lines(env)
    env['hotel.room.type'].search([]).ensure_meal_price_lines()
    _logger.info("TYPE_LINE_MIGRATION: ensured meal price line coverage "
                 "for all room types.")
