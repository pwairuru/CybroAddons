from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestConference(TransactionCase):
    def setUp(self):
        super().setUp()
        self.hall_a = self.env['hotel.venue'].create({
            'name': 'Hall A',
            'capacity': 200,
            'flat_price': 50000.0,
            'pax_price': 2500.0,
        })
        self.company_partner = self.env.company.partner_id
        self.guest = self.env.ref('base.public_partner')
        product = self.env['product.product'].search(
            [('sale_ok', '=', True)], limit=1)
        if not product:
            product = self.env['product.product'].create({
                'name': 'Test Conf Product',
                'sale_ok': True,
                'list_price': 1000.0,
            })
        self.product = product

    def test_venue_no_double_book(self):
        self.env['hotel.conference'].create({
            'venue_id': self.hall_a.id, 'date': '2026-11-01',
            'slot': 'full'})
        with self.assertRaises(ValidationError):
            self.env['hotel.conference'].create({
                'venue_id': self.hall_a.id, 'date': '2026-11-01',
                'slot': 'half_am'})

    def test_half_am_half_pm_same_day_allowed(self):
        self.env['hotel.conference'].create({
            'venue_id': self.hall_a.id, 'date': '2026-11-02',
            'slot': 'half_am'})
        self.env['hotel.conference'].create({
            'venue_id': self.hall_a.id, 'date': '2026-11-02',
            'slot': 'half_pm'})

    def test_half_am_double_book_rejected(self):
        self.env['hotel.conference'].create({
            'venue_id': self.hall_a.id, 'date': '2026-11-03',
            'slot': 'half_am'})
        with self.assertRaises(ValidationError):
            self.env['hotel.conference'].create({
                'venue_id': self.hall_a.id, 'date': '2026-11-03',
                'slot': 'half_am'})

    def test_package_explosion_posts_master_lines(self):
        conf = self.env['hotel.conference'].create({
            'venue_id': self.hall_a.id, 'date': '2026-11-04',
            'slot': 'full', 'partner_id': self.company_partner.id,
            'pax': 10})
        conf.action_confirm()
        master = conf.master_folio_id
        self.assertTrue(master.id, "confirm must create a master folio")
        routings = set(master.line_ids.mapped('routing'))
        self.assertEqual(routings, {'to_master'},
                         "package lines must route to_master")
        self.assertEqual(len(master.line_ids), 2,
                         "venue flat + pax lines expected")

    def test_personal_extra_routed_to_personal(self):
        conf = self.env['hotel.conference'].create({
            'venue_id': self.hall_a.id, 'date': '2026-11-05',
            'slot': 'full', 'partner_id': self.company_partner.id,
            'pax': 5})
        conf.action_confirm()
        att = conf.add_attendee(self.guest.id)
        line = conf.post_personal_extra(att.id, self.product.id, 1, 800.0)
        self.assertEqual(line.routing, 'to_personal')
        self.assertEqual(line.folio_id.id, att.personal_folio_id.id)
        self.assertNotEqual(att.personal_folio_id.id,
                            conf.master_folio_id.id,
                            "personal folio must differ from master")

    def test_settle_master_returns_move(self):
        conf = self.env['hotel.conference'].create({
            'venue_id': self.hall_a.id, 'date': '2026-11-06',
            'slot': 'full', 'partner_id': self.company_partner.id,
            'pax': 2})
        conf.action_confirm()
        move = conf.action_settle_master()
        self.assertTrue(move.id, "settle must return an account.move")
        self.assertEqual(conf.master_folio_id.state, 'settled')

    def test_confirm_done_rejected(self):
        conf = self.env['hotel.conference'].create({
            'venue_id': self.hall_a.id, 'date': '2026-11-08',
            'slot': 'full', 'partner_id': self.company_partner.id})
        conf.write({'state': 'done'})
        with self.assertRaises(ValidationError):
            conf.action_confirm()

    def test_confirm_cancelled_rejected(self):
        conf = self.env['hotel.conference'].create({
            'venue_id': self.hall_a.id, 'date': '2026-11-09',
            'slot': 'full', 'partner_id': self.company_partner.id})
        conf.action_cancel()
        with self.assertRaises(ValidationError):
            conf.action_confirm()

    def test_add_attendee_cancelled_rejected(self):
        conf = self.env['hotel.conference'].create({
            'venue_id': self.hall_a.id, 'date': '2026-11-10',
            'slot': 'full', 'partner_id': self.company_partner.id})
        conf.action_cancel()
        with self.assertRaises(ValidationError):
            conf.add_attendee(self.guest.id)

    def test_add_attendee_done_rejected(self):
        conf = self.env['hotel.conference'].create({
            'venue_id': self.hall_a.id, 'date': '2026-11-11',
            'slot': 'full', 'partner_id': self.company_partner.id})
        conf.write({'state': 'done'})
        with self.assertRaises(ValidationError):
            conf.add_attendee(self.guest.id)

    def test_add_attendee_duplicate_rejected(self):
        conf = self.env['hotel.conference'].create({
            'venue_id': self.hall_a.id, 'date': '2026-11-12',
            'slot': 'full', 'partner_id': self.company_partner.id})
        conf.add_attendee(self.guest.id)
        with self.assertRaises(ValidationError):
            conf.add_attendee(self.guest.id)

    def test_add_attendee_over_capacity_rejected(self):
        small = self.env['hotel.venue'].create({
            'name': 'Booth', 'capacity': 1,
            'flat_price': 5000.0, 'pax_price': 500.0})
        conf = self.env['hotel.conference'].create({
            'venue_id': small.id, 'date': '2026-11-13',
            'slot': 'full', 'partner_id': self.company_partner.id,
            'pax': 1})
        conf.add_attendee(self.guest.id)
        with self.assertRaises(ValidationError):
            conf.add_attendee(self.company_partner.id)

    def test_add_attendee_over_pax_rejected(self):
        conf = self.env['hotel.conference'].create({
            'venue_id': self.hall_a.id, 'date': '2026-11-14',
            'slot': 'full', 'partner_id': self.company_partner.id,
            'pax': 1})
        conf.add_attendee(self.guest.id)
        with self.assertRaises(ValidationError):
            conf.add_attendee(self.company_partner.id)

    def test_pos_bill_to_read_only(self):
        conf = self.env['hotel.conference'].create({
            'venue_id': self.hall_a.id, 'date': '2026-11-07',
            'slot': 'full', 'partner_id': self.company_partner.id})
        partner = conf.resolve_pos_bill_to(None)
        self.assertFalse(partner, "unknown POS ref resolves to falsy")
