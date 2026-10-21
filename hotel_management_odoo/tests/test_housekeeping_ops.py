# -*- coding: utf-8 -*-
"""Task 10: housekeeping pro + linen/lost&found/complaints/wakeup + staff/assets.

Failing-first: dirty->clean->inspected->OOO, SLA breach, QR asset.
"""
from odoo.tests.common import TransactionCase


class TestHousekeepingOps(TransactionCase):
    def setUp(self):
        super().setUp()
        self.room_101 = self.env['product.template'].create({
            'name': 'HK-101',
            'is_room': True,
            'room_type': 'single',
            'num_person': 1,
            'list_price': 10000.0,
        })
        self.team = self.env['cleaning.team'].create({
            'name': 'HK Team',
            'team_head_id': self.env.ref('base.user_admin').id,
        })
        self.user = self.env.ref('base.user_admin')

    def _request(self, **kw):
        vals = {
            'cleaning_type': 'room',
            'room_id': self.room_101.id,
            'team_id': self.team.id,
            'assigned_id': self.user.id,
            'task_type': 'departure',
        }
        vals.update(kw)
        return self.env['cleaning.request'].create(vals)

    def test_dirty_to_clean_to_inspected(self):
        req = self._request(room_status='dirty')
        req.action_mark_clean()
        assert req.room_status == 'clean', "dirty must go clean, got %s" % req.room_status
        req.action_inspect()
        assert req.room_status == 'inspected', "clean must go inspected, got %s" % req.room_status

    def test_inspect_requires_clean(self):
        from odoo.exceptions import ValidationError
        req = self._request(room_status='dirty')
        with self.assertRaises(ValidationError):
            req.action_inspect()

    def test_ooo_transition(self):
        req = self._request(room_status='dirty')
        req.action_mark_ooo()
        assert req.room_status == 'ooo', "must go OOO, got %s" % req.room_status
        assert req.state == 'done', "OOO closes the request"

    def test_departure_vs_stayover_types(self):
        dep = self._request(task_type='departure')
        stay = self._request(task_type='stayover')
        assert dep.task_type == 'departure'
        assert stay.task_type == 'stayover'

    def test_sla_breach_flagged(self):
        req = self._request(sla_deadline='2020-01-01 00:00:00')
        assert req.sla_breach is True, "overdue open request must breach SLA"

    def test_sla_no_breach_when_done(self):
        req = self._request(sla_deadline='2020-01-01 00:00:00')
        req.action_mark_clean()
        req.action_inspect()
        req.action_done_cleaning()
        assert req.sla_breach is False, "done request must not breach"

    def test_linen_issue_return(self):
        ltype = self.env['hotel.linen.type'].create({'name': 'Sheet'})
        move = self.env['hotel.linen.move'].create({
            'linen_type_id': ltype.id,
            'room_id': self.room_101.id,
            'qty': 2,
            'direction': 'issue',
        })
        assert move.qty == 2
        move.action_return()
        assert move.state == 'returned'

    def test_linen_qty_guard(self):
        from odoo.exceptions import ValidationError
        ltype = self.env['hotel.linen.type'].create({'name': 'Towel'})
        with self.assertRaises(ValidationError):
            self.env['hotel.linen.move'].create({
                'linen_type_id': ltype.id,
                'room_id': self.room_101.id,
                'qty': 0,
                'direction': 'issue',
            })

    def test_lost_found_flow(self):
        item = self.env['hotel.lost.found'].create({
            'name': 'Wallet',
            'room_id': self.room_101.id,
            'description': 'Black wallet',
        })
        assert item.state == 'found'
        item.action_claim()
        assert item.state == 'claimed'
        item.action_return()
        assert item.state == 'returned'

    def test_complaint_sla(self):
        comp = self.env['hotel.complaint'].create({
            'name': 'No hot water',
            'room_id': self.room_101.id,
            'sla_deadline': '2020-01-01 00:00:00',
        })
        assert comp.sla_breach is True, "overdue open complaint must breach"
        comp.action_resolve()
        assert comp.state == 'resolved'
        assert comp.sla_breach is False

    def test_wakeup_schedule_done(self):
        from odoo.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            self.env['hotel.wakeup.call'].create({
                'room_id': self.room_101.id,
                'wake_time': '2020-01-01 06:00:00',
            })
        call = self.env['hotel.wakeup.call'].create({
            'room_id': self.room_101.id,
            'wake_time': '2030-01-01 06:00:00',
        })
        assert call.state == 'scheduled'
        call.action_done()
        assert call.state == 'done'

    def test_roster_handover(self):
        roster = self.env['hotel.staff.roster'].create({
            'roster_date': '2026-10-19',
            'shift': 'morning',
            'user_id': self.user.id,
            'team_id': self.team.id,
        })
        handover = self.env['hotel.shift.handover'].create({
            'roster_id': roster.id,
            'notes': 'Room 101 needs inspection',
        })
        assert handover.roster_id.id == roster.id
        handover.action_confirm()
        assert handover.state == 'confirmed'

    def test_asset_qr_tracked(self):
        asset = self.env['hotel.asset'].create({
            'name': 'Vacuum V1',
            'qr_code': 'QR-VAC-001',
            'room_id': self.room_101.id,
        })
        found = self.env['hotel.asset'].track_by_qr('QR-VAC-001')
        assert found.id == asset.id, "QR lookup must return the asset"
        assert found.room_id.id == self.room_101.id

    def test_asset_qr_unique_per_company(self):
        from odoo.exceptions import ValidationError
        self.env['hotel.asset'].create({
            'name': 'Vacuum V1',
            'qr_code': 'QR-DUP-001',
        })
        with self.assertRaises(ValidationError):
            self.env['hotel.asset'].create({
                'name': 'Vacuum V2',
                'qr_code': 'QR-DUP-001',
            })

    def test_asset_qr_whitespace_normalized(self):
        from odoo.exceptions import ValidationError
        asset = self.env['hotel.asset'].create({
            'name': 'Mop M1',
            'qr_code': '  QR-MOP-002  ',
        })
        assert asset.qr_code == 'QR-MOP-002', \
            "QR must be stored stripped, got %r" % asset.qr_code
        found = self.env['hotel.asset'].track_by_qr('QR-MOP-002')
        assert found.id == asset.id
        with self.assertRaises(ValidationError):
            self.env['hotel.asset'].create({
                'name': 'Mop M2',
                'qr_code': 'QR-MOP-002',
            })

    def test_asset_qr_write_normalized(self):
        asset = self.env['hotel.asset'].create({
            'name': 'Bucket B1',
            'qr_code': 'QR-BKT-003',
        })
        asset.write({'qr_code': '  QR-BKT-003B  '})
        assert asset.qr_code == 'QR-BKT-003B', \
            "QR write must strip, got %r" % asset.qr_code
        assert self.env['hotel.asset'].track_by_qr('QR-BKT-003B').id == asset.id

    def test_linen_soiled_blocked(self):
        from odoo.exceptions import ValidationError
        ltype = self.env['hotel.linen.type'].create({'name': 'Blanket'})
        move = self.env['hotel.linen.move'].create({
            'linen_type_id': ltype.id,
            'room_id': self.room_101.id,
            'qty': 1,
            'direction': 'soiled',
        })
        with self.assertRaises(ValidationError):
            move.action_issue()
        with self.assertRaises(ValidationError):
            move.action_return()
        assert move.direction == 'soiled', \
            "blocked actions must not clobber soiled, got %s" % move.direction

    def test_dispose_guards(self):
        from odoo.exceptions import ValidationError
        item = self.env['hotel.lost.found'].create({
            'name': 'Watch',
            'room_id': self.room_101.id,
        })
        item.action_dispose()
        assert item.state == 'disposed'
        with self.assertRaises(ValidationError):
            item.action_dispose()
        item2 = self.env['hotel.lost.found'].create({
            'name': 'Ring',
            'room_id': self.room_101.id,
        })
        item2.action_claim()
        item2.action_return()
        with self.assertRaises(ValidationError):
            item2.action_dispose()
