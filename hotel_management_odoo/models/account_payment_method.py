# -*- coding: utf-8 -*-
import logging

from odoo import api, models

_logger = logging.getLogger(__name__)


class AccountPaymentMethodLine(models.Model):
    _inherit = 'account.payment.method.line'

    @api.model
    def _fill_missing_payment_accounts(self):
        """Fill outstanding accounts on bank/cash method lines lacking one.

        Root cause (C1): the Manual/Checks payment method lines on the
        Bank and Cash Restaurant journals had ``payment_account_id``
        unset, so ``outstanding_account_id`` was False and pay-wizard
        payments posted with ``move_id`` False (no journal entry).
        Inbound lines take the chart's outstanding-receipts account,
        outbound lines the outstanding-payments account. Lines that
        already have an account are never touched, so this is safe to
        run on every module upgrade.
        """
        missing = self.search([
            ('payment_account_id', '=', False),
            ('journal_id.type', 'in', ('bank', 'cash', 'credit')),
        ])
        if not missing:
            return 0
        filled = 0
        for company in missing.mapped('company_id'):
            co_env = self.with_company(company)
            inbound_acc = co_env.env['account.chart.template'].ref(
                'account_journal_payment_debit_account_id',
                raise_if_not_found=False) or company.transfer_account_id
            outbound_acc = co_env.env['account.chart.template'].ref(
                'account_journal_payment_credit_account_id',
                raise_if_not_found=False) or company.transfer_account_id
            for line in missing.filtered(
                    lambda l: l.company_id.id == company.id
                    and l.payment_type == 'inbound'):
                if inbound_acc:
                    line.payment_account_id = inbound_acc.id
                    filled += 1
            for line in missing.filtered(
                    lambda l: l.company_id.id == company.id
                    and l.payment_type != 'inbound'):
                if outbound_acc:
                    line.payment_account_id = outbound_acc.id
                    filled += 1
        _logger.info("Filled outstanding accounts on %d payment method "
                     "line(s).", filled)
        return filled
