# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase


class TestKanbanAvatar(TransactionCase):
    """avatar.mixin letter+color fallback for imageless kanban cards."""

    def _assert_letter_avatar(self, record):
        avatar = record.avatar_128
        self.assertTrue(avatar, '%s has no avatar' % record._name)
        self.assertIn(b'svg', bytes(avatar).lower())

    def test_booking_avatar(self):
        guest = self.env['res.partner'].create({'name': 'Avatar Guest'})
        room = self.env['product.template'].create({
            'name': 'Avatar Room', 'is_room': True,
            'num_person': 2, 'list_price': 10000.0})
        bk = self.env['room.booking'].create({
            'partner_id': guest.id,
            'room_line_ids': [(0, 0, {'room_id': room.id,
                                      'checkin_date': '2026-11-01 14:00:00',
                                      'checkout_date': '2026-11-02 11:00:00'})]})
        self._assert_letter_avatar(bk)

    def test_folio_avatar(self):
        folio = self.env['hotel.folio'].create({
            'partner_id': self.env['res.partner'].create(
                {'name': 'Avatar Folio Guest'}).id})
        self._assert_letter_avatar(folio)

    def test_room_avatar_without_upload(self):
        room = self.env['product.template'].create({
            'name': 'Avatar Only Room', 'is_room': True,
            'num_person': 2, 'list_price': 10000.0})
        self.assertFalse(room.image_1920)
        self._assert_letter_avatar(room)

    def test_room_type_and_amenity_avatar(self):
        rtype = self.env['hotel.room.type'].create({
            'name': 'Avatar Type', 'company_id': self.env.company.id})
        self._assert_letter_avatar(rtype)
        amenity = self.env['hotel.amenity'].create({'name': 'Avatar Amen'})
        self._assert_letter_avatar(amenity)

    def test_team_avatars(self):
        cteam = self.env['cleaning.team'].create({'name': 'Avatar CTeam'})
        self._assert_letter_avatar(cteam)
        mteam = self.env['maintenance.team'].create({'name': 'Avatar MTeam'})
        self._assert_letter_avatar(mteam)
