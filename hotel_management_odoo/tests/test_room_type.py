# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase


class TestRoomType(TransactionCase):
    def test_type_link_and_price_authority(self):
        rtype = self.env['hotel.room.type'].create({
            'name': 'Deluxe', 'code': 'DLX',
            'adult_capacity': 2, 'child_capacity': 1,
            'max_occupants': 3, 'base_rate': 12000.0,
            'website_published': True,
        })
        room = self.env['product.template'].create({
            'name': '101', 'is_room': True, 'room_type': 'double',
            'num_person': 2, 'list_price': 8000.0,
            'room_type_id': rtype.id,
        })
        self.assertEqual(room.room_type_id.base_rate, 12000.0)
        self.assertTrue(rtype.website_published)
