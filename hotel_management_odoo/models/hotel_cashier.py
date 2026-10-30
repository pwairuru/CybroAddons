# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class HotelDeposit(models.Model):
    """Advance payment linked to a folio, deducted at settle time."""
    _name = 'hotel.deposit'
    _description = "Hotel Deposit"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    folio_id = fields.Many2one('hotel.folio', string="Folio",
                               required=True, ondelete="cascade", index=True,
                               tracking=True)
    amount = fields.Float(string="Amount", required=True, tracking=True)
    state = fields.Selection(
        [('draft', 'Draft'), ('applied', 'Applied'),
         ('cancelled', 'Cancelled'), ('refunded', 'Refunded')],
        default='draft', required=True, tracking=True)
    company_id = fields.Many2one('res.company', string="Company",
                                 required=True, index=True,
                                 default=lambda self: self.env.company)
    account_id = fields.Many2one('account.account',
                                 string="Liability Account",
                                 ondelete="restrict",
                                 tracking=True,
                                 help="Customer-deposit liability account "
                                 "(interim: liability, reversed at settle).")
    move_id = fields.Many2one('account.move', string="Liability Entry",
                              readonly=True, ondelete="set null",
                              help="Liability reversal entry posted at "
                              "settle time.")
    payment_move_id = fields.Many2one('account.move', string="Payment Entry",
                                       readonly=True, ondelete="set null",
                                       copy=False,
                                       tracking=True,
                                       help="Cash receipt posted at collect "
                                       "time (Dr cash / Cr liability).")
    reversal_move_id = fields.Many2one('account.move', string="Reversal Entry",
                                       readonly=True, ondelete="set null",
                                       copy=False,
                                       help="Reversal posted by Refund.")

    @api.constrains('amount')
    def _check_amount(self):
        for rec in self:
            if rec.amount <= 0:
                raise ValidationError("Deposit amount must be positive.")

    def action_collect(self):
        """Post the cash receipt for this deposit (Dr cash / Cr liability).

        Requires draft state, no prior collection, and an open folio in
        the current company. Resolves the cash account from the first
        bank/cash journal default account and the liability account via
        the folio (same lookup as settle). Returns the posted move.
        """
        self.ensure_one()
        if self.state != 'draft':
            raise ValidationError("Only draft deposits can be collected.")
        if self.payment_move_id:
            raise ValidationError(
                "Deposit already collected (move %s)."
                % (self.payment_move_id.name or self.payment_move_id.id))
        folio = self.folio_id
        if folio.company_id.id != self.env.company.id:
            raise ValidationError(
                "Deposit belongs to %s; collect from that company."
                % folio.company_id.display_name)
        if folio.state != 'open':
            raise ValidationError(
                "Can only collect deposits for an open folio.")
        company = folio.company_id
        journal = self.env['account.journal'].search(
            [('type', 'in', ('bank', 'cash')),
             ('company_id', '=', company.id)], limit=1)
        cash_account = journal.default_account_id if journal else False
        if not cash_account:
            raise ValidationError(
                "No cash/bank journal with a default account for "
                "company %s; configure one to collect deposits."
                % company.display_name)
        liability = folio._ensure_liability_account()
        ref = 'Deposit folio %s' % folio.id
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': journal.id,
            'company_id': company.id,
            'currency_id': company.currency_id.id,
            'partner_id': folio.partner_id.id,
            'ref': ref,
            'line_ids': [
                (0, 0, {
                    'name': ref,
                    'account_id': cash_account.id,
                    'partner_id': folio.partner_id.id,
                    'debit': self.amount,
                    'credit': 0.0,
                }),
                (0, 0, {
                    'name': ref,
                    'account_id': liability.id,
                    'partner_id': folio.partner_id.id,
                    'debit': 0.0,
                    'credit': self.amount,
                }),
            ],
        })
        move.action_post()
        self.write({'payment_move_id': move.id})
        folio.message_post(
            body="Deposit collected: %.2f (move %s)."
            % (self.amount, move.name or move.id))
        return move

    def action_cancel_draft(self):
        self.ensure_one()
        if self.state != 'draft':
            raise ValidationError("Only draft deposits can be cancelled.")
        if self.payment_move_id:
            raise ValidationError(
                "Deposit already collected; use Refund instead.")
        self.write({'state': 'cancelled'})
        self.folio_id.message_post(
            body="Deposit %.2f cancelled." % self.amount)
        return True

    def action_refund(self, reason=None):
        self.ensure_one()
        if not self.payment_move_id:
            raise ValidationError("Nothing collected; cancel instead.")
        if self.state == 'refunded':
            return self.reversal_move_id or self.payment_move_id
        rev = self.payment_move_id._reverse_moves(
            default_values_list=[{'ref': 'Deposit refund folio %s' % self.folio_id.id}])
        rev.action_post()
        self.write({'state': 'refunded', 'reversal_move_id': rev.id})
        msg = ("Deposit %.2f refunded (%s)."
               % (self.amount, rev.name or rev.id))
        if reason:
            msg += " Reason: %s" % reason
        self.folio_id.message_post(body=msg)
        return rev

    def apply(self):
        """Mark this deposit applied against its folio."""
        self.ensure_one()
        if self.state != 'draft':
            raise ValidationError("Only draft deposits can be applied.")
        folio_company = self.folio_id.company_id
        if folio_company.id != self.env.company.id:
            raise ValidationError(
                "Deposit belongs to %s; apply from that company."
                % folio_company.display_name)
        if self.folio_id.state != 'open':
            raise ValidationError("Can only apply deposits to an open folio.")
        self.write({'state': 'applied'})
        return self


