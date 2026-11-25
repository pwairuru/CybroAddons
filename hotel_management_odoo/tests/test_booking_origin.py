# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase


class TestBookingOrigin(TransactionCase):
    def _make_booking(self, **kwargs):
        vals = {'partner_id': self.env.company.partner_id.id}
        vals.update(kwargs)
        return self.env['room.booking'].create(vals)

    def test_default_is_reception(self):
        bk = self._make_booking()
        self.assertEqual(bk.booking_source, 'reception')

    def test_website_persists_and_groups(self):
        bk = self._make_booking(booking_source='website')
        self.assertEqual(bk.booking_source, 'website')
        self._make_booking()
        groups = self.env['room.booking']._read_group(
            [], ['booking_source'], ['__count'])
        sources = [source for source, _count in groups]
        self.assertIn('website', sources)
        self.assertIn('reception', sources)
