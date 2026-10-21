from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestFolioSplit(TransactionCase):
    def test_split_line_between_folios(self):
        folio_a = self.env['hotel.folio'].create(
            {'partner_id': self.env.company.partner_id.id})
        folio_b = self.env['hotel.folio'].create(
            {'partner_id': self.env.ref('base.public_partner').id})
        product = self.env['product.product'].search(
            [('sale_ok', '=', True)], limit=1)
        if not product:
            product = self.env['product.product'].create({
                'name': 'Test Minibar',
                'sale_ok': True,
                'list_price': 500.0,
            })
        line = self.env['hotel.charge.service'].post_charge(
            folio_a.id, product.id, 1, 500.0, 'to_guest')
        line.action_transfer(folio_b.id)
        assert line.folio_id.id == folio_b.id, "line must move to folio B"

    def test_post_charge_rejects_zero_qty(self):
        folio = self.env['hotel.folio'].create(
            {'partner_id': self.env.company.partner_id.id})
        product = self.env['product.product'].search(
            [('sale_ok', '=', True)], limit=1)
        with self.assertRaises(ValidationError):
            self.env['hotel.charge.service'].post_charge(
                folio.id, product.id, 0, 500.0, 'to_guest')

    def test_post_charge_rejects_bad_routing(self):
        folio = self.env['hotel.folio'].create(
            {'partner_id': self.env.company.partner_id.id})
        product = self.env['product.product'].search(
            [('sale_ok', '=', True)], limit=1)
        with self.assertRaises(ValidationError):
            self.env['hotel.charge.service'].post_charge(
                folio.id, product.id, 1, 500.0, 'bogus')

    def test_settle_empty_folio_raises(self):
        folio = self.env['hotel.folio'].create(
            {'partner_id': self.env.company.partner_id.id})
        with self.assertRaises(ValidationError):
            folio.action_settle()

    def test_settle_only_open(self):
        folio = self.env['hotel.folio'].create(
            {'partner_id': self.env.company.partner_id.id})
        folio.write({'state': 'settled'})
        with self.assertRaises(ValidationError):
            folio.action_settle()

    def test_transfer_logs_chatter_on_both_folios(self):
        folio_a = self.env['hotel.folio'].create(
            {'partner_id': self.env.company.partner_id.id})
        folio_b = self.env['hotel.folio'].create(
            {'partner_id': self.env.ref('base.public_partner').id})
        product = self.env['product.product'].search(
            [('sale_ok', '=', True)], limit=1)
        line = self.env['hotel.charge.service'].post_charge(
            folio_a.id, product.id, 1, 500.0, 'to_guest')
        line.action_transfer(folio_b.id)
        for folio in (folio_a, folio_b):
            bodies = ' '.join(folio.message_ids.mapped('body') or [])
            assert 'Charge moved' in bodies, "transfer must log chatter"

    def test_transfer_from_settled_source_rejected(self):
        folio_a = self.env['hotel.folio'].create(
            {'partner_id': self.env.company.partner_id.id})
        folio_b = self.env['hotel.folio'].create(
            {'partner_id': self.env.ref('base.public_partner').id})
        product = self.env['product.product'].search(
            [('sale_ok', '=', True)], limit=1)
        line = self.env['hotel.charge.service'].post_charge(
            folio_a.id, product.id, 1, 500.0, 'to_guest')
        folio_a.write({'state': 'settled'})
        with self.assertRaises(ValidationError):
            line.action_transfer(folio_b.id)

    def test_transfer_cross_company_rejected(self):
        other = self.env['res.company'].create({'name': 'Other Co Split'})
        folio_a = self.env['hotel.folio'].create(
            {'partner_id': self.env.company.partner_id.id})
        folio_b = self.env['hotel.folio'].create(
            {'partner_id': self.env.ref('base.public_partner').id,
             'company_id': other.id})
        product = self.env['product.product'].search(
            [('sale_ok', '=', True)], limit=1)
        line = self.env['hotel.charge.service'].post_charge(
            folio_a.id, product.id, 1, 500.0, 'to_guest')
        with self.assertRaises(ValidationError):
            line.action_transfer(folio_b.id)

    def test_transfer_on_closed_day_rejected(self):
        from odoo import fields
        folio_a = self.env['hotel.folio'].create(
            {'partner_id': self.env.company.partner_id.id})
        folio_b = self.env['hotel.folio'].create(
            {'partner_id': self.env.ref('base.public_partner').id})
        product = self.env['product.product'].search(
            [('sale_ok', '=', True)], limit=1)
        line = self.env['hotel.charge.service'].post_charge(
            folio_a.id, product.id, 1, 500.0, 'to_guest')
        self.env['hotel.business.date'].create({
            'date': fields.Date.today(), 'is_closed': True})
        with self.assertRaises(ValidationError):
            line.action_transfer(folio_b.id)
