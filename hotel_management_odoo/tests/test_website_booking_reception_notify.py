# addons/CybroAddons/hotel_management_odoo/tests/test_website_booking_reception_notify.py
from odoo.tests.common import TransactionCase, tagged


@tagged('reception_notify')
class TestWebsiteBookingReceptionNotify(TransactionCase):
    def _reception_user(self, login):
        group = self.env.ref('hotel_management_odoo.hotel_group_reception')
        internal = self.env.ref('base.group_user')
        user = self.env['res.users'].create({
            'name': login, 'login': login,
            # Odoo 20: without base.group_user the user computes as
            # share (portal) and is rightly excluded from notify targets.
            'group_ids': [(6, 0, [internal.id, group.id])],
        })
        self.assertTrue(user.partner_id)
        self.assertFalse(user.share)
        return user

    def _free_room_vals(self):
        svc = self.env['hotel.public.booking']
        rooms = svc.search_free('2026-12-01', '2026-12-03')
        if not rooms:
            self.skipTest('no published rooms')
        return rooms[0]['id']

    def test_website_booking_notifies_reception_bell(self):
        svc = self.env['hotel.public.booking']
        group = self.env.ref('hotel_management_odoo.hotel_group_reception')
        baseline = set(group.all_user_ids.ids)
        u1 = self._reception_user('recept_notify_1')
        u2 = self._reception_user('recept_notify_2')
        outsider = self.env['res.users'].create({'name': 'Out', 'login': 'recept_outsider'})
        room_id = self._free_room_vals()
        bk = svc.create_booking({'room_id': room_id, 'ci': '2026-12-01', 'co': '2026-12-03',
            'name': 'Web Guest', 'phone': '+254799000101', 'idem_key': 'notify-bell-1'})
        acts = self.env['mail.activity'].search([('res_model', '=', 'room.booking'), ('res_id', '=', bk.id)])
        self.assertTrue(acts)
        notified_uids = set(acts.mapped('user_id.id'))
        self.assertTrue({u1.id, u2.id} <= notified_uids)
        self.assertNotIn(outsider.id, notified_uids)
        # no strangers beyond pre-existing members + our two
        self.assertTrue(notified_uids <= baseline | {u1.id, u2.id})
        msg = self.env['mail.message'].search([('model', '=', 'room.booking'), ('res_id', '=', bk.id)], order='id desc', limit=1)
        notified = msg.notification_ids.mapped('res_partner_id.id') if msg else []
        # fallback: notified partner ids on message
        partners = set(msg.notified_partner_ids.ids) if msg and 'notified_partner_ids' in msg._fields else set(notified)
        self.assertTrue({u1.partner_id.id, u2.partner_id.id} <= partners)
        self.assertNotIn(outsider.partner_id.id, partners)

    def test_idem_retry_does_not_double_notify(self):
        svc = self.env['hotel.public.booking']
        self._reception_user('recept_notify_3')
        room_id = self._free_room_vals()
        v = {'room_id': room_id, 'ci': '2026-12-01', 'co': '2026-12-03',
             'name': 'Web Guest', 'phone': '+254799000102', 'idem_key': 'notify-bell-2'}
        b1 = svc.create_booking(dict(v))
        n1 = self.env['mail.activity'].search_count([('res_model', '=', 'room.booking'), ('res_id', '=', b1.id)])
        b2 = svc.create_booking(dict(v))
        self.assertEqual(b1.id, b2.id)
        n2 = self.env['mail.activity'].search_count([('res_model', '=', 'room.booking'), ('res_id', '=', b1.id)])
        self.assertEqual(n1, n2)

    def test_empty_reception_never_blocks_booking(self):
        svc = self.env['hotel.public.booking']
        group = self.env.ref('hotel_management_odoo.hotel_group_reception')
        # Odoo 20: roster is direct members (group.user_ids). Strip the
        # group itself plus every implying group (manager/admin imply
        # reception; the computed all_user_ids inverse forbids clearing
        # implied rows, so strip instead). Then assert the skip branch:
        # booking succeeds AND zero activities are scheduled on it.
        for u in group.all_user_ids:
            u.group_ids -= group.all_implied_by_ids + group
        self.assertFalse(group.user_ids)
        room_id = self._free_room_vals()
        bk = svc.create_booking({'room_id': room_id, 'ci': '2026-12-01', 'co': '2026-12-03',
            'name': 'Web Guest', 'phone': '+254799000103', 'idem_key': 'notify-bell-3'})
        self.assertTrue(bk.exists())
        self.assertFalse(self.env['mail.activity'].search(
            [('res_model', '=', 'room.booking'), ('res_id', '=', bk.id)], limit=1))

    def test_share_and_inactive_excluded(self):
        svc = self.env['hotel.public.booking']
        group = self.env.ref('hotel_management_odoo.hotel_group_reception')
        portal = self.env['res.users'].create({'name': 'Port', 'login': 'recept_portal',
            'group_ids': [(6, 0, [group.id])], 'share': True})
        gone = self._reception_user('recept_gone')
        gone.active = False
        keep = self._reception_user('recept_keep')
        room_id = self._free_room_vals()
        bk = svc.create_booking({'room_id': room_id, 'ci': '2026-12-01', 'co': '2026-12-03',
            'name': 'Web Guest', 'phone': '+254799000104', 'idem_key': 'notify-bell-4'})
        uids = set(self.env['mail.activity'].search(
            [('res_model', '=', 'room.booking'), ('res_id', '=', bk.id)]).mapped('user_id.id'))
        self.assertIn(keep.id, uids)
        self.assertNotIn(portal.id, uids)
        self.assertNotIn(gone.id, uids)

    def test_backend_booking_does_not_notify(self):
        group = self.env.ref('hotel_management_odoo.hotel_group_reception')
        u = self.env['res.users'].create({'name': 'R', 'login': 'recept_back',
            'group_ids': [(6, 0, [group.id])]})
        bk = self.env['room.booking'].create({
            'partner_id': self.env['res.partner'].create({'name': 'Walk'}).id,
            'checkin_date': '2026-12-01 14:00:00', 'checkout_date': '2026-12-03 11:00:00',
        })
        acts = self.env['mail.activity'].search([('res_model', '=', 'room.booking'), ('res_id', '=', bk.id)])
        self.assertNotIn(u.id, acts.mapped('user_id.id'))

    def test_draft_still_notifies(self):
        svc = self.env['hotel.public.booking']
        self.env.company.public_auto_confirm = False
        self._reception_user('recept_draft')
        room_id = self._free_room_vals()
        bk = svc.create_booking({'room_id': room_id, 'ci': '2026-12-01', 'co': '2026-12-03',
            'name': 'Web Guest', 'phone': '+254799000105', 'idem_key': 'notify-bell-5'})
        self.assertEqual(bk.state, 'draft')
        self.assertTrue(self.env['mail.activity'].search(
            [('res_model', '=', 'room.booking'), ('res_id', '=', bk.id)], limit=1))
