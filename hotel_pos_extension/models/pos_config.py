# -*- coding: utf-8 -*-
#############################################################################
#
#    Cybrosys Technologies Pvt. Ltd.
#
#    Copyright (C) 2026-TODAY Cybrosys Technologies(<https://www.cybrosys.com>)
#    Author: Cybrosys Techno Solutions(<https://www.cybrosys.com>)
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
from odoo import fields, models


class PosConfig(models.Model):
    """Per-terminal M-Pesa paybill printed on the POS receipt.

    Most registers share the default paybill; a few print their own.
    Free-form fields so any customer sets their own numbers per
    terminal with no code change. The receipt QWeb reads them from
    the ``config`` dict and hides the block when empty.
    """
    _inherit = 'pos.config'

    receipt_paybill_number = fields.Char(
        string='M-Pesa Paybill',
        help='Paybill number printed on this terminal\'s receipts. '
             'Empty hides the M-Pesa block on the ticket.')
    receipt_paybill_account = fields.Char(
        string='M-Pesa Account Name',
        help='Account name printed under the paybill on this '
             'terminal\'s receipts.')
