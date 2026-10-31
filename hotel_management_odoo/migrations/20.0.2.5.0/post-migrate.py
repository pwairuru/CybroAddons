"""Migrate booking/folio sequences to yearly reset.

XML is noupdate=1, so existing DBs keep BOOKING//FOLIO/ without this.
Sets RES/%(range_year)s/ + FOL/%(range_year)s/ with use_date_range
and ensures date ranges for current year +/- 2.
"""
from datetime import date

from odoo import SUPERUSER_ID, api


def _ensure_yearly(env, code, prefix, padding=4, years=(-1, 0, 1, 2)):
    seq = env['ir.sequence'].search([('code', '=', code)], limit=1)
    if not seq:
        return
    seq.write({
        'prefix': prefix,
        'padding': padding,
        'use_date_range': True,
    })
    today_year = date.today().year
    for offset in years:
        year = today_year + offset
        existing = env['ir.sequence.date_range'].search([
            ('sequence_id', '=', seq.id),
            ('date_from', '<=', f'{year}-06-30'),
            ('date_to', '>=', f'{year}-06-30'),
        ], limit=1)
        if not existing:
            env['ir.sequence.date_range'].create({
                'sequence_id': seq.id,
                'date_from': f'{year}-01-01',
                'date_to': f'{year}-12-31',
            })


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    _ensure_yearly(env, 'room.booking', 'RES/%(range_year)s/')
    _ensure_yearly(env, 'hotel.folio', 'FOL/%(range_year)s/')
