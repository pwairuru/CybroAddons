# tests/test_public_booking_grouping.py — pure type-grouping helper for /book.
from odoo.addons.hotel_management_odoo.controllers.public_booking import (
    _group_rooms_by_type,
)
from odoo.tests.common import TransactionCase


class TestPublicBookingGrouping(TransactionCase):
    def test_groups_by_type_with_count_and_cheapest_rep(self):
        rows = [
            {'id': 1, 'type_id': 10, 'type': 'Deluxe', 'nightly': 30000.0, 'total': 60000.0,
             'nightly_str': 'KES 30,000', 'total_str': 'KES 60,000', 'name': 'D-101',
             'image_url': '/book/room-image/1', 'adult_capacity': 2, 'max_occupants': 3, 'amenities': ['Pool']},
            {'id': 2, 'type_id': 10, 'type': 'Deluxe', 'nightly': 25000.0, 'total': 50000.0,
             'nightly_str': 'KES 25,000', 'total_str': 'KES 50,000', 'name': 'D-102',
             'image_url': '/book/room-image/2', 'adult_capacity': 2, 'max_occupants': 3, 'amenities': ['Pool']},
            {'id': 3, 'type_id': 20, 'type': 'Suite', 'nightly': 50000.0, 'total': 100000.0,
             'nightly_str': 'KES 50,000', 'total_str': 'KES 100,000', 'name': 'S-201',
             'image_url': '/book/room-image/3', 'adult_capacity': 2, 'max_occupants': 4, 'amenities': []},
        ]
        grouped = _group_rooms_by_type(rows)
        self.assertEqual(len(grouped), 2)
        deluxe = [g for g in grouped if g['type'] == 'Deluxe'][0]
        self.assertEqual(deluxe['count'], 2)
        self.assertEqual(deluxe['rep_id'], 2)
        self.assertEqual(deluxe['nightly'], 25000.0)

    def test_missing_type_id_falls_back_to_name(self):
        rows = [
            {'id': 5, 'type_id': False, 'type': 'Cabin', 'nightly': 10000.0, 'total': 20000.0,
             'nightly_str': 'KES 10,000', 'total_str': 'KES 20,000', 'name': 'C-1',
             'image_url': '', 'adult_capacity': 2, 'max_occupants': 2, 'amenities': []},
        ]
        grouped = _group_rooms_by_type(rows)
        self.assertEqual(len(grouped), 1)
        self.assertEqual(grouped[0]['count'], 1)

    def test_empty_free_list_groups_to_empty(self):
        self.assertEqual(_group_rooms_by_type([]), [])

    def test_tie_break_lowest_id_wins(self):
        rows = [
            {'id': 9, 'type_id': 10, 'type': 'Deluxe', 'nightly': 25000.0, 'total': 50000.0,
             'nightly_str': 'KES 25,000', 'total_str': 'KES 50,000', 'name': 'D-109',
             'image_url': '/book/room-image/9', 'adult_capacity': 2, 'max_occupants': 3, 'amenities': []},
            {'id': 7, 'type_id': 10, 'type': 'Deluxe', 'nightly': 25000.0, 'total': 50000.0,
             'nightly_str': 'KES 25,000', 'total_str': 'KES 50,000', 'name': 'D-107',
             'image_url': '/book/room-image/7', 'adult_capacity': 2, 'max_occupants': 3, 'amenities': []},
        ]
        grouped = _group_rooms_by_type(rows)
        self.assertEqual(len(grouped), 1)
        self.assertEqual(grouped[0]['rep_id'], 7)
        self.assertEqual(grouped[0]['rep_name'], 'D-107')

    def test_output_keys_and_sort_by_nightly(self):
        rows = [
            {'id': 3, 'type_id': 20, 'type': 'Suite', 'nightly': 50000.0, 'total': 100000.0,
             'nightly_str': 'KES 50,000', 'total_str': 'KES 100,000', 'name': 'S-201',
             'image_url': '/book/room-image/3', 'adult_capacity': 2, 'max_occupants': 4, 'amenities': []},
            {'id': 2, 'type_id': 10, 'type': 'Deluxe', 'nightly': 25000.0, 'total': 50000.0,
             'nightly_str': 'KES 25,000', 'total_str': 'KES 50,000', 'name': 'D-102',
             'image_url': '/book/room-image/2', 'adult_capacity': 2, 'max_occupants': 3, 'amenities': ['Pool']},
        ]
        grouped = _group_rooms_by_type(rows)
        self.assertEqual([g['type'] for g in grouped], ['Deluxe', 'Suite'])
        for g in grouped:
            self.assertEqual(
                sorted(g.keys()),
                sorted(['type_id', 'type', 'count', 'rep_id', 'rep_name',
                        'nightly', 'total', 'nightly_str', 'total_str',
                        'image_url', 'adult_capacity', 'max_occupants',
                        'amenities']))
        deluxe = grouped[0]
        self.assertEqual(deluxe['type_id'], 10)
        self.assertEqual(deluxe['image_url'], '/book/room-image/2')
        self.assertEqual(deluxe['amenities'], ['Pool'])
