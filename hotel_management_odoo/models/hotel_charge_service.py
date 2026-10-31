# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError

from .hotel_booking_line_mixin import _assign_tax_amounts
from .hotel_business_date import _to_date

ROUTINGS = ('to_guest', 'to_master', 'to_personal', 'to_company')


class HotelFolioLine(models.Model):
    """Single charge on a folio ledger."""
    _name = 'hotel.folio.line'
    _description = "Hotel Folio Line"
    _order = 'id'

    folio_id = fields.Many2one('hotel.folio', string="Folio",
                               required=True, ondelete="cascade")
    company_id = fields.Many2one('res.company', string="Company",
                                 related='folio_id.company_id', store=True,
                                 index=True, readonly=True)
    product_id = fields.Many2one('product.product', string="Product",
                                  required=True)
    quantity = fields.Float(string="Qty", default=1.0)
    price_unit = fields.Float(string="Unit Price", default=0.0)
    routing = fields.Selection(
        [('to_guest', 'To Guest'),
         ('to_master', 'To Master'),
         ('to_personal', 'To Personal'),
         ('to_company', 'To Company')],
        string="Routing",
        help="Charge routing code",
        default='to_guest')
    tax_ids = fields.Many2many('account.tax',
                                'hotel_folio_line_taxes_rel',
                                'line_id', 'tax_id',
                                string='Taxes',
                                domain=[('type_tax_use', '=', 'sale')])
    hotel_date = fields.Date(string="Hotel Date",
                             default=fields.Date.today,
                             help="Business date this charge belongs to")
    room_template_id = fields.Many2one(
        'product.template', string="Room", index=True,
        domain=[('is_room', '=', True)],
        help="Room this charge belongs to; part of the stay-night "
             "dedup key (folio + product + hotel date + room).")
    booking_line_id = fields.Many2one(
        'room.booking.line', string="Booking Line", index=True,
        ondelete="set null",
        help="Source stay line when this charge is a room night.")
    source = fields.Char(string="Source", default='rate', index=True,
                         help="Charge origin: rate/meal/pos/service/manual. "
                         "Room scope only; POS/services attach later.")
    pos_order_id = fields.Many2one(
        'pos.order', string="POS Order", index=True, ondelete="set null",
        help="POS order this charge came from (source='pos').")
    invoiced_qty = fields.Float(string="Invoiced Qty", default=0.0,
                                help="Qty already covered by a folio invoice.")
    locked = fields.Boolean(string="Locked", default=False,
                            help="Set once a folio invoice covers the line.")
    price_subtotal = fields.Float(string="Subtotal",
                                  compute='_compute_price_subtotal',
                                  store=True)
    price_tax = fields.Float(string="Tax",
                             compute='_compute_price_subtotal',
                             store=True)
    price_total = fields.Float(string="Total",
                               compute='_compute_price_subtotal',
                               store=True)

    @api.depends('quantity', 'price_unit', 'tax_ids',
                 'folio_id.partner_id', 'folio_id.company_id')
    def _compute_price_subtotal(self):
        """Line amounts through the account.tax engine (folio tax truth)."""
        for line in self:
            base_line = line._prepare_base_line_for_taxes_computation()
            self.env['account.tax']._add_tax_details_in_base_line(
                base_line, line.folio_id.company_id or self.env.company)
            self.env['account.tax']._round_base_lines_tax_details(
                [base_line],
                line.folio_id.company_id or self.env.company)
            _assign_tax_amounts(line, base_line)

    def _prepare_base_line_for_taxes_computation(self):
        self.ensure_one()
        return self.env[
            'account.tax']._prepare_base_line_for_taxes_computation(
            self,
            **{
                'tax_ids': self.tax_ids,
                'quantity': self.quantity or 0.0,
                'partner_id': self.folio_id.partner_id,
                'currency_id': (self.folio_id.company_id.currency_id
                                or self.env.company.currency_id),
            },
        )

    def action_transfer(self, target_folio_id):
        """Move this line to another folio (split/merge support).

        Guards: source folio must be open, both folios share one
        company, and both the line's hotel date and today must be open
        business days (closed-day corrections post on the open day).
        The move is logged on both folios via chatter.
        """
        self.ensure_one()
        target = self.env['hotel.folio'].browse(target_folio_id)
        if not target.exists():
            raise ValidationError("Target folio %s does not exist."
                                  % target_folio_id)
        source = self.folio_id
        if source.state != 'open':
            raise ValidationError("Can only transfer from an open folio.")
        if target.state != 'open':
            raise ValidationError("Can only transfer to an open folio.")
        if target.company_id.id != source.company_id.id:
            raise ValidationError(
                "Transfer needs one company; %s -> %s."
                % (source.company_id.display_name,
                   target.company_id.display_name))
        checker = self.env['hotel.charge.service']
        checker._check_open_day(self.hotel_date, source.company_id)
        checker._check_open_day(fields.Date.today(), source.company_id)
        self.write({'folio_id': target.id})
        message = ("Charge moved: %s x %s (%s) from folio %s to folio %s."
                   % (self.quantity, self.price_unit,
                      self.hotel_date, source.id, target.id))
        source.message_post(body=message)
        target.message_post(body=message)
        return self


class HotelChargeService(models.AbstractModel):
    """Posting API for folio charges.

    Produces hotel.folio.line records; pricing callers resolve via
    product.pricelist and account.tax computation before calling.
    """
    _name = 'hotel.charge.service'
    _description = "Hotel Charge Service"

    @api.model
    def _check_open_day(self, hotel_date, company=None):
        company = company or self.env.company
        if self.env['hotel.business.date'].is_day_closed(hotel_date,
                                                     company=company):
            raise ValidationError("Closed day: post adjustment on open day")

    @api.model
    def post_charge(self, folio_id, product_id, qty, price_unit,
                    routing='to_guest', hotel_date=None,
                    room_template_id=None, booking_line_id=None,
                    source='rate', pos_order_id=None):
        day = _to_date(hotel_date)
        if routing not in ROUTINGS:
            raise ValidationError("Unknown routing %s." % routing)
        folio = self.env['hotel.folio'].browse(folio_id)
        if not folio.exists():
            raise ValidationError("Folio %s does not exist." % folio_id)
        if folio.state != 'open':
            raise ValidationError("Can only post charges to an open folio.")
        folio_company = folio.company_id
        if folio_company.id != self.env.company.id:
            raise ValidationError(
                "Folio belongs to %s; post from that company."
                % folio_company.display_name)
        self._check_open_day(day, folio_company)
        if qty <= 0:
            raise ValidationError("Quantity must be positive.")
        product = self.env['product.product'].browse(product_id)
        if not product.exists():
            raise ValidationError("Product %s does not exist." % product_id)
        line = self.env['hotel.folio.line'].create({
            'folio_id': folio.id,
            'product_id': product.id,
            'quantity': qty,
            'price_unit': price_unit,
            'routing': routing or 'to_guest',
            'hotel_date': day,
            'tax_ids': [(6, 0, product.taxes_id.ids)],
            'room_template_id': room_template_id or False,
            'booking_line_id': booking_line_id or False,
            'source': source or 'rate',
            'pos_order_id': pos_order_id or False,
        })
        return line
