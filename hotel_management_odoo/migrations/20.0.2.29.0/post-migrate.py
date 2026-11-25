# -*- coding: utf-8 -*-
"""Map old booking_source varchar to booking_origin_id links.

The booking_source Selection was removed from the code; its varchar
column still sits in upgraded DBs. 'website' rows link to the website
origin; every other value (and NULL links) defaults to reception.
Then drop the dead column. Phone has no special backfill: nothing
ever proved old phone rows, and the seed already carries the phone
origin. Idempotent: safe to re-run (fresh installs: column absent).
"""
from odoo import api, SUPERUSER_ID

ORIGINS = (
    ('reception', 'Reception / Walk-in', 10),
    ('website', 'Website', 20),
    ('phone', 'Phone', 30),
)


def _has_booking_source(cr):
    cr.execute(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name='room_booking' "
        "AND column_name='booking_source'")
    return bool(cr.fetchone())


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Origin = env['room.booking.origin']
    for code, name, sequence in ORIGINS:
        if not Origin.with_context(active_test=False).search(
                [('code', '=', code)], limit=1):
            Origin.create({
                'code': code, 'name': name, 'sequence': sequence})
    reception = Origin._by_code('reception')
    website = Origin._by_code('website')
    if not reception:
        return
    if _has_booking_source(cr):
        if website:
            cr.execute(
                "UPDATE room_booking SET booking_origin_id = %s "
                "WHERE booking_source = 'website'",
                (website.id,))
        cr.execute(
            "UPDATE room_booking SET booking_origin_id = %s "
            "WHERE booking_origin_id IS NULL",
            (reception.id,))
        cr.execute("ALTER TABLE room_booking DROP COLUMN booking_source")
    else:
        cr.execute(
            "UPDATE room_booking SET booking_origin_id = %s "
            "WHERE booking_origin_id IS NULL",
            (reception.id,))
