# -*- coding: utf-8 -*-
"""Capacity label pins (Task 1: model string=/help=).

Label-only change: no enforcement logic, no rename, no migration.
Task 2 extends this file with view-arch assertions.
"""
from odoo.tests.common import TransactionCase


class TestCapacityLabels(TransactionCase):
    def test_capacity_label_strings(self):
        self.assertEqual(self.env['product.template'].fields_get(['num_person'])['num_person']['string'], 'Room Capacity (hard cap)')
        self.assertEqual(self.env['hotel.room.type'].fields_get(['max_occupants'])['max_occupants']['string'], 'Type Max Occupants (hard cap)')
        self.assertEqual(self.env['hotel.rate.line'].fields_get(['included_adults'])['included_adults']['string'], 'Price Covers Adults')
        self.assertEqual(self.env['hotel.room.type'].fields_get(['adult_capacity'])['adult_capacity']['string'], 'Std Adults (display default)')
        self.assertEqual(self.env['hotel.room.type'].fields_get(['child_capacity'])['child_capacity']['string'], 'Std Children (display default)')
        self.assertEqual(self.env['hotel.rate.line'].fields_get(['included_children'])['included_children']['string'], 'Price Covers Children')

    def test_capacity_label_helps(self):
        num_help = self.env['product.template'].fields_get(['num_person'])['num_person']['help']
        self.assertIn('website', num_help.lower())
        self.assertIn('type max', num_help.lower())
        adult_help = self.env['hotel.room.type'].fields_get(['adult_capacity'])['adult_capacity']['help']
        self.assertIn('not enforced', adult_help.lower())
        child_help = self.env['hotel.room.type'].fields_get(['child_capacity'])['child_capacity']['help']
        self.assertIn('not enforced', child_help.lower())
        max_help = self.env['hotel.room.type'].fields_get(['max_occupants'])['max_occupants']['help']
        self.assertIn('hard', max_help.lower())
        self.assertIn('booking', max_help.lower())
        self.assertIn('pricing', max_help.lower())
        incl_help = self.env['hotel.rate.line'].fields_get(['included_adults'])['included_adults']['help']
        self.assertIn('extra', incl_help.lower())
        incl_child_help = self.env['hotel.rate.line'].fields_get(['included_children'])['included_children']['help']
        self.assertIn('extra', incl_child_help.lower())

    def test_standard_heads_hidden_from_views(self):
        views = self.env['ir.ui.view'].search([('model', '=', 'hotel.room.type')])
        for v in views:
            self.assertNotIn('standard_heads', v.arch or '')
