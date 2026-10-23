# -*- coding: utf-8 -*-
"""Post-migration linking for hotel.room.type (20.0.1.1.0).

Runs AFTER new tables/columns exist. Creates the Standard/Deluxe
sellable types from the distinct ``list_price`` bands found on existing
rooms, then links each physical room (product.template) via the
``num_person`` heuristic:

* num_person <= 1 (legacy 'single') -> Standard
* num_person >= 2 (legacy 'double'/'dormitory') -> Deluxe

The legacy ``room_type`` selection column is kept untouched for
compatibility; it becomes read-only in views in a later task.

Idempotent: re-running reuses existing types matched by code and only
fills rooms whose ``room_type_id`` is still empty.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def _get_or_create_type(env, code, name, base_rate, adult_capacity,
                        max_occupants):
    rtype = env['hotel.room.type'].search([('code', '=', code)], limit=1)
    if rtype:
        return rtype
    return env['hotel.room.type'].create({
        'name': name,
        'code': code,
        'adult_capacity': adult_capacity,
        'child_capacity': 0,
        'max_occupants': max_occupants,
        'base_rate': base_rate,
        'default_board': 'RO',
    })


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    rooms = env['product.template'].search([('is_room', '=', True)])
    prices = sorted({room.list_price for room in rooms if room.list_price})
    if prices:
        median = prices[len(prices) // 2]
    else:
        median = 0.0
    lower = [p for p in prices if p <= median]
    upper = [p for p in prices if p > median]
    standard = _get_or_create_type(
        env, 'STD', 'Standard',
        base_rate=lower[-1] if lower else 0.0,
        adult_capacity=1, max_occupants=1)
    deluxe = _get_or_create_type(
        env, 'DLX', 'Deluxe',
        base_rate=upper[-1] if upper else (prices[-1] if prices else 0.0),
        adult_capacity=2, max_occupants=2)
    _logger.info("ROOM_TYPE_MIGRATION: Standard(id=%s, base_rate=%s) "
                 "Deluxe(id=%s, base_rate=%s) from price bands %s",
                 standard.id, standard.base_rate,
                 deluxe.id, deluxe.base_rate, prices)
    for room in rooms:
        if room.room_type_id:
            continue
        target = standard if (room.num_person or 0) <= 1 else deluxe
        room.room_type_id = target.id
        _logger.info("ROOM_TYPE_MIGRATION map: room %s (legacy=%s, "
                     "num_person=%s, list_price=%s) -> %s",
                     room.display_name, room.room_type, room.num_person,
                     room.list_price, target.code)
        if room.num_person > target.max_occupants:
            _logger.warning(
                "ROOM_TYPE_MIGRATION MANUAL REVIEW: room %s fits %s pax "
                "but linked type %s caps at %s occupants.",
                room.display_name, room.num_person,
                target.code, target.max_occupants)
        if room.list_price and target.base_rate and abs(
                room.list_price - target.base_rate) / target.base_rate > 0.5:
            _logger.warning(
                "ROOM_TYPE_MIGRATION MANUAL REVIEW: room %s list_price %s "
                "differs >50%% from %s base_rate %s.",
                room.display_name, room.list_price,
                target.code, target.base_rate)
