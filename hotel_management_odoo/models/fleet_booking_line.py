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


class FleetBookingLine(models.Model):
    """Model that handles the fleet booking"""
    _name = "fleet.booking.line"
    _description = "Hotel Fleet Line"
    _rec_name = 'fleet_id'
    _inherit = ['hotel.booking.line.mixin']

    fleet_id = fields.Many2one('fleet.vehicle.model',
                               string="Vehicle",
                               help='Indicates the Vehicle')
    description = fields.Char(string='Description',
                              related='fleet_id.display_name',
                              help="Description of Vehicle")
    uom_qty = fields.Float(string="Total KM", default=1,
                           help="The quantity converted into the UoM used by "
                                "the product")
    uom_id = fields.Many2one('uom.uom', readonly=True,
                             string="Unit of Measure",
                             default=lambda self: self._get_default_km_uom(), help="This will set "
                                                              "the unit of"
                                                              " measure used")
    price_unit = fields.Float(string='Rent/KM',
                              related='fleet_id.price_per_km',
                              digits='Product Price',
                              help="The rent/km of the selected fleet.")
    tax_ids = fields.Many2many('account.tax',
                               'hotel_fleet_order_line_taxes_rel',
                               'fleet_id',
                               'tax_id', string='Taxes',
                               help="Default taxes used when renting the fleet"
                                    "models.",
                               domain=[('type_tax_use', '=', 'sale')])
    def _charge_product(self):
        """Sellable product for folio charges.

        Search-first-or-create a service-type product
        ``Hotel: <vehicle display name>`` (company-filtered).
        """
        self.ensure_one()
        vehicle = self.fleet_id
        if not vehicle:
            raise ValidationError(
                _("Fleet line %s has no vehicle selected.") % self.id)
        return self._charge_product_search_or_create(
            'fleet', vehicle.display_name or vehicle.name or '-')

    @api.depends('uom_qty', 'price_unit', 'tax_ids')
    def _compute_price_subtotal(self):
        """Compute the amounts of the room booking line."""
        self._compute_booking_line_amounts()

    def search_available_vehicle(self):
        """Returns list of booked vehicles"""
        return (self.env['fleet.vehicle.model'].search(
            [('id', 'in', self.search([]).mapped('fleet_id').ids)]).ids)