# -*- coding: utf-8 -*-
"""Post-migration for toddler band removal (20.0.1.15.0).

Reassigns every ``hotel.rate.occupancy`` row still on band
``toddler`` to ``child``. When a child row already exists for the
same room type + plan, the duplicate merges by keeping the lowest
id row and deleting the other (constraint ``_check_unique_band``
would otherwise reject the rewrite).

Idempotent: a second run finds no toddler rows and does nothing.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
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
