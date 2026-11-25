# -*- coding: utf-8 -*-
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestBookingOrigin(TransactionCase):
    def _make_booking(self, **kwargs):
        vals = {'partner_id': self.env.company.partner_id.id}
        vals.update(kwargs)
        return self.env['room.booking'].create(vals)

    def _origin(self, code):
        return self.env['room.booking.origin']._by_code(code)

    def test_default_is_reception(self):
        bk = self._make_booking()
        self.assertEqual(bk.booking_origin_id.code, 'reception')

    def test_website_persists_and_groups(self):
        bk = self._make_booking(
            booking_origin_id=self._origin('website').id)
        self.assertEqual(bk.booking_origin_id.code, 'website')
        self._make_booking()
        groups = self.env['room.booking']._read_group(
            [], ['booking_origin_id'], ['__count'])
        codes = [origin.code for origin, _count in groups]
        self.assertIn('website', codes)
        self.assertIn('reception', codes)

    def test_public_create_marks_website(self):
        svc = self.env['hotel.public.booking']
        rooms = svc.search_free('2026-12-01', '2026-12-03')
        if not rooms:
            self.skipTest('no published rooms')
        v = {'room_id': rooms[0]['id'], 'ci': '2026-12-01',
             'co': '2026-12-03', 'name': 'Web Guest',
             'phone': '+254700000002', 'idem_key': 'origin-web-1'}
        bk = svc.create_booking(v)
        self.assertEqual(bk.booking_origin_id.code, 'website')
        self.assertEqual(svc.create_booking(v).id, bk.id)

    def test_public_create_fails_without_website_origin(self):
        self._origin('website').write({'active': False})
        svc = self.env['hotel.public.booking']
        rooms = svc.search_free('2026-12-01', '2026-12-03')
        if not rooms:
            self.skipTest('no published rooms')
        v = {'room_id': rooms[0]['id'], 'ci': '2026-12-01',
             'co': '2026-12-03', 'name': 'Web Guest',
             'phone': '+254700000003', 'idem_key': 'origin-web-2'}
        with self.assertRaises(ValidationError):
            svc.create_booking(v)

    def test_origin_views_wired(self):
        tree = self.env.ref(
            'hotel_management_odoo.room_booking_view_tree').arch_db
        kanban = self.env.ref(
            'hotel_management_odoo.room_booking_view_kanban').arch_db
        search = self.env.ref(
            'hotel_management_odoo.room_booking_view_search').arch_db
        form = self.env.ref(
            'hotel_management_odoo.room_booking_view_form').arch_db
        self.assertNotIn('booking_source', tree + kanban + search + form)
        self.assertIn('booking_origin_id', form)
        self.assertIn("[('active', '=', True)]", form)
        self.assertIn("[('booking_origin_code', '=', 'website')]", search)
        self.assertIn("[('booking_origin_code', '=', 'phone')]", search)
        self.assertIn("'group_by': 'booking_origin_id'", search)
        for view_name, arch in (('tree', tree), ('kanban', kanban)):
            with self.subTest(view=view_name):
                self.assertIn('fa-globe', arch)
                self.assertIn('fa-phone', arch)
                self.assertIn(  # tooltip copy, verbatim
                    'Website booking — call to confirm/payment', arch)
                self.assertIn(  # tooltip copy, verbatim
                    'Phone booking — confirm details', arch)
        for view_name, arch, label in (
                ('search', search, 'Website'), ('search', search, 'Phone')):
            with self.subTest(view=view_name, label=label):
                self.assertIn(label, arch)

    def _load_29_migrate(self):
        import importlib.util
        from pathlib import Path
        from odoo.modules.module import get_module_path
        path = (Path(get_module_path('hotel_management_odoo'))
                / 'migrations' / '20.0.2.29.0' / 'post-migrate.py')
        spec = importlib.util.spec_from_file_location(
            'booking_origin_29_migrate', path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def _booking_source_gone(self):
        self.cr.execute(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name='room_booking' "
            "AND column_name='booking_source'")
        return self.cr.fetchone()[0] == 0

    def test_backfill_maps_and_drops_column(self):
        web = self._origin('website')
        rec = self._origin('reception')
        bk_web = self._make_booking(booking_origin_id=rec.id)
        bk_rec = self._make_booking()
        bk_other = self._make_booking()
        # Pre-upgrade shape: old varchar still present, new link
        # nullable/unfilled (ORM default fill happens at column
        # creation; NULLs are possible mid-upgrade).
        self.cr.execute(
            "ALTER TABLE room_booking ALTER COLUMN booking_origin_id "
            "DROP NOT NULL")
        self.cr.execute(
            "ALTER TABLE room_booking ADD COLUMN booking_source varchar")
        self.cr.execute(
            "UPDATE room_booking SET booking_source='website', "
            "booking_origin_id=NULL WHERE id=%s",
            (bk_web.id,))
        self.cr.execute(
            "UPDATE room_booking SET booking_source='reception', "
            "booking_origin_id=NULL WHERE id=%s",
            (bk_rec.id,))
        self.cr.execute(
            "UPDATE room_booking SET booking_source='phone', "
            "booking_origin_id=NULL WHERE id=%s",
            (bk_other.id,))
        mig = self._load_29_migrate()
        mig.migrate(self.cr, '20.0.2.29.0')
        Booking = self.env['room.booking']
        Booking.invalidate_model(['booking_origin_id'])
        self.assertEqual(
            Booking.browse(bk_web.id).booking_origin_id.code, 'website')
        self.assertEqual(
            Booking.browse(bk_rec.id).booking_origin_id.code, 'reception')
        # No evidence ever proved old phone rows: non-website maps
        # to the reception default.
        self.assertEqual(
            Booking.browse(bk_other.id).booking_origin_id.code,
            'reception')
        self.assertTrue(self._booking_source_gone())
        # Re-run idempotent: links unchanged, column stays gone.
        mig.migrate(self.cr, '20.0.2.29.0')
        Booking.invalidate_model(['booking_origin_id'])
        self.assertEqual(
            Booking.browse(bk_web.id).booking_origin_id.code, 'website')
        self.assertEqual(
            Booking.browse(bk_rec.id).booking_origin_id.code, 'reception')
        self.assertEqual(
            Booking.browse(bk_other.id).booking_origin_id.code,
            'reception')
        self.assertTrue(self._booking_source_gone())

    def _shape_pre_upgrade(self):
        # Pre-upgrade shape: old varchar still present, new link
        # nullable/unfilled (ORM default fill happens at column
        # creation; NULLs are possible mid-upgrade).
        self.cr.execute(
            "ALTER TABLE room_booking ALTER COLUMN booking_origin_id "
            "DROP NOT NULL")
        self.cr.execute(
            "ALTER TABLE room_booking ADD COLUMN booking_source varchar")

    def _make_pre_upgrade_row(self, source=None):
        bk = self._make_booking()
        self.cr.execute(
            "UPDATE room_booking SET booking_origin_id=NULL WHERE id=%s",
            (bk.id,))
        if source is not None:
            self.cr.execute(
                "UPDATE room_booking SET booking_source=%s WHERE id=%s",
                (source, bk.id))
        return bk

    def _post_chatter(self, booking):
        return self.env['mail.message'].create({
            'model': 'room.booking',
            'res_id': booking.id,
            'message_type': 'comment',
            'body': 'Booking created from website (source: public /book).',
        })

    def test_backfill_chatter_proves_website_on_direct_jump(self):
        # Direct <28→29 jump: the 28.0 varchar flagging never ran, so
        # the varchar still says reception — chatter must win.
        self._shape_pre_upgrade()
        bk = self._make_pre_upgrade_row(source='reception')
        self._post_chatter(bk)
        mig = self._load_29_migrate()
        mig.migrate(self.cr, '20.0.2.29.0')
        Booking = self.env['room.booking']
        Booking.invalidate_model(['booking_origin_id'])
        self.assertEqual(
            Booking.browse(bk.id).booking_origin_id.code, 'website')
        self.assertTrue(self._booking_source_gone())

    def test_backfill_links_archived_website(self):
        # Resolved with the same active_test=False search as the
        # ensure step: an archived website origin still links.
        web = self._origin('website')
        web.write({'active': False})
        self._shape_pre_upgrade()
        bk = self._make_pre_upgrade_row(source='website')
        mig = self._load_29_migrate()
        mig.migrate(self.cr, '20.0.2.29.0')
        Booking = self.env['room.booking']
        Booking.invalidate_model(['booking_origin_id'])
        self.assertEqual(
            Booking.browse(bk.id).booking_origin_id.id, web.id)

    def test_require_origin_raises_when_missing(self):
        mig = self._load_29_migrate()
        Origin = self.env['room.booking.origin']
        with self.assertRaises(ValueError):
            mig._require_origin(Origin, 'no-such-origin')