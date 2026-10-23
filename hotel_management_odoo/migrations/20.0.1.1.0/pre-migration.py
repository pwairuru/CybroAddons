# -*- coding: utf-8 -*-
"""Pre-migration audit for hotel.room.type introduction (20.0.1.1.0).

Runs BEFORE new tables/columns exist, so this step is strictly read-only:
it snapshots the current room population so the post-migration linking
(post-migration.py) and any manual review have a baseline in the logs.

The legacy ``room_type`` selection column is left untouched here and in
post-migration; views keep rendering it read-only until a later task
removes it.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("""
        SELECT room_type, num_person, COUNT(*), MIN(list_price), MAX(list_price)
        FROM product_template
        WHERE is_room IS TRUE
        GROUP BY room_type, num_person
        ORDER BY room_type, num_person
    """)
    rows = cr.fetchall()
    if not rows:
        _logger.info("ROOM_TYPE_MIGRATION: no rooms found; nothing to map.")
        return
    _logger.info("ROOM_TYPE_MIGRATION pre-audit: "
                 "(legacy_room_type, num_person, count, min_price, max_price)")
    for room_type, num_person, count, min_price, max_price in rows:
        _logger.info("ROOM_TYPE_MIGRATION pre-audit: (%s, %s, %s, %s, %s) "
                     "-> MANUAL REVIEW: confirm Standard vs Deluxe mapping "
                     "for this band after upgrade.",
                     room_type, num_person, count, min_price, max_price)
