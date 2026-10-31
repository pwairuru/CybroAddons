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


class ServiceBookingLine(models.Model):
    """Model that handles the service booking form"""
    _name = "service.booking.line"
    _description = "Hotel service Line"
    _inherit = ['hotel.booking.line.mixin']

    service_id = fields.Many2one('hotel.service', string="Service",
                                 help="Indicates the Service")
    description = fields.Char(string='Description', related='service_id.name',
                              help="Description of the Service")
    uom_qty = fields.Float(string="Qty", default=1.0,
                           help="The quantity converted into the UoM used by "
                                "the product")
    uom_id = fields.Many2one('uom.uom', readonly=True,
                             string="Unit of Measure",
                             help="This will set the unit of measure used",
                             default=lambda self: self._get_default_unit_uom())
    price_unit = fields.Float(string='Price', related='service_id.unit_price',
                              digits='Product Price',
                              help="The price of the selected service.")
    tax_ids = fields.Many2many('account.tax',
                               'hotel_service_order_line_taxes_rel',
                               'service_id', 'tax_id',
                               related='service_id.taxes_ids', string='Taxes',
                               help="Default taxes used when selling the "
                                    "services.",
                               domain=[('type_tax_use', '=', 'sale')])
    def _charge_product(self):
        """Sellable product for folio charges."""
        self.ensure_one()
        if not self.service_id or not self.service_id.product_id:
            raise ValidationError(
                _("Service line %s has no product (service %s).")
                % (self.id, self.service_id.display_name or '-'))
        return self._charge_product_from_field('service_id.product_id')

    @api.depends('uom_qty', 'price_unit', 'tax_ids')
    def _compute_price_subtotal(self):
        """Compute the amounts of the room booking line."""
        self._compute_booking_line_amounts()