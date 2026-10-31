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


class FoodBookingLine(models.Model):
    """Model that handles the food booking"""
    _name = "food.booking.line"
    _description = "Hotel Food Line"
    _rec_name = 'food_id'
    _inherit = ['hotel.booking.line.mixin']

    food_id = fields.Many2one('lunch.product', string="Product",
                              help="Indicates the Food Product")
    description = fields.Char(string='Description',
                              help="Description of Food Product",
                              related='food_id.display_name')
    uom_qty = fields.Float(string="Qty", default=1,
                           help="The quantity converted into the UoM used by "
                                "the product")
    uom_id = fields.Many2one('uom.uom', readonly=True,
                             string="Unit of Measure",
                             default=lambda self: self._get_default_unit_uom(), help="This will set "
                                                                "the unit of"
                                                                " measure used")
    price_unit = fields.Float(related='food_id.price', string='Price',
                              digits='Product Price',
                              help="The price of the selected food item.")
    tax_ids = fields.Many2many('account.tax',
                               'hotel_food_order_line_taxes_rel',
                               'food_id', 'tax_id',
                               string='Taxes',
                               help="Default taxes used when selling the food"
                                    " products.",
                               domain=[('type_tax_use', '=', 'sale')])
    def _charge_product(self):
        """Sellable product for folio charges.

        Prefers lunch.product.product_id when that field exists;
        otherwise search-first-or-create a service-type product
        ``Hotel: <food name>`` (company-filtered).
        """
        self.ensure_one()
        food = self.food_id
        if not food:
            raise ValidationError(
                _("Food line %s has no food selected.") % self.id)
        if 'product_id' in self.env['lunch.product']._fields:
            product = food.product_id
            if product:
                return product
        return self._charge_product_search_or_create(
            'food', food.display_name or food.name or '-')

    @api.depends('uom_qty', 'price_unit', 'tax_ids')
    def _compute_price_subtotal(self):
        """Compute the amounts of the room booking line."""
        self._compute_booking_line_amounts()

    def search_food_orders(self):
        """Returns list of food orders"""
        return (self.search([]).filtered(lambda r: r.booking_id.state not in [
            'check_out', 'cancel', 'done']).ids)
