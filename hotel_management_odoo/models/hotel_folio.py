# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.addons.base.models.avatar_mixin import generate_text_avatar_svg
from odoo.exceptions import ValidationError


class HotelFolio(models.Model):
    """Ledger header grouping charges per stay/party.

    Unified lifecycle: charges accumulate on folio lines
    (via hotel.charge.service), then generate a draft invoice
    (idempotent) -> post -> apply deposits (liability, never a
    negative revenue line) -> settle.

    Amount truth: amount_untaxed/amount_tax/amount_total are computed
    from the lines through the account.tax engine (same helpers the
    booking lines use), so folio tax always matches what settle posts.
    ``total`` is kept as an alias of amount_total for older callers
    (portal history, total_spent).
    """
    _name = 'hotel.folio'
    _description = "Hotel Folio"
    _order = 'id desc'
    _rec_name = 'name'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'avatar.mixin']

    name = fields.Char(string="Folio", default='New', copy=False,
                       index=True,
                       help="Folio reference (FOL/YYYY/ sequence).")
    partner_id = fields.Many2one('res.partner', string="Customer",
                                 required=True, tracking=True)
    booking_id = fields.Many2one('room.booking', string="Booking",
                                 help="Room booking this folio belongs to",
                                 ondelete="set null", tracking=True)
    company_id = fields.Many2one('res.company', string="Company",
                                 required=True, index=True,
                                 default=lambda self: self.env.company,
                                 compute='_compute_company', store=True,
                                 readonly=False)
    state = fields.Selection([('open', 'Open'), ('settled', 'Settled'),
                              ('void', 'Void')],
                             default='open', required=True, tracking=True)
    line_ids = fields.One2many('hotel.folio.line', 'folio_id',
                               string="Charges")
    move_id = fields.Many2one('account.move', string="Settlement Invoice",
                              readonly=True, ondelete="set null")
    ledger_id = fields.Many2one('hotel.city.ledger', string="City Ledger",
                                readonly=True, ondelete="set null")
    deposit_ids = fields.One2many('hotel.deposit', 'folio_id',
                                 string="Deposits")
    invoice_ids = fields.One2many('account.move', 'hotel_folio_id',
                                  string="Invoices")
    payment_ids = fields.One2many('account.payment', 'hotel_folio_id',
                                  string="Payments")
    notes = fields.Text(string="Notes", tracking=True,
                        help="Folio notes (chatter + Notes tab).")
    policy_snapshot = fields.Selection(
        [('prepaid', 'On Booking'), ('manual', 'On Check In'),
         ('picking', 'On Checkout')],
        string="Policy Snapshot", tracking=True,
        help="Hotel policy copied from the booking at folio creation; "
        "drives the Pay-on-Checkout banner on the statement.")
    total = fields.Float(string="Total", compute='_compute_totals',
                          store=True, tracking=True,
                          help="Gross incl. tax (alias of Amount Total).")
    amount_untaxed = fields.Float(string="Untaxed", compute='_compute_totals',
                                  store=True, tracking=True)
    amount_tax = fields.Float(string="Tax", compute='_compute_totals',
                              store=True, tracking=True)
    amount_total = fields.Float(string="Amount Total",
                                compute='_compute_totals', store=True,
                                tracking=True)
    deposit_total = fields.Float(string="Deposits", compute='_compute_totals',
                                  store=True, tracking=True)
    amount_due = fields.Float(string="Balance Due", compute='_compute_totals',
                               store=True, tracking=True)
    amount_paid = fields.Float(string="Paid", compute='_compute_totals',
                               store=True, tracking=True,
                               help="Deposits plus paid portion of posted "
                                    "folio invoices.")

    @api.depends('partner_id.name', 'partner_id.avatar_128', 'image_128')
    def _compute_avatar_128(self):
        """Show the customer letter (partner avatar) on folio cards."""
        for rec in self:
            if rec.image_128:
                rec.avatar_128 = rec.image_128
            elif rec.partner_id and rec.partner_id.avatar_128:
                rec.avatar_128 = rec.partner_id.avatar_128
            elif rec.partner_id and rec.partner_id.name:
                rec.avatar_128 = generate_text_avatar_svg(
                    rec.partner_id.name[:1].upper(), rec.partner_id.name)
            elif rec.name:
                rec.avatar_128 = generate_text_avatar_svg(
                    rec.name[:1].upper(), rec.name)
            else:
                rec.avatar_128 = False

    def _avatar_generate_svg(self):
        self.ensure_one()
        name = (self.partner_id.name if self.partner_id else None) or self.name
        if not name:
            return super()._avatar_generate_svg()
        return generate_text_avatar_svg(name[:1].upper(), name)

    @api.model_create_multi
    def create(self, vals_list):
        """Assign the FOL/YYYY/ sequence (room.booking pattern)."""
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'hotel.folio') or 'New'
        return super().create(vals_list)

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
                   'deposit_ids.amount', 'deposit_ids.state', 'state',
                   'invoice_ids.amount_total', 'invoice_ids.amount_residual',
                   'invoice_ids.state')
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
            folio.amount_paid = folio.deposit_total + sum(
                m.amount_total - m.amount_residual
                for m in folio.invoice_ids
                if m.move_type == 'out_invoice' and m.state == 'posted')
            if folio.state in ('settled', 'void'):
                folio.amount_due = 0.0
            else:
                folio.amount_due = max(
                    0.0, folio.amount_total - folio.amount_paid)

    def _ensure_sale_journal(self):
        self.ensure_one()
        journal = self.env['account.journal'].search(
            [('type', '=', 'sale'),
             ('company_id', '=', self.company_id.id)], limit=1)
        if not journal:
            raise ValidationError("No sales journal found for company %s."
                                  % self.company_id.display_name)
        return journal

    def _ensure_liability_account(self):
        self.ensure_one()
        company = self.company_id
        account = self.env['account.account'].search(
            [('account_type', '=', 'liability_current'),
             ('company_ids', 'in', company.id)], limit=1)
        if not account:
            account = self.env['account.account'].search(
                [('account_type', 'in',
                  ('liability_current', 'liability_payable',
                   'liability_non_current', 'liability_credit_card')),
                 ('company_ids', 'in', company.id)], limit=1)
        if not account:
            raise ValidationError(
                "No liability account for company %s; create one "
                "(e.g. Deferred Revenue) to hold deposits."
                % company.display_name)
        return account

    def _line_income_account(self, product, journal):
        company = self.company_id
        account = (
            product.property_account_income_id
            or product.categ_id.property_account_income_categ_id
            or journal.default_account_id
            or self.env['account.account'].search([
                ('company_ids', 'in', company.id),
                ('account_type', '=', 'income'),
            ], limit=1))
        if not account:
            raise ValidationError(
                "No income account for %s (company %s)."
                % (product.display_name, company.display_name))
        return account

    def _receivable_account(self):
        self.ensure_one()
        account = self.partner_id.property_account_receivable_id
        if account:
            return account
        account = self.env['account.account'].search(
            [('account_type', '=', 'asset_receivable'),
             ('company_ids', 'in', self.company_id.id)], limit=1)
        if not account:
            raise ValidationError(
                "No receivable account for company %s."
                % self.company_id.display_name)
        return account

    def _assert_open(self, msg="Only open folios can be invoiced."):
        """Raise unless this folio is open."""
        self.ensure_one()
        if self.state != 'open':
            raise ValidationError(msg)

    def _assert_no_posted(self, msg):
        """Raise when any linked invoice is already posted."""
        self.ensure_one()
        if self.invoice_ids.filtered(lambda m: m.state == 'posted'):
            raise ValidationError(msg)

    def action_generate_draft_invoice(self):
        """Idempotent draft invoice for uninvoiced folio lines.

        Returns the open draft if one exists; otherwise creates a draft
        from lines where invoiced_qty < quantity (empty folio yields an
        empty draft so history stays idempotent). Marks covered qty via
        invoiced_qty/locked so later drafts only pick up new charges.
        Never posts a negative revenue line.
        """
        self.ensure_one()
        if self.state == 'settled' and self.move_id:
            return self.move_id
        self._assert_open("Only open folios can be invoiced.")
        draft = self.env['account.move'].search([
            ('hotel_folio_id', '=', self.id),
            ('state', '=', 'draft'),
            ('move_type', '=', 'out_invoice'),
        ], limit=1, order='id desc')
        if draft:
            return draft
        pending = self.line_ids.filtered(
            lambda l: (l.quantity - (l.invoiced_qty or 0.0)) > 0.0)
        if not pending and self.invoice_ids:
            latest = self.env['account.move'].search(
                [('hotel_folio_id', '=', self.id),
                 ('move_type', '=', 'out_invoice')],
                limit=1, order='id desc')
            if latest:
                return latest
        journal = self._ensure_sale_journal()
        company = self.company_id
        move_lines = []
        for line in pending:
            qty = line.quantity - (line.invoiced_qty or 0.0)
            account = self._line_income_account(line.product_id, journal)
            move_lines.append((0, 0, {
                'name': line.product_id.display_name or '/',
                'product_id': line.product_id.id,
                'quantity': qty,
                'price_unit': line.price_unit,
                'account_id': account.id,
                'tax_ids': [(6, 0, line.tax_ids.ids)],
            }))
        move = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'journal_id': journal.id,
            'company_id': company.id,
            'currency_id': company.currency_id.id,
            'partner_id': self.partner_id.id,
            'hotel_folio_id': self.id,
            'hotel_booking_id': self.booking_id.id or False,
            'invoice_line_ids': move_lines,
        })
        for line in pending:
            line.write({'invoiced_qty': line.quantity, 'locked': True})
        self.message_post(
            body="Draft invoice %s generated (%d line(s))."
            % (move.name or move.id, len(move_lines)))
        return move

    def action_post_invoice(self):
        """Post the idempotent draft (generates one if missing)."""
        self.ensure_one()
        if self.state == 'settled' and self.move_id:
            return self.move_id
        self._assert_open("Only open folios can post invoices.")
        move = self.action_generate_draft_invoice()
        if move.state == 'draft':
            move.action_post()
            self.message_post(
                body="Invoice %s posted." % (move.name or move.id))
        return move

    def _linked_payments(self):
        self.ensure_one()
        domain = [('hotel_folio_id', '=', self.id)]
        if self.booking_id:
            domain = ['|', ('hotel_folio_id', '=', self.id),
                      ('hotel_booking_id', '=', self.booking_id.id)]
        return self.env['account.payment'].sudo().search(domain)

    def action_register_payment(self):
        self.ensure_one()
        moves = self.invoice_ids.filtered(
            lambda m: m.move_type == 'out_invoice' and m.state == 'posted'
            and m.payment_state != 'paid')
        if not moves:
            raise ValidationError("No unpaid posted invoice for folio %s." % self.id)
        return {
            'type': 'ir.actions.act_window',
            'name': 'Register Payment',
            'res_model': 'account.payment.register',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'active_model': 'account.move',
                'active_ids': moves.ids,
                'default_hotel_folio_id': self.id,
                'default_hotel_booking_id': self.booking_id.id or False,
            },
        }

    def action_view_payments(self):
        """Open payments linked to this folio (or its booking)."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Payments',
            'res_model': 'account.payment',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self._linked_payments().ids)],
            'context': "{'create': False}",
        }

    def action_apply_deposit(self):
        """Apply draft deposits via the liability account (no negatives).

        Interim minimum: resolves the customer-deposit liability account,
        stamps it on the deposits, flips drafts to applied. The actual
        liability reversal posts at settle time so the invoice itself
        never carries a negative revenue line. Prefer account.payment
        reconcile when feasible without breaking scope.
        """
        self.ensure_one()
        self._assert_open("Can only apply deposits to an open folio.")
        liability = self._ensure_liability_account()
        drafts = self.deposit_ids.filtered(lambda d: d.state == 'draft')
        for deposit in drafts:
            vals = {'state': 'applied'}
            if not deposit.account_id:
                vals['account_id'] = liability.id
            deposit.write(vals)
        if drafts:
            self.message_post(
                body="Deposits applied via %s: %s."
                % (liability.display_name,
                   ', '.join('%.2f' % d.amount for d in drafts)))
        return True

    def _post_deposit_reversal(self, deposit_total):
        """Dr liability / Cr receivable for applied deposits at settle."""
        self.ensure_one()
        if deposit_total <= 0:
            return False
        liability = self._ensure_liability_account()
        receivable = self._receivable_account()
        company = self.company_id
        journal = self.env['account.journal'].search(
            [('type', '=', 'general'),
             ('company_id', '=', company.id)], limit=1)
        if not journal:
            journal = self._ensure_sale_journal()
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': journal.id,
            'company_id': company.id,
            'currency_id': company.currency_id.id,
            'partner_id': self.partner_id.id,
            'ref': 'Deposit applied folio %s' % self.id,
            'line_ids': [
                (0, 0, {
                    'name': 'Deposit applied folio %s' % self.id,
                    'account_id': liability.id,
                    'partner_id': self.partner_id.id,
                    'debit': deposit_total,
                    'credit': 0.0,
                }),
                (0, 0, {
                    'name': 'Deposit applied folio %s' % self.id,
                    'account_id': receivable.id,
                    'partner_id': self.partner_id.id,
                    'debit': 0.0,
                    'credit': deposit_total,
                }),
            ],
        })
        move.action_post()
        self.deposit_ids.filtered(
            lambda d: d.state == 'applied' and not d.move_id
        ).write({'move_id': move.id, 'account_id': liability.id})
        return move

    def action_settle(self):
        """Generate draft (idempotent) -> post -> apply deposit -> settle.

        Backwards compatible: direct settle orchestrates the split steps
        so older callers (cashier, conference) keep working. Posts gross
        charge lines untouched; deposits reverse via liability, never as
        a negative revenue line. Requires a posted invoice and applied
        deposits before marking settled.
        """
        self.ensure_one()
        if self.state == 'settled' and self.move_id:
            return self.move_id
        self._assert_open("Only open folios can be settled.")
        if not self.line_ids:
            raise ValidationError("Cannot settle a folio with no charge lines.")
        gross = self.amount_total
        deposits = self.deposit_ids.filtered(
            lambda d: d.state in ('draft', 'applied'))
        deposit_total = sum(deposits.mapped('amount'))
        if deposit_total >= gross:
            raise ValidationError(
                "Deposits cover the full balance; refund instead of settling.")
        move = self.action_generate_draft_invoice()
        if move.state == 'draft':
            move.action_post()
        self.action_apply_deposit()
        if deposit_total > 0:
            self._post_deposit_reversal(deposit_total)
        expected = gross
        if abs(move.amount_total - expected) > 0.01:
            raise ValidationError(
                "Settlement mismatch: invoice %.2f != folio %.2f."
                % (move.amount_total, expected))
        self.write({'state': 'settled', 'move_id': move.id})
        self.message_post(
            body="Folio settled with invoice %s (gross %.2f, deposits %.2f)."
            % ((move.name or move.id), gross, deposit_total))
        self._accrue_loyalty_points()
        return move

    def _accrue_loyalty_points(self):
        """Auto-accrue loyalty points after settle.

        One bad program never breaks settle: failures are isolated
        per program and reported on the chatter (never swallowed).
        Accrual itself is idempotent on (program, folio).
        """
        self.ensure_one()
        programs = self.env['hotel.loyalty.program'].search([
            ('company_id', '=', self.company_id.id),
            ('active', '=', True),
        ])
        for program in programs:
            try:
                program.accrue_for_folio(self)
            except Exception as exc:
                self.message_post(
                    body="Loyalty auto-accrue failed for program %s: %s."
                    % (program.display_name, exc))

    def action_void(self):
        """Void an open folio with no posted invoices."""
        self.ensure_one()
        if self.state == 'settled':
            raise ValidationError("Settled folios cannot be voided.")
        if self.state == 'void':
            return self
        self._assert_no_posted(
            "Folio has posted invoices; cannot void.")
        for draft in self.invoice_ids.filtered(
                lambda m: m.state == 'draft'):
            draft.button_cancel()
        self.write({'state': 'void'})
        self.message_post(body="Folio voided.")
        return self
