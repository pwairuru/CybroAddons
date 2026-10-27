# -*- coding: utf-8 -*-
"""Post-migration backfill for room type meal prices (20.0.1.14.0).

Runs AFTER ``hotel.room.type.meal.price`` exists and the meal plan
seeds are loaded. Every room type gets one price line per active
meal plan: Room Only (RO) starts at the type ``base_rate`` (the
room-only price authority), every other plan starts at 0.0 for the
manager to fill in.

Idempotent: only lines missing for a type+plan are created; never
touches existing lines. RO lines still at 0.0 get the type base_rate:
the table is brand new at this version, so a 0.0 RO line can only be
auto-created, never user-priced.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    plans = env['hotel.meal.plan'].search([('active', '=', True)])
    if not plans:
        _logger.warning("MEAL_PRICE_MIGRATION: no meal plans found; "
                        "nothing to do.")
        return
    line_model = env['hotel.room.type.meal.price']
    created = 0
    for rtype in env['hotel.room.type'].search([]):
        have = set(rtype.meal_price_ids.mapped('meal_plan_id.id'))
        for plan in plans:
            if plan.id in have:
                continue
            price = rtype.base_rate if plan.code == 'RO' else 0.0
            line_model.create({
                'room_type_id': rtype.id,
                'meal_plan_id': plan.id,
                'price': price,
            })
            created += 1
    _logger.info("MEAL_PRICE_MIGRATION: created %s meal price line(s).",
                 created)
    ro_zero = line_model.search([
        ('meal_plan_id.code', '=', 'RO'),
        ('price', '=', 0.0),
    ])
    for line in ro_zero:
        line.price = line.room_type_id.base_rate
    if ro_zero:
        _logger.info("MEAL_PRICE_MIGRATION: set RO=base_rate on %s "
                     "line(s).", len(ro_zero))