class HotelCityLedger(models.Model):
    """City-ledger (direct-bill AR) entry a folio balance is transferred to."""
    _name = 'hotel.city.ledger'
    _description = "Hotel City Ledger"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    partner_id = fields.Many2one('res.partner', string="Customer",
                                 required=True, index=True, tracking=True)
    folio_id = fields.Many2one('hotel.folio', string="Folio",
                               required=True, ondelete="restrict", index=True,
                               tracking=True)
    amount = fields.Float(string="Amount", required=True, tracking=True)
    state = fields.Selection([('open', 'Open'), ('paid', 'Paid')],
                             default='open', required=True, tracking=True)
    transfer_date = fields.Date(string="Transfer Date", required=True,
                                default=fields.Date.today, tracking=True)
    due_date = fields.Date(string="Due Date", tracking=True)
    age_days = fields.Integer(string="Age (days)",
                              compute='_compute_age_days', store=True)
    company_id = fields.Many2one('res.company', string="Company",
                                 required=True, index=True,
                                 default=lambda self: self.env.company)

    @api.depends('transfer_date')
    def _compute_age_days(self):
        today = fields.Date.today()
        for rec in self:
            base = rec.transfer_date or today
            rec.age_days = max(0, (today - base).days)

    @api.model
    def transfer(self, folio_id):
        """Move an open folio's balance into the city ledger.

        Draft deposits block the transfer (settle them first); the
        ledger always carries the exact folio balance, never a mix of
        linked deposits.
        """
        folio = self.env['hotel.folio'].browse(folio_id)
        if not folio.exists():
            raise ValidationError("Folio %s does not exist." % folio_id)
        folio_company = folio.company_id
        if folio_company.id != self.env.company.id:
            raise ValidationError(
                "Folio belongs to %s; transfer from that company."
                % folio_company.display_name)
        if folio.state != 'open':
            raise ValidationError("Can only transfer an open folio.")
        if not folio.line_ids:
            raise ValidationError("Cannot transfer a folio with no charges.")
        if self.search_count([('folio_id', '=', folio.id),
                               ('state', '=', 'open')]):
            raise ValidationError("Folio %s is already in the city ledger."
                                  % folio_id)
        # Block while any deposits sit unconsumed (draft OR manually
        # applied on the still-open folio). Operator settles the deposits
        # first (settle consumes them), then transfers the net balance.
        # Blocking applied too closes the apply-then-transfer hole where
        # amount_due still showed gross and the ledger over-transferred.
        if folio.deposit_ids.filtered(
                lambda d: d.state in ('draft', 'applied')):
            raise ValidationError(
                "Folio %s has unapplied deposits; "
                "settle deposits first." % folio_id)
        amount = folio.amount_due
        if amount <= 0:
            raise ValidationError("Folio %s has no balance to transfer."
                                  % folio_id)
        today = fields.Date.today()
        ledger = self.create({
            'partner_id': folio.partner_id.id,
            'folio_id': folio.id,
            'amount': amount,
            'company_id': folio_company.id,
            'transfer_date': today,
            'due_date': fields.Date.add(today, days=30),
        })
        folio.write({'state': 'settled', 'ledger_id': ledger.id})
        return ledger


