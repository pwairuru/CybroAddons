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

class HotelPosLine(models.Model):
    """Store and link POS orders with hotel bookings for tracking and billing purposes."""
    _name = "hotel.pos.line"
    _description = "Hotel POS Line"

    booking_id = fields.Many2one("room.booking", string="Booking", ondelete="cascade")
    pos_order_id = fields.Many2one("pos.order", string="POS Order")
    pos_reference = fields.Char(related="pos_order_id.pos_reference", string="POS Ref")
    date_order = fields.Datetime(related="pos_order_id.date_order", string="Date")
    amount_total = fields.Monetary(related="pos_order_id.amount_total", string="Total")
    currency_id = fields.Many2one(related='booking_id.pricelist_id.currency_id', string="Currency")
    state = fields.Selection(related="pos_order_id.state", string="Status")
    session_id = fields.Many2one(related="pos_order_id.session_id", string="Session")
    user_id = fields.Many2one(related="pos_order_id.user_id", string="Cashier")
    partner_id = fields.Many2one(related="pos_order_id.partner_id", string="Customer")
    is_pay_at_checkout = fields.Boolean(
        string="Pay At Checkout", compute='_compute_checkout_due',
        store=False,
        help="True when the POS order was charged to the room (hotel-charge "
             "payment method): the guest pays it at checkout, not at the till.")
    due_until_settle = fields.Boolean(
        string="Due At Checkout", compute='_compute_checkout_due',
        store=False,
        help="True while a pay-at-checkout charge sits on the guest's open "
             "balance (folio still open). A Paid POS state alone does not "
             "mean the hotel has the money.")

    @api.depends('pos_order_id.payment_ids.payment_method_id.is_hotel_charge',
                 'pos_order_id.state', 'booking_id')
    def _compute_checkout_due(self):
        Folio = self.env['hotel.folio']
        for link in self:
            order = link.pos_order_id
            pay_at_checkout = bool(order) and any(
                p.payment_method_id.is_hotel_charge
                for p in order.payment_ids)
            link.is_pay_at_checkout = pay_at_checkout
            if not (pay_at_checkout and order
                    and order.state in ('paid', 'done', 'invoiced')
                    and link.booking_id):
                link.due_until_settle = False
                continue
            link.due_until_settle = bool(Folio.search([
                ('booking_id', '=', link.booking_id.id),
                ('state', '=', 'open'),
            ], limit=1))
