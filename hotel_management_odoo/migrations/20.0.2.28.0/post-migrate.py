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
    env = api.Environment(cr, SUPERUSER_ID, {})
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