class HotelCashierShift(models.Model):
    """Cashier shift with open/close and cash variance tracking."""
    _name = 'hotel.cashier.shift'
    _description = "Hotel Cashier Shift"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    user_id = fields.Many2one('res.users', string="Cashier",
                              default=lambda self: self.env.user,
                              required=True, index=True, tracking=True)
    company_id = fields.Many2one('res.company', string="Company",
                                 required=True, index=True,
                                 default=lambda self: self.env.company)
    state = fields.Selection([('draft', 'Draft'), ('open', 'Open'),
                              ('closed', 'Closed')],
                             default='draft', required=True, tracking=True)
    opening_cash = fields.Float(string="Opening Cash", default=0.0,
                                tracking=True)
    expected_cash = fields.Float(string="Expected Cash", default=0.0,
                                 tracking=True)
    closing_cash = fields.Float(string="Closing Cash", default=0.0,
                                tracking=True)
    variance = fields.Float(string="Variance",
                            compute='_compute_variance', store=True,
                            tracking=True)
    opened_at = fields.Datetime(string="Opened At", readonly=True,
                                tracking=True)
    closed_at = fields.Datetime(string="Closed At", readonly=True,
                                tracking=True)

    @api.constrains('opening_cash', 'expected_cash', 'closing_cash')
    def _check_cash(self):
        for rec in self:
            if (rec.opening_cash < 0 or rec.expected_cash < 0
                    or rec.closing_cash < 0):
                raise ValidationError("Cash amounts cannot be negative.")

    @api.depends('closing_cash', 'expected_cash')
    def _compute_variance(self):
        for rec in self:
            rec.variance = rec.closing_cash - rec.expected_cash

    def _check_company(self):
        if self.company_id.id != self.env.company.id:
            raise ValidationError(
                "Shift belongs to %s; operate from that company."
                % self.company_id.display_name)

    def action_open(self):
        self.ensure_one()
        if self.state != 'draft':
            raise ValidationError("Only draft shifts can be opened.")
        self._check_company()
        open_count = self.search_count(
            [('user_id', '=', self.user_id.id),
             ('company_id', '=', self.company_id.id),
             ('state', '=', 'open')])
        if open_count:
            raise ValidationError(
                "User %s already has an open shift; close it first."
                % self.user_id.display_name)
        self.write({'state': 'open',
                    'opened_at': fields.Datetime.now()})
        return self

    def close(self, closing_cash=None):
        """Close the shift; variance = closing - expected."""
        self.ensure_one()
        if self.state != 'open':
            raise ValidationError("Only open shifts can be closed.")
        self._check_company()
        closing = self.closing_cash if closing_cash is None else closing_cash
        if closing < 0:
            raise ValidationError("Closing cash cannot be negative.")
        self.write({'closing_cash': closing, 'state': 'closed',
                    'closed_at': fields.Datetime.now()})
        return True
