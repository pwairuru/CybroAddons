from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestDepositCollect(TransactionCase):
    def test_collect_posts_cash_against_liability(self):
        guest = self.env['res.partner'].create({'name': 'Deposit Guest'})
        folio = self.env['hotel.folio'].create(
            {'partner_id': guest.id})
        dep = self.env['hotel.deposit'].create(
            {'folio_id': folio.id, 'amount': 5000.0})
        move = dep.action_collect()
        self.assertEqual(move.state, 'posted')
        self.assertEqual(dep.payment_move_id, move)
        self.assertEqual(move.amount_total, 5000.0)
        # Real double-entry: Dr cash-journal default / Cr liability.
        company = folio.company_id
        journal = self.env['account.journal'].search(
            [('type', 'in', ('bank', 'cash')),
             ('company_id', '=', company.id)], limit=1)
        cash_account = journal.default_account_id
        liability = folio._ensure_liability_account()
        lines = move.line_ids
        self.assertEqual(len(lines), 2)
        debit_line = lines.filtered(lambda l: l.debit > 0.0)
        credit_line = lines.filtered(lambda l: l.credit > 0.0)
        self.assertEqual(len(debit_line), 1)
        self.assertEqual(len(credit_line), 1)
        self.assertEqual(debit_line.account_id, cash_account)
        self.assertEqual(credit_line.account_id, liability)
        self.assertEqual(debit_line.debit, 5000.0)
        self.assertEqual(debit_line.credit, 0.0)
        self.assertEqual(credit_line.credit, 5000.0)
        self.assertEqual(credit_line.debit, 0.0)
        self.assertEqual(debit_line.partner_id, guest)
        self.assertEqual(credit_line.partner_id, guest)
        self.assertEqual(sum(lines.mapped('debit')),
                         sum(lines.mapped('credit')))
        with self.assertRaises(ValidationError):
            dep.action_collect()
