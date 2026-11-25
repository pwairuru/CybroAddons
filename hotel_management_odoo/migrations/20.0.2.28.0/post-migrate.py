# -*- coding: utf-8 -*-
"""Backfill booking_source='website' from chatter evidence.

New field defaults 'reception' for new rows, but existing website
bookings (created via /book before the origin field existed) also get
'reception' from the column default on upgrade. Bookings whose chatter
proves website origin ('source: public /book', posted by
hotel.public.booking.create_booking()) are set back to 'website'.
Idempotent: safe to re-run.
"""
from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    # booking_source was removed from the code (replaced by the
    # booking_origin_id link in 20.0.2.29.0). On DBs where the field
    # or its column is already gone there is nothing to backfill;
    # without this guard pre-28.0 upgrades crash on the write below.
    cr.execute(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name='room_booking' "
        "AND column_name='booking_source'")
    if not cr.fetchone():
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    if 'booking_source' not in env['room.booking']._fields:
        return
    msgs = env['mail.message'].search([
        ('model', '=', 'room.booking'),
        ('body', 'ilike', 'source: public /book'),
    ])
    ids = set(msgs.mapped('res_id'))
    targets = env['room.booking'].browse(ids).exists().filtered(
        lambda b: b.booking_source != 'website')
    if not targets:
        return
    targets.with_context(
        tracking_disable=True, mail_notrack=True,
    ).write({'booking_source': 'website'})
