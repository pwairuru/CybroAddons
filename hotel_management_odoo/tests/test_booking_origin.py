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

    def test_public_create_marks_website(self):
        svc = self.env['hotel.public.booking']
        rooms = svc.search_free('2026-12-01', '2026-12-03')
        if not rooms:
            self.skipTest('no published rooms')
        v = {'room_id': rooms[0]['id'], 'ci': '2026-12-01',
             'co': '2026-12-03', 'name': 'Web Guest',
             'phone': '+254700000002', 'idem_key': 'origin-web-1'}
        bk = svc.create_booking(v)
        self.assertEqual(bk.booking_source, 'website')
        self.assertEqual(svc.create_booking(v).id, bk.id)

    def test_origin_views_wired(self):
        tree = self.env.ref(
            'hotel_management_odoo.room_booking_view_tree').arch_db
        kanban = self.env.ref(
            'hotel_management_odoo.room_booking_view_kanban').arch_db
        search = self.env.ref(
            'hotel_management_odoo.room_booking_view_search').arch_db
        form = self.env.ref(
            'hotel_management_odoo.room_booking_view_form').arch_db
        self.assertIn('booking_source', tree + kanban + search + form)
        self.assertIn('group_by', search)
        for view_name, arch in (('tree', tree), ('kanban', kanban)):
            with self.subTest(view=view_name):
                self.assertIn('fa-globe', arch)
                self.assertIn('Website booking', arch)  # tooltip copy
