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
from odoo import api, fields, models


class AccountMove(models.Model):

    """Inherited account. move for adding hotel booking reference field to
    invoicing model."""
    _inherit = "account.move"

    hotel_booking_id = fields.Many2one('room.booking',
                                       string="Booking Reference",
                                       readonly=True, help="Choose the Booking"
                                                           "Reference")
    hotel_folio_id = fields.Many2one('hotel.folio', string="Folio",
                                     index=True, ondelete="set null",
                                     help="Folio this invoice was generated "
                                     "from (folio unification).")


class AccountPayment(models.Model):
    """Folio link for payments tab (folio unification)."""
    _inherit = "account.payment"

    hotel_folio_id = fields.Many2one('hotel.folio', string="Folio",
                                     index=True, ondelete="set null",
                                     help="Folio this payment applies to.")
    hotel_booking_id = fields.Many2one('room.booking', string="Booking",
                                       index=True, ondelete="set null",
                                       help="Booking this payment applies to.")

    def _backfill_hotel_links(self):
        """Copy folio/booking links from the reconciled invoices.

        The register wizard reconciles at post time, after create, so
        create-time backfill alone misses the links. Never overwrites
        links already set (manual routing wins)."""
        for rec in self:
            if rec.hotel_folio_id and rec.hotel_booking_id:
                continue
            inv = rec.reconciled_invoice_ids[:1]
            if not inv:
                continue
            if not rec.hotel_folio_id and inv.hotel_folio_id:
                rec.hotel_folio_id = inv.hotel_folio_id
            if not rec.hotel_booking_id and inv.hotel_booking_id:
                rec.hotel_booking_id = inv.hotel_booking_id

    @api.model_create_multi
    def create(self, vals_list):
        recs = super().create(vals_list)
        # Single backfill: vals invoice commands first (create-time
        # link), else the stored reconciled invoices.
        for rec, vals in zip(recs, vals_list):
            if rec.hotel_folio_id and rec.hotel_booking_id:
                continue
            inv = False
            inv_ids = []
            for key in ('invoice_ids', 'reconciled_invoice_ids',
                        'reconciled_bill_ids'):
                for cmd in vals.get(key) or []:
                    if cmd[0] == 6:
                        inv_ids += cmd[2]
                    elif cmd[0] == 4:
                        inv_ids.append(cmd[1])
            if inv_ids:
                inv = self.env['account.move'].sudo().browse(inv_ids[:1])
            elif rec.reconciled_invoice_ids:
                inv = rec.reconciled_invoice_ids[:1]
            if not inv:
                continue
            if not rec.hotel_folio_id:
                rec.hotel_folio_id = inv.hotel_folio_id
            if not rec.hotel_booking_id:
                rec.hotel_booking_id = inv.hotel_booking_id
        return recs

    def action_post(self):
        """Post, then backfill folio/booking links from reconciliation."""
        res = super().action_post()
        self._backfill_hotel_links()
        return res