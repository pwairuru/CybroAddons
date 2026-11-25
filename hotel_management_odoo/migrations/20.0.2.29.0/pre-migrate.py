# -*- coding: utf-8 -*-
"""Pre-create room.booking.origin table + seeds before registry init.

Upgrade 28.0→29.0 crashes in registry init: the new required
``booking_origin_id`` column default (``_default_origin`` →
``_by_code('reception')``) searches ``room_booking_origin`` before
Odoo creates that table in the same init pass (missing relation).
Fresh installs are unaffected (no booking rows at init).

This runs before the ORM pass, so raw SQL/cr only — no ORM, no
``api.Environment`` (registry not ready). Creates the core columns;
the ORM adds the remaining (mail.thread/activity mixin) columns
during init. Seeds the 3 origins + matching ``ir_model_data``
noupdate rows so the later ``data/room_booking_origin_data.xml``
seed skips instead of clashing. Idempotent: safe to re-run.
"""

ORIGINS = (
    ('reception', 'Reception / Walk-in', 10),
    ('website', 'Website', 20),
    ('phone', 'Phone', 30),
)

XML_IDS = {
    'reception': 'room_booking_origin_reception',
    'website': 'room_booking_origin_website',
    'phone': 'room_booking_origin_phone',
}


def migrate(cr, version):
    cr.execute(
        "CREATE TABLE IF NOT EXISTS room_booking_origin ("
        "id SERIAL PRIMARY KEY, "
        "name VARCHAR NOT NULL, "
        "code VARCHAR NOT NULL, "
        "sequence INTEGER, "
        "active BOOLEAN DEFAULT true, "
        "create_uid INTEGER, "
        "create_date TIMESTAMP, "
        "write_uid INTEGER, "
        "write_date TIMESTAMP)")
    for code, name, sequence in ORIGINS:
        cr.execute(
            "INSERT INTO room_booking_origin (name, code, sequence, "
            "active) SELECT %s, %s, %s, true WHERE NOT EXISTS "
            "(SELECT 1 FROM room_booking_origin WHERE code = %s)",
            (name, code, sequence, code))
    for code, _name, _sequence in ORIGINS:
        cr.execute(
            "INSERT INTO ir_model_data "
            "(module, name, model, res_id, noupdate, date_init, "
            "date_update) SELECT %s, %s, 'room.booking.origin', o.id, "
            "true, now() AT TIME ZONE 'UTC', now() AT TIME ZONE 'UTC' "
            "FROM room_booking_origin o WHERE o.code = %s "
            "AND NOT EXISTS (SELECT 1 FROM ir_model_data d "
            "WHERE d.module = %s AND d.name = %s)",
            ('hotel_management_odoo', XML_IDS[code], code,
             'hotel_management_odoo', XML_IDS[code]))
