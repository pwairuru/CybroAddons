# -*- coding: utf-8 -*-
#############################################################################
#
#    Cybrosys Technologies Pvt. Ltd.
#
#    Copyright (C) 2026-TODAY Cybrosys Technologies(<https://www.cybrosys.com>)
#
#    You can modify it under the terms of the GNU LESSER
#    GENERAL PUBLIC LICENSE (LGPL v3), Version 3.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU LESSER GENERAL PUBLIC LICENSE (LGPL v3) for more details.
#
#    You should have received a copy of the GNU LESSER GENERAL PUBLIC LICENSE
#    (LGPL v3) along with this program.
#    If not, see <http://www.gnu.org/licenses/>.
#
#############################################################################
from odoo import api, SUPERUSER_ID

# One-time backfill for the Esidai upgrade to per-terminal paybills.
# The receipt template used to hardcode these values for every register;
# existing terminals keep printing them until staff sets per-register
# values on the POS config form. Fresh installs start empty (block
# hidden) so other customers enter their own numbers.
LEGACY_PAYBILL_NUMBER = '4141717'
LEGACY_PAYBILL_ACCOUNT = 'CAMP DAVID UNITED'


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    configs = env['pos.config'].search([
        '|',
        ('receipt_paybill_number', '=', False),
        ('receipt_paybill_number', '=', ''),
    ])
    for config in configs:
        vals = {}
        if not config.receipt_paybill_number:
            vals['receipt_paybill_number'] = LEGACY_PAYBILL_NUMBER
        if not config.receipt_paybill_account:
            vals['receipt_paybill_account'] = LEGACY_PAYBILL_ACCOUNT
        if vals:
            config.write(vals)
