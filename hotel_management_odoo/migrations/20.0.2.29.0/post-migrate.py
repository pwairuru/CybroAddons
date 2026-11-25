# -*- coding: utf-8 -*-
"""Map old booking_source varchar to booking_origin_id links.

The booking_source Selection was removed from the code; its varchar
column still sits in upgraded DBs. Chatter evidence ('source: public
/book') links website bookings first — this folds in the 28.0
backfill, which cannot run under new code (its ORM field write
targets a removed field), so direct <28→29 jumps stay correct: the
28.0 migration stays a guarded no-op and this single migration owns
the whole mapping. Then 'website' varchar rows link to the website
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

CHATTER_MARKER = 'source: public /book'


def _has_booking_source(cr):
    cr.execute(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name='room_booking' "
        "AND column_name='booking_source'")
    return bool(cr.fetchone())


def _require_origin(Origin, code):
    """Resolve ``code`` the same way the ensure step searches.

    Origins were just ensured above, so a miss means creation
    failed — raise instead of leaving NULL links or misclassifying
    website rows before the irreversible DROP COLUMN.
    """
    origin = Origin.with_context(active_test=False).search(
        [('code', '=', code)], limit=1)
    if not origin:
        raise ValueError(
            "room.booking.origin '%s' missing after ensure; aborting "
            "migration instead of leaving bad links." % code)
    return origin


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Origin = env['room.booking.origin']
    for code, name, sequence in ORIGINS:
        if not Origin.with_context(active_test=False).search(
                [('code', '=', code)], limit=1):
            Origin.create({
                'code': code, 'name': name, 'sequence': sequence})
    reception = _require_origin(Origin, 'reception')
    website = _require_origin(Origin, 'website')
    # Chatter proof first (folded 28.0 backfill): on direct <28→29
    # jumps the varchar flagging never ran, so map from evidence
    # directly instead of trusting the varchar.
    cr.execute(
        "UPDATE room_booking b SET booking_origin_id = %s "
        "FROM mail_message m "
        "WHERE m.model = 'room.booking' AND m.res_id = b.id "
        "AND m.body ILIKE %s",
        (website.id, '%' + CHATTER_MARKER + '%'))
    if _has_booking_source(cr):
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
