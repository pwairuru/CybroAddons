# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class HotelDepositWizard(models.TransientModel):
    """One-click Take Deposit: amount + journal, done.

    Confirm creates the deposit, collects it as a real inbound
    payment, and applies it (reversing against a posted invoice at
    once). The full hotel.deposit form stays for corrections and
    edge cases; reception never needs the 3-step path.
    """
    _name = 'hotel.deposit.wizard'
    _description = 'Take Deposit'

    folio_id = fields.Many2one('hotel.folio', string="Folio",
                               required=True, readonly=True)
    amount = fields.Float(string="Amount", required=True)
    journal_id = fields.Many2one(
        'account.journal', string="Received In",
        domain=[('type', 'in', ('bank', 'cash'))], required=True)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        folio = False
        if res.get('folio_id'):
            folio = self.env['hotel.folio'].browse(res['folio_id'])
        elif self.env.context.get('default_folio_id'):
            folio = self.env['hotel.folio'].browse(
                self.env.context['default_folio_id'])
        if folio and folio.exists():
            if 'amount' in fields_list and not res.get('amount'):
                res['amount'] = folio.amount_due or 0.0
            if 'journal_id' in fields_list and not res.get('journal_id'):
                journal = self.env['account.journal'].search(
                    [('type', 'in', ('bank', 'cash')),
                     ('company_id', '=', folio.company_id.id)], limit=1)
                if journal:
                    res['journal_id'] = journal.id
        return res

    def action_confirm(self):
        """Create, collect and apply in one step; show the deposit."""
        self.ensure_one()
        if self.amount <= 0:
            raise ValidationError("Deposit amount must be positive.")
        if self.folio_id.state != 'open':
            raise ValidationError(
                "Can only take deposits for an open folio.")
        deposit = self.env['hotel.deposit'].create({
            'folio_id': self.folio_id.id,
            'amount': self.amount,
        })
        deposit.action_collect(journal=self.journal_id)
        deposit.apply()
        self.folio_id.message_post(
            body="Deposit taken via quick dialog: %.2f (%s)."
            % (self.amount, self.journal_id.display_name))
        return {
            'type': 'ir.actions.act_window',
            'name': 'Deposit',
            'res_model': 'hotel.deposit',
            'view_mode': 'form',
            'res_id': deposit.id,
            'target': 'current',
        }
