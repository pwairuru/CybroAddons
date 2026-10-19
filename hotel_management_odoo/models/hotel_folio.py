# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class HotelFolio(models.Model):
    """Ledger header grouping charges per stay/party.

    Replaces the legacy single-invoice path: charges accumulate on
    folio lines (via hotel.charge.service) and settle once into a
    single account.move.

    Amount truth: amount_untaxed/amount_tax/amount_total are computed
    from the lines through the account.tax engine (same helpers the
    booking lines use), so folio tax always matches what settle posts.
    ``total`` is kept as an alias of amount_total for older callers
    (portal history, total_spent).
    """
    _name = 'hotel.folio'
    _description = "Hotel Folio"
    _order = 'id desc'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    partner_id = fields.Many2one('res.partner', string="Customer",
                                 required=True)
    booking_id = fields.Many2one('room.booking', string="Booking",
                                 help="Room booking this folio belongs to",
                                 ondelete="set null")
    company_id = fields.Many2one('res.company', string="Company",
                                 required=True, index=True,
                                 default=lambda self: self.env.company,
                                 compute='_compute_company', store=True,
                                 readonly=False)
    state = fields.Selection([('open', 'Open'), ('settled', 'Settled')],
                             default='open', required=True)
    line_ids = fields.One2many('hotel.folio.line', 'folio_id',
                               string="Charges")
    move_id = fields.Many2one('account.move', string="Settlement Invoice",
                              readonly=True, ondelete="set null")
    ledger_id = fields.Many2one('hotel.city.ledger', string="City Ledger",
                                readonly=True, ondelete="set null")
    deposit_ids = fields.One2many('hotel.deposit', 'folio_id',
                                 string="Deposits")
    total = fields.Float(string="Total", compute='_compute_totals',
                          store=True,
                          help="Gross incl. tax (alias of Amount Total).")
    amount_untaxed = fields.Float(string="Untaxed", compute='_compute_totals',
                                  store=True)
    amount_tax = fields.Float(string="Tax", compute='_compute_totals',
                              store=True)
    amount_total = fields.Float(string="Amount Total",
                                compute='_compute_totals', store=True)
    deposit_total = fields.Float(string="Deposits", compute='_compute_totals',
                                  store=True)
    amount_due = fields.Float(string="Balance Due", compute='_compute_totals',
                               store=True)

    @api.depends('booking_id.company_id')
    def _compute_company(self):
        for folio in self:
            if folio.booking_id and folio.booking_id.company_id:
                folio.company_id = folio.booking_id.company_id
            elif not folio.company_id:
                folio.company_id = self.env.company

    @api.depends('line_ids.quantity', 'line_ids.price_unit',
                  'line_ids.tax_ids', 'line_ids.price_subtotal',
                  'line_ids.price_tax', 'line_ids.price_total',
                  'deposit_ids.amount', 'deposit_ids.state', 'state')
    def _compute_totals(self):
        for folio in self:
            folio.amount_untaxed = sum(
                line.price_subtotal for line in folio.line_ids)
            folio.amount_tax = sum(
                line.price_tax for line in folio.line_ids)
            folio.amount_total = sum(
                line.price_total for line in folio.line_ids)
            folio.total = folio.amount_total
            folio.deposit_total = sum(
                d.amount for d in folio.deposit_ids
                if d.state in ('draft', 'applied'))
            if folio.state == 'settled':
                folio.amount_due = 0.0
            else:
                folio.amount_due = folio.amount_total - folio.deposit_total

    def action_settle(self):
        """Create (and post) one account.move for all open lines.

        Gross charge lines post untouched (tax stays correct); deposits
        apply as one separate negative-amount line. Consumed deposits
        flip to applied. Returns the created account.move record.
        Reuses account.move ORM only; no accounting core changes.
        """
        self.ensure_one()
        if self.state == 'settled' and self.move_id:
            return self.move_id
        if self.state != 'open':
            raise ValidationError("Only open folios can be settled.")
        if not self.line_ids:
            raise ValidationError("Cannot settle a folio with no charge lines.")
        gross = self.amount_total
        deposits = self.deposit_ids.filtered(
            lambda d: d.state in ('draft', 'applied'))
        deposit_total = sum(deposits.mapped('amount'))
        if deposit_total >= gross:
            raise ValidationError(
                "Deposits cover the full balance; refund instead of settling.")
        company = self.company_id
        journal = self.env['account.journal'].search(
            [('type', '=', 'sale'), ('company_id', '=', company.id)], limit=1)
        if not journal:
            raise ValidationError("No sales journal found for company %s."
                                  % company.display_name)
        move_lines = [(0, 0, {
            'name': line.product_id.display_name or '/',
            'product_id': line.product_id.id,
            'quantity': line.quantity,
            'price_unit': line.price_unit,
            'tax_ids': [(6, 0, line.tax_ids.ids)],
        }) for line in self.line_ids]
        if deposit_total > 0:
            first_product = self.line_ids[0].product_id
            account = (first_product.property_account_income_id
                       or first_product.categ_id
                       .property_account_income_categ_id
                       or journal.default_account_id)
            if not account:
                raise ValidationError(
                    "Cannot determine an income account for the deposit line.")
            move_lines.append((0, 0, {
                'name': 'Deposit applied',
                'quantity': 1,
                'price_unit': -deposit_total,
                'account_id': account.id,
                'tax_ids': [(6, 0, [])],
            }))
        move = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'journal_id': journal.id,
            'company_id': company.id,
            'currency_id': company.currency_id.id,
            'partner_id': self.partner_id.id,
            'invoice_line_ids': move_lines,
        })
        move.action_post()
        expected = gross - deposit_total
        if abs(move.amount_total - expected) > 0.01:
            raise ValidationError(
                "Settlement mismatch: invoice %.2f != folio %.2f."
                % (move.amount_total, expected))
        deposits.write({'state': 'applied'})
        self.write({'state': 'settled', 'move_id': move.id})
        return move
