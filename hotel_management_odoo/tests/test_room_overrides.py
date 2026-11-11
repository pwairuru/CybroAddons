# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase


class TestRoomOverrides(TransactionCase):
    def _make_room(self, name='Override Room'):
        return self.env['product.template'].create({
            'name': name, 'is_room': True,
            'num_person': 2, 'list_price': 10000.0})

    def test_website_excluded_hides_published_type(self):
        rtype = self.env['hotel.room.type'].create({
            'name': 'Web Type', 'website_published': True})
        room = self._make_room()
        room.room_type_id = rtype.id
        self.assertTrue(room.website_published)
        room.website_excluded = True
        self.assertFalse(room.website_published)

    def test_website_unpublished_type_stays_hidden(self):
        rtype = self.env['hotel.room.type'].create({
            'name': 'Dark Type', 'website_published': False})
        room = self._make_room()
        room.room_type_id = rtype.id
        self.assertFalse(room.website_published)

    def test_manager_override_beats_floor(self):
        mgr_floor = self.env['res.users'].create({
            'name': 'Floor Mgr', 'login': 'floor_mgr_ovr'})
        mgr_over = self.env['res.users'].create({
            'name': 'Over Mgr', 'login': 'over_mgr_ovr'})
        floor = self.env['hotel.floor'].create({
            'name': 'Ovr Floor', 'user_id': mgr_floor.id})
        room = self._make_room()
        room.floor_id = floor.id
        self.assertEqual(room.user_id, mgr_floor)
        room.manager_override_id = mgr_over.id
        self.assertEqual(room.user_id, mgr_over)
