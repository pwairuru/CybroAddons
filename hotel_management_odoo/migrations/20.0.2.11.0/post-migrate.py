"""Stamp hotel links on reconciled-but-unlinked payments.

Payments posted before the partial-reconcile hook reconciled AFTER
post, so create/post backfill missed them and the reservation
Payments button showed an empty list. One-shot repair; the hook
keeps future payments linked.
"""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    orphans = env['account.payment'].sudo().search([
        ('hotel_booking_id', '=', False),
        ('hotel_folio_id', '=', False),
    ])
    orphans._backfill_hotel_links()
