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


class HotelService(models.Model):
    """Model that holds the all hotel services"""
    _name = 'hotel.service'
    _description = "Hotel Service"
    _inherit = 'mail.thread'
    _order = 'id desc'

    name = fields.Char(string="Service", help="Name of the service",
                       required=True)
    unit_price = fields.Float(string="Price", help="Price of the service",
                              default=0.0)
    taxes_ids = fields.Many2many('account.tax',
                                 'hotel_service_taxes_rel',
                                 'service_id', 'tax_id',
                                 string='Customer Taxes',
                                 help="Default taxes used when selling the"
                                      " service product.",
                                 domain=[('type_tax_use', '=', 'sale')],
                                 default=lambda self:
                                 self.env.company.account_sale_tax_id)
    product_id = fields.Many2one('product.product', string="Service Product",
                                 ondelete='restrict', copy=False,
                                 tracking=True,
                                 help="Sellable service product for folios.")

    def _prepare_service_product_vals(self):
        """Product vals mirroring this service (company same)."""
        self.ensure_one()
        return {
            'name': self.name,
            'type': 'service',
            'list_price': self.unit_price or 0.0,
            'taxes_id': [(6, 0, self.taxes_ids.ids)],
            'sale_ok': True,
            'purchase_ok': False,
            'company_id': self.env.company.id,
        }

    def _ensure_product(self):
        """Create linked product when missing; raise if creation fails."""
        for svc in self:
            if svc.product_id:
                continue
            product = self.env['product.product'].create(
                svc._prepare_service_product_vals())
            if not product:
                raise ValidationError(
                    _("Failed to create service product for %s.") % svc.name)
            svc.product_id = product.id
            if not svc.product_id:
                raise ValidationError(
                    _("Service %s requires a product.") % svc.name)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._ensure_product()
        return records

    def write(self, vals):
        res = super().write(vals)
        if any(f in vals for f in ('name', 'unit_price', 'taxes_ids')):
            for svc in self:
                if not svc.product_id:
                    svc._ensure_product()
                    continue
                prod_vals = {}
                if 'name' in vals:
                    prod_vals['name'] = svc.name
                if 'unit_price' in vals:
                    prod_vals['list_price'] = svc.unit_price
                if 'taxes_ids' in vals:
                    prod_vals['taxes_id'] = [(6, 0, svc.taxes_ids.ids)]
                if prod_vals:
                    svc.product_id.write(prod_vals)
        return res

    def _charge_product(self):
        """Sellable product for folio charges (symmetry helper for T2)."""
        self.ensure_one()
        if not self.product_id:
            raise ValidationError(
                _("Service %s has no product.") % self.name)
        return self.product_id