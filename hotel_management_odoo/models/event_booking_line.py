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
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class EventBookingLine(models.Model):
    """Model that handles the event booking form"""
    _name = "event.booking.line"
    _description = "Hotel Event Line"
    _rec_name = 'event_id'
    _inherit = ['hotel.booking.line.mixin']

    event_id = fields.Many2one('event.event', string="Event",
                               help="Choose the Event")
    ticket_id = fields.Many2one('product.product', string="Ticket",
                                help="Choose the Ticket Type",
                                domain=[('service_tracking', '=', 'event')]
                                )
    description = fields.Char(string='Description', help="Detailed "
                                                         "description of the "
                                                         "event",
                              related='event_id.display_name')
    uom_qty = fields.Float(string="Quantity", default=1,
                           help="The quantity converted into the UoM used by "
                                "the product")
    uom_id = fields.Many2one('uom.uom', readonly=True,
                             string="Unit of Measure",
                             related='ticket_id.uom_id', help="This will set "
                                                              "the unit of"
                                                              " measure used")
    price_unit = fields.Float(related='ticket_id.lst_price', string='Price',
                              digits='Product Price',
                              help="The selling price of the selected ticket.")
    tax_ids = fields.Many2many('account.tax',
                               'hotel_event_order_line_taxes_rel',
                               'event_id',
                               'tax_id',
                               string='Taxes',
                               compute='_compute_tax_ids',
                               store=True, readonly=False,
                               help="Default taxes used when selling the event"
                                    "tickets.",
                               domain=[('type_tax_use', '=', 'sale')])
    currency_id = fields.Many2one(
        related='booking_id.pricelist_id.currency_id', string='Currency',
        help='The currency used', store=True, precompute=True)

    def _charge_product(self):
        """Sellable product for folio charges (the event ticket)."""
        self.ensure_one()
        if not self.ticket_id:
            raise ValidationError(
                _("Event line %s has no ticket.") % self.id)
        return self._charge_product_from_field('ticket_id')

    @api.depends('ticket_id', 'booking_id.company_id')
    def _compute_tax_ids(self):
        """Restrict the ticket's taxes to the booking's own company"""
        for line in self:
            company = line.booking_id.company_id or self.env.company
            line.tax_ids = line.ticket_id.taxes_id.filtered(
                lambda tax: not tax.company_id or tax.company_id == company)

    @api.depends('uom_qty', 'price_unit', 'tax_ids')
    def _compute_price_subtotal(self):
        """Compute the amounts of the room booking line."""
        self._compute_booking_line_amounts()