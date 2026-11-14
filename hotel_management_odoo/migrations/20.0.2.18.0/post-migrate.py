# -*- coding: utf-8 -*-
from odoo import api, SUPERUSER_ID

LEGACY_PAYBILL_NUMBER = '4141717'
LEGACY_PAYBILL_ACCOUNT = 'CAMP DAVID UNITED'


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    for company in env['res.company'].search([]):
        vals = {}
        if not company.mpesa_paybill_number:
            vals['mpesa_paybill_number'] = LEGACY_PAYBILL_NUMBER
        if not company.mpesa_paybill_account:
            vals['mpesa_paybill_account'] = LEGACY_PAYBILL_ACCOUNT
        if vals:
            company.write(vals)
