"""Recompute booking headline totals to include settled POS orders.

_compute_amount_untaxed gained the POS slice via _additional_amounts;
stored totals on existing bookings stay stale until a dependent field
changes, so flush them once here.
"""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    bookings = env['room.booking'].search([])
    bookings._compute_amount_untaxed()
    bookings.flush_recordset()
