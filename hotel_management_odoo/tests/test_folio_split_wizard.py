# -*- coding: utf-8 -*-
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestFolioSplitWizard(TransactionCase):
    def _mk_folio_with_lines(self, partner, n=2, price=50.0):
        folio = self.env['hotel.folio'].create({'partner_id': partner.id})
        prod = self.env['product.product'].search([], limit=1)
        Svc = self.env['hotel.charge.service']
        lines = Svc.env['hotel.folio.line'].browse()
        for i in range(n):
            lines |= Svc.post_charge(
                folio.id, prod.id, 1 + i, price + 10.0 * i)
        return folio, lines

    def test_split_to_new_folio(self):
        a = self.env['res.partner'].create({'name': 'Split A'})
        b = self.env['res.partner'].create({'name': 'Split B'})
        folio = self.env['hotel.folio'].create({'partner_id': a.id})
        prod = self.env['product.product'].search([], limit=1)
        Svc = self.env['hotel.charge.service']
        l1 = Svc.post_charge(folio.id, prod.id, 1, 100.0)
        l2 = Svc.post_charge(folio.id, prod.id, 2, 50.0)
        wiz = self.env['hotel.folio.split'].with_context(
            active_id=folio.id, active_model='hotel.folio').create(
                {'target_mode': 'new', 'new_partner_id': b.id,
                 'line_ids': [(6, 0, [l2.id])]})
        action = wiz.action_split()
        self.assertIsInstance(action, dict)
        self.assertEqual(action.get('res_model'), 'hotel.folio')
        target = self.env['hotel.folio'].browse(action.get('res_id'))
        self.assertTrue(target.exists())
        self.assertEqual(target.partner_id, b)
        self.assertEqual(l2.folio_id, target)
        self.assertEqual(l1.folio_id, folio)

    def test_split_to_existing_folio(self):
        a = self.env['res.partner'].create({'name': 'Split Exist A'})
        folio, lines = self._mk_folio_with_lines(a, n=2)
        target = self.env['hotel.folio'].create({'partner_id': a.id})
        moving = lines[:1]
        wiz = self.env['hotel.folio.split'].with_context(
            active_id=folio.id, active_model='hotel.folio').create(
                {'target_mode': 'existing',
                 'target_folio_id': target.id,
                 'line_ids': [(6, 0, moving.ids)]})
        action = wiz.action_split()
        self.assertIsInstance(action, dict)
        self.assertEqual(action.get('res_id'), target.id)
        moving.invalidate_recordset()
        self.assertEqual(moving.folio_id, target)
        self.assertEqual(
            (folio.line_ids - moving).folio_id, folio)

    def test_same_target_rejected(self):
        a = self.env['res.partner'].create({'name': 'Split Same A'})
        folio, lines = self._mk_folio_with_lines(a, n=1)
        wiz = self.env['hotel.folio.split'].with_context(
            active_id=folio.id, active_model='hotel.folio').create(
                {'target_mode': 'existing',
                 'target_folio_id': folio.id,
                 'line_ids': [(6, 0, lines.ids)]})
        with self.assertRaises(ValidationError):
            wiz.action_split()

    def test_closed_source_rejected(self):
        a = self.env['res.partner'].create({'name': 'Split Closed A'})
        b = self.env['res.partner'].create({'name': 'Split Closed B'})
        folio, lines = self._mk_folio_with_lines(a, n=1)
        folio.write({'state': 'settled'})
        wiz = self.env['hotel.folio.split'].with_context(
            active_id=folio.id, active_model='hotel.folio').create(
                {'target_mode': 'new', 'new_partner_id': b.id,
                 'line_ids': [(6, 0, lines.ids)]})
        with self.assertRaises(ValidationError):
            wiz.action_split()
