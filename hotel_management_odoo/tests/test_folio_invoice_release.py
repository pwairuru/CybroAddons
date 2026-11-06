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

    def test_draft_topped_up_with_late_pos_and_service_charges(self):
        """A draft preview must not go stale.

        Charges added after draft creation (POS + service, as on a
        second checkout after reopen) must be topped up into the same
        draft so one canonical path bills everything.
        """
        folio = self._folio_with_charges()
        draft = folio.action_generate_draft_invoice()
        first_count = len(draft.invoice_line_ids)
        pos_prod = self.env['product.product'].create({
            'name': 'Late POS Charge', 'sale_ok': True,
            'type': 'service', 'list_price': 750.0})
        svc_prod = self.env['product.product'].create({
            'name': 'Late Service Charge', 'sale_ok': True,
            'type': 'service', 'list_price': 500.0})
        Svc = self.env['hotel.charge.service']
        Svc.post_charge(folio.id, pos_prod.id, 1, 750.0, 'to_guest',
                        source='pos')
        Svc.post_charge(folio.id, svc_prod.id, 2, 500.0, 'to_guest',
                        source='service')
        folio.invalidate_recordset()
        self.assertEqual(folio.amount_total, 3750.0)
        again = folio.action_generate_draft_invoice()
        self.assertEqual(again.id, draft.id,
                         "same draft must be reused, not duplicated")
        self.assertEqual(len(again.invoice_line_ids), first_count + 2)
        move = folio.action_post_invoice()
        self.assertEqual(move.id, draft.id)
        self.assertAlmostEqual(move.amount_total, folio.amount_total,
                               places=2)

    def test_checkout_posts_waiting_draft(self):
        """Checkout must post a preview draft, never skip it.

        A folio with a draft but no new pending lines still has
        something to bill; checkout posts the draft instead of
        reporting 'no uninvoiced charges'.
        """
        folio = self._folio_with_charges()
        draft = folio.action_generate_draft_invoice()
        self.assertFalse(folio._pending_lines())
        move = folio.action_post_invoice()
        self.assertEqual(move.id, draft.id)
        self.assertEqual(move.state, 'posted')
        self.assertAlmostEqual(move.amount_total, folio.amount_total,
                               places=2)
