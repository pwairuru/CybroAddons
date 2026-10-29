# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase


class TestMultiRoomSnapshot(TransactionCase):
    def test_snapshot_fields_exist(self):
        f = self.env['room.booking.line']._fields
        self.assertIn('rate_line_id', f)
