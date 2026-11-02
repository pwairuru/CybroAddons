# -*- coding: utf-8 -*-
"""Folio invoice release (RES/2026/2085 regression).

Cancelling or deleting a non-posted folio invoice must unlock the
folio lines it covered. Otherwise a reopen + re-checkout silently
drops those charges from the regenerated invoice (lines stay
locked with stale invoiced_qty from the deleted move).
"""
from odoo.tests.common import TransactionCase


class TestFolioInvoiceRelease(TransactionCase):
    def _folio_with_charges(self):
        folio = self.env['hotel.folio'].create({
            'partner_id': self.env.company.partner_id.id})
        prod = self.env['product.product'].create({
            'name': 'Release Test Charge', 'sale_ok': True,
            'type': 'service', 'list_price': 1000.0})
        Svc = self.env['hotel.charge.service']
        Svc.post_charge(folio.id, prod.id, 1, 1000.0, 'to_guest')
        Svc.post_charge(folio.id, prod.id, 2, 500.0, 'to_guest')
        return folio

    def test_cancel_draft_invoice_unlocks_lines(self):
        folio = self._folio_with_charges()
        move = folio.action_generate_draft_invoice()
        self.assertTrue(all(folio.line_ids.mapped('locked')))
        move.button_cancel()
        self.assertFalse(any(folio.line_ids.mapped('locked')),
                         "cancelled draft must release folio line locks")
        self.assertFalse(any(folio.line_ids.mapped('invoiced_qty')),
                         "cancelled draft must reset invoiced_qty")
        again = folio.action_generate_draft_invoice()
        self.assertEqual(len(again.invoice_line_ids.filtered(
            lambda l: l.display_type not in ('line_section', 'line_note')
            and not l.is_downpayment)), 2)

    def test_unlink_draft_invoice_unlocks_lines(self):
        folio = self._folio_with_charges()
        move = folio.action_generate_draft_invoice()
        self.assertTrue(all(folio.line_ids.mapped('locked')))
        move.unlink()
        self.assertFalse(any(folio.line_ids.mapped('locked')),
                         "deleted draft must release folio line locks")
        self.assertFalse(any(folio.line_ids.mapped('invoiced_qty')),
                         "deleted draft must reset invoiced_qty")
