# -*- coding: utf-8 -*-
from odoo import api, fields, models, tools, _
from odoo.exceptions import ValidationError


def _assign_tax_amounts(line, base_line):
    """Copy account.tax details onto price_subtotal/tax/total."""
    line.price_subtotal = base_line['tax_details']['total_excluded_currency']
    line.price_total = base_line['tax_details']['total_included_currency']
    line.price_tax = line.price_total - line.price_subtotal


class HotelBookingLineMixin(models.AbstractModel):
    """Shared booking-line fields + tax/charge helpers (behavior-preserving)."""
    _name = 'hotel.booking.line.mixin'
    _description = "Hotel Booking Line Mixin"

    booking_id = fields.Many2one("room.booking", string="Booking",
                                 ondelete="cascade")
    currency_id = fields.Many2one('res.currency', string="Currency",
                                  related='booking_id.pricelist_id.currency_id')
    price_subtotal = fields.Monetary(string="Subtotal",
                                    compute='_compute_price_subtotal',
                                    store=True)
    price_tax = fields.Monetary(string="Total Tax",
                               compute='_compute_price_subtotal',
                               store=True)
    price_total = fields.Monetary(string="Total",
                                 compute='_compute_price_subtotal',
                                 store=True)
    state = fields.Selection(related='booking_id.state',
                             string="Order Status", copy=False)
    folio_line_id = fields.Many2one('hotel.folio.line', string="Folio Line",
                                    readonly=True, copy=False,
                                    ondelete='set null')
    tax_ids = fields.Many2many('account.tax', string='Taxes',
                               domain=[('type_tax_use', '=', 'sale')])

    @tools.ormcache()
    def _get_default_unit_uom(self):
        """Default unit UoM (replaces 3 ormcache copies)."""
        return self.env.ref('uom.product_uom_unit')

    @tools.ormcache()
    def _get_default_km_uom(self):
        """Default km UoM (fleet variant)."""
        return self.env.ref('uom.product_uom_km')

    def _prepare_base_line_for_taxes_computation(self):
        """Shared base-line dict for the account.tax engine."""
        self.ensure_one()
        return self.env['account.tax']._prepare_base_line_for_taxes_computation(
            self,
            **{
                'tax_ids': self.tax_ids,
                'quantity': self.uom_qty,
                'partner_id': self.booking_id.partner_id,
                'currency_id': self.currency_id or self.env.company.currency_id,
            },
        )

    def _compute_booking_line_amounts(self):
        """Shared tax-compute body (incl. import_file invalidate)."""
        for line in self:
            base_line = line._prepare_base_line_for_taxes_computation()
            self.env['account.tax']._add_tax_details_in_base_line(
                base_line, self.env.company)
            self.env['account.tax']._round_base_lines_tax_details(
                [base_line], self.env.company)
            _assign_tax_amounts(line, base_line)
            if self.env.context.get('import_file', False) \
                    and not self.env.user.user_has_groups(
                        'account.group_account_manager'):
                line.tax_ids.invalidate_recordset(
                    ['invoice_repartition_line_ids'])

    def _charge_product_search_or_create(self, source, label):
        """Search-first-or-create service product ``Hotel: <label>``."""
        self.ensure_one()
        company = self.booking_id.company_id or self.env.company
        name = "Hotel: %s" % (label or '-')
        product = self.env['product.product'].search([
            ('name', '=', name),
            ('company_id', 'in', (False, company.id)),
            ('type', '=', 'service'),
        ], limit=1)
        if not product:
            product = self.env['product.product'].create({
                'name': name,
                'type': 'service',
                'list_price': self.price_unit or 0.0,
                'sale_ok': True,
                'purchase_ok': False,
                'company_id': company.id,
            })
        if not product:
            raise ValidationError(
                _("Line %s has no product.") % self.id)
        return product

    def _charge_product_from_field(self, fname):
        """Passthrough helper for direct/nested product fields."""
        self.ensure_one()
        rec = self
        for part in fname.split('.'):
            rec = rec[part]
            if not rec:
                break
        if not rec:
            raise ValidationError(
                _("Line %s has no product (%s).") % (self.id, fname))
        return rec

    def _charge_product_from_fname(self, fname):
        """Alias kept for spec compatibility."""
        return self._charge_product_from_field(fname)
