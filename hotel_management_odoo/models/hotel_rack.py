# -*- coding: utf-8 -*-
"""Rack availability + dashboard tiles (Task 4).

Computed-only layer over existing models — no new tables, no config menus.
Consumes bookings (room.booking.line) + OOO (maintenance.request type room,
not done/cancel) + dirty (cleaning.request room, not done).

Produces:
- rack JSON: [{room_id, room_name, date, status, booking_id}]
  status in {available, reserved, occupied, dirty, ooo}
  priority: ooo > occupied > reserved > dirty > available
- tiles: {occupancy, adr, revpar, arrivals, departures, dirty, ...}
"""
from datetime import datetime, timedelta, timezone

from odoo import api, fields, models
from odoo.exceptions import ValidationError

from .hotel_business_date import _nights

_RACK_STATUSES = ('available', 'reserved', 'occupied', 'dirty',
                   'ooo', 'conflict')
_DISPLAY = {
    'available': 'Available',
    'reserved': 'Reserved',
    'occupied': 'In-House',
    'dirty': 'Dirty',
    'ooo': 'OOO',
    'conflict': 'Conflict',
}


def _to_date(value):
    # NOTE: kept local on purpose — business-date _to_date maps falsy
    # input to today, while rack needs None for missing line dates
    # (callers skip when ci/co are falsy). Import _nights only.
    if not value:
        return None
    if isinstance(value, str):
        return fields.Date.from_string(value)
    from datetime import datetime
    if isinstance(value, datetime):
        return value.date()
    return value


class HotelDailyInventory(models.AbstractModel):
    """Computed availability. OWL tape-chart reads it, no new table."""
    _name = 'hotel.daily.inventory'
    _description = "Hotel Daily Inventory (computed)"

    @api.model
    def _rooms(self):
        return self.env['product.template'].with_company(
            self.env.company).search(
                [('is_room', '=', True),
                 '|', ('company_id', '=', False),
                 ('company_id', '=', self.env.company.id)],
                order='name')

    @api.model
    def _ooo_room_ids(self):
        # Canonical OOO helper: open room-maintenance requests.
        # Company-scoped so rate/channel reuse stays correct.
        reqs = self.env['maintenance.request'].search([
            ('type', '=', 'room'),
            ('company_id', '=', self.env.company.id),
            ('state', 'not in', ('done', 'cancel')),
        ])
        ids = set()
        for req in reqs:
            ids.update(req.room_maintenance_ids.ids)
        return ids

    @api.model
    def _dirty_room_ids(self):
        # Task 10: clean/inspected rooms are sellable-ready, not dirty.
        # Legacy rows (room_status False) still count until migrated.
        reqs = self.env['cleaning.request'].search([
            ('cleaning_type', '=', 'room'),
            ('company_id', '=', self.env.company.id),
            ('state', 'not in', ('done',)),
            ('room_id', '!=', False),
            '|',
            ('room_status', '=', False),
            ('room_status', 'not in', ('clean', 'inspected')),
        ])
        return set(reqs.mapped('room_id.id'))

    @api.model
    def get_rack(self, date_from=None, date_to=None, days=7):
        """Rack JSON for [date_from, date_to]. Defaults to today + days."""
        today = fields.Date.context_today(self)
        start = fields.Date.from_string(date_from) if date_from else today
        if date_to:
            end = fields.Date.from_string(date_to)
        else:
            end = start + timedelta(days=max(int(days or 7) - 1, 0))
        if end < start:
            raise ValidationError(
                _("Rack end date (%s) is before start (%s).")
                % (end, start))
        if (end - start).days > 31:
            end = start + timedelta(days=31)
        rooms = self._rooms()
        ooo_ids = self._ooo_room_ids()
        dirty_ids = self._dirty_room_ids()
        # UTC day bounds: datetimes are stored naive-UTC; server-local
        # midnight shifts occupancy at TZ edges, so build UTC bounds.
        window_start_dt = fields.Datetime.to_string(
            datetime.combine(start, datetime.min.time()).replace(
                tzinfo=timezone.utc).replace(tzinfo=None))
        window_end_dt = fields.Datetime.to_string(
            datetime.combine(end, datetime.max.time()).replace(
                tzinfo=timezone.utc).replace(tzinfo=None))
        lines = self.env['room.booking.line'].search([
            ('booking_id.company_id', '=', self.env.company.id),
            ('booking_id.state', 'in', ('reserved', 'check_in')),
            ('checkin_date', '<', window_end),
            ('checkout_date', '>', window_start),
        ])
        # Per-day status resolution (line sets small; python loop fine).
        cells = []
        day = start
        while day <= end:
            day_str = fields.Date.to_string(day)
            for room in rooms:
                status = 'available'
                booking_id = False
                if room.id in ooo_ids:
                    status = 'ooo'
                else:
                    hits = []
                    for line in lines:
                        if line.room_id.id != room.id:
                            continue
                        ci = _to_date(line.checkin_date)
                        co = _to_date(line.checkout_date)
                        if ci and co and ci <= day < co:
                            hits.append(line)
                    live = [ln for ln in hits
                            if ln.booking_id.state == 'check_in']
                    upcoming = [ln for ln in hits
                                if ln.booking_id.state == 'reserved']
                    if len(live) > 1 or (live and upcoming):
                        status = 'conflict'
                        booking_id = live[0].booking_id.id
                    elif live:
                        status = 'occupied'
                        booking_id = live[0].booking_id.id
                    elif len(upcoming) > 1:
                        status = 'conflict'
                        booking_id = upcoming[0].booking_id.id
                    elif upcoming:
                        status = 'reserved'
                        booking_id = upcoming[0].booking_id.id
                    if status == 'available' and room.id in dirty_ids:
                        status = 'dirty'
                cells.append({
                    'room_id': room.id,
                    'room_name': room.name,
                    'date': day_str,
                    'status': status,
                    'display': _DISPLAY[status],
                    'booking_id': booking_id,
                })
            day += timedelta(days=1)
        return {
            'date_from': fields.Date.to_string(start),
            'date_to': fields.Date.to_string(end),
            'statuses': list(_RACK_STATUSES),
            'cells': cells,
        }

    @api.model
    def get_tiles(self, hotel_date=None):
        """Dashboard tiles for one business day (default today)."""
        today = fields.Date.from_string(hotel_date) if hotel_date else fields.Date.context_today(self)
        day_str = fields.Date.to_string(today)
        rooms = self._rooms()
        total = len(rooms)
        ooo_ids = self._ooo_room_ids()
        # Dirty excludes OOO: an out-of-order room is not sellable, so it must
        # not inflate the dirty count either.
        dirty_ids = self._dirty_room_ids() - ooo_ids
        ooo_room_ids = ooo_ids & set(rooms.ids)
        sellable = max(total - len(ooo_room_ids), 0)

        day_start = fields.Datetime.to_string(
            datetime.combine(today, datetime.min.time()))
        day_end = fields.Datetime.to_string(
            datetime.combine(today + timedelta(days=1),
                             datetime.min.time()))
        lines = self.env['room.booking.line'].search([
            ('booking_id.company_id', '=', self.env.company.id),
            ('booking_id.state', 'in',
             ('reserved', 'check_in', 'check_out', 'done')),
            ('checkin_date', '<', day_end),
            ('checkout_date', '>', day_start),
        ])
        occupied_ids, reserved_ids = set(), set()
        revenue = 0.0
        target_currency = self.env.company.currency_id
        for line in lines:
            ci = _to_date(line.checkin_date)
            co = _to_date(line.checkout_date)
            if not (ci and co):
                continue
            if ci <= today < co:
                nightly = (line.price_total or 0.0) / (_nights(ci, co) or 1)
                # Lines price in the booking pricelist currency; tiles
                # report in company currency, so convert per line.
                line_currency = line.currency_id or target_currency
                nightly = line_currency._convert(
                    nightly, target_currency,
                    line.company_id or self.env.company, today)
                if line.booking_id.state == 'check_in':
                    occupied_ids.add(line.room_id.id)
                    revenue += nightly
                elif line.booking_id.state == 'reserved':
                    reserved_ids.add(line.room_id.id)
        # Arrivals: lines starting today, any non-cancelled state —
        # a stay checked out (or settled) today still arrived today.
        arrivals = sum(
            1 for line in lines
            if _to_date(line.checkin_date) == today
            and line.booking_id.state in (
                'reserved', 'check_in', 'check_out', 'done'))
        # Departures: lines ending today (in-house or already checked out).
        departures = sum(
            1 for line in lines
            if _to_date(line.checkout_date) == today
            and line.booking_id.state in ('check_in', 'check_out'))
        occupied = len(occupied_ids)
        occupancy = round(100.0 * occupied / sellable, 1) if sellable else 0.0
        adr = round(revenue / occupied, 2) if occupied else 0.0
        revpar = round(revenue / sellable, 2) if sellable else 0.0
        open_folios = self.env['hotel.folio'].search_count([
            ('company_id', '=', self.env.company.id),
            ('state', '=', 'open'),
        ])
        return {
            'date': day_str,
            'total_rooms': total,
            'sellable_rooms': sellable,
            'occupied': occupied,
            'reserved': len(reserved_ids),
            'occupancy': occupancy,
            'adr': adr,
            'revpar': revpar,
            'arrivals': arrivals,
            'departures': departures,
            'dirty': len(dirty_ids),
            'ooo': len(ooo_room_ids),
            'room_revenue': round(revenue, 2),
            'currency_symbol': self.env.company.currency_id.symbol,
            'open_folios': open_folios,
        }

    @api.model
    def get_dashboard_series(self, date_from=None, days=14):
        """POS-style sparkline series for [start, start+days).

        One scan of room.booking.line for the window, then per-day
        occupancy/arrivals/departures/revenue math (same nightly-split
        rules as get_tiles). Read-only.
        """
        days = min(max(int(days or 14), 1), 28)
        today = fields.Date.context_today(self)
        start = fields.Date.from_string(date_from) if date_from else today
        end = start + timedelta(days=days)
        rooms = self._rooms()
        total = len(rooms)
        ooo_ids = self._ooo_room_ids()
        ooo_room_ids = ooo_ids & set(rooms.ids)
        sellable = max(total - len(ooo_room_ids), 0)
        target_currency = self.env.company.currency_id
        window_start = fields.Datetime.to_string(
            datetime.combine(start, datetime.min.time()))
        window_end = fields.Datetime.to_string(
            datetime.combine(end, datetime.min.time()))
        lines = self.env['room.booking.line'].search([
            ('booking_id.company_id', '=', self.env.company.id),
            ('booking_id.state', 'in',
             ('reserved', 'check_in', 'check_out', 'done')),
            ('checkin_date', '<', window_end),
            ('checkout_date', '>', window_start),
        ])
        # Food orders per booking check-in day (same window/state filter).
        food_per_day = {}
        for fl in self.env['food.booking.line'].search([
                ('booking_id.company_id', '=', self.env.company.id),
                ('booking_id.state', 'in',
                 ('reserved', 'check_in', 'check_out', 'done')),
        ]):
            ci = _to_date(fl.booking_id.checkin_date)
            if ci and start <= ci < end:
                key = fields.Date.to_string(ci)
                food_per_day[key] = food_per_day.get(key, 0) + 1
        dates = [fields.Date.to_string(start + timedelta(days=i))
                 for i in range(days)]
        occupancy, arrivals, departures = [], [], []
        room_revenue, adr_list, revpar_list, available = [], [], [], []
        food_orders = []
        for i in range(days):
            day = start + timedelta(days=i)
            occupied_ids = set()
            revenue = 0.0
            arr = dep = 0
            for line in lines:
                ci = _to_date(line.checkin_date)
                co = _to_date(line.checkout_date)
                if not (ci and co):
                    continue
                state = line.booking_id.state
                if ci == day and state in (
                        'reserved', 'check_in', 'check_out', 'done'):
                    arr += 1
                if co == day and state in ('check_in', 'check_out'):
                    dep += 1
                if ci <= day < co and state == 'check_in':
                    occupied_ids.add(line.room_id.id)
                    nightly = (line.price_total or 0.0) / (_nights(ci, co) or 1)
                    line_currency = line.currency_id or target_currency
                    revenue += line_currency._convert(
                        nightly, target_currency,
                        line.company_id or self.env.company, day)
            occupied = len(occupied_ids)
            occ_pct = round(100.0 * occupied / sellable, 1) if sellable else 0.0
            adr = round(revenue / occupied, 2) if occupied else 0.0
            revpar = round(revenue / sellable, 2) if sellable else 0.0
            occupancy.append(occ_pct)
            arrivals.append(arr)
            departures.append(dep)
            room_revenue.append(round(revenue, 2))
            adr_list.append(adr)
            revpar_list.append(revpar)
            available.append(max(sellable - occupied, 0))
            food_orders.append(food_per_day.get(
                fields.Date.to_string(day), 0))
        return {
            'date_from': fields.Date.to_string(start),
            'days': days,
            'dates': dates,
            'occupancy': occupancy,
            'arrivals': arrivals,
            'departures': departures,
            'room_revenue': room_revenue,
            'adr': adr_list,
            'revpar': revpar_list,
            'available': available,
            'food_orders': food_orders,
            'sellable_rooms': sellable,
            'total_rooms': total,
            'currency_symbol': target_currency.symbol,
        }

    @api.model
    def get_tape(self, date_from=None, days=14):
        """Tape-chart payload for [start, start+days). Read-only."""
        days = min(max(int(days or 14), 1), 28)
        today = fields.Date.context_today(self)
        start = fields.Date.from_string(date_from) if date_from else today
        end = start + timedelta(days=days)
        rooms = self._rooms()
        ooo_ids = self._ooo_room_ids()
        dirty_ids = self._dirty_room_ids()
        floor_names = {f.id: f.name for f in self.env['hotel.floor'].search([])}
        type_labels = dict(
            self.env['product.template'].fields_get(['room_type'])['room_type']['selection'])
        room_rows = [{
            'id': r.id, 'name': r.name,
            'floor_id': r.floor_id.id or False,
            'floor_name': r.floor_id.name or 'No Floor',
            'floor_seq': r.floor_id.id and 0 or 1,
            'room_type': r.room_type or False,
            'room_type_label': type_labels.get(r.room_type, r.room_type or ''),
            'hk_status': 'ooo' if r.id in ooo_ids else (
                'dirty' if r.id in dirty_ids else 'clean'),
            'is_ooo': r.id in ooo_ids,
        } for r in rooms]
        room_rows.sort(key=lambda x: (x['floor_id'] or 9999, x['name']))
        if floor_names:
            seq = {fid: i for i, fid in
                   enumerate(self.env['hotel.floor'].search([], order='id').ids)}
            for row in room_rows:
                row['floor_seq'] = seq.get(row['floor_id'], 9999)
            room_rows.sort(key=lambda x: (x['floor_seq'], x['name']))
        window_start = fields.Datetime.to_string(
            datetime.combine(start, datetime.min.time()))
        window_end = fields.Datetime.to_string(
            datetime.combine(end, datetime.min.time()))
        lines = self.env['room.booking.line'].search([
            ('booking_id.company_id', '=', self.env.company.id),
            ('booking_id.state', 'in', ('reserved', 'check_in')),
            ('checkin_date', '<', window_end),
            ('checkout_date', '>', window_start),
        ])
        segments = []
        for line in lines:
            ci = _to_date(line.checkin_date)
            co = _to_date(line.checkout_date)
            if not (ci and co):
                continue
            seg_from = max(ci, start)
            seg_to = min(co, end)
            if seg_from >= seg_to:
                continue
            bk = line.booking_id
            segments.append({
                'id': line.id, 'booking_id': bk.id,
                'booking_name': bk.name,
                'room_id': line.room_id.id,
                'date_from': fields.Date.to_string(seg_from),
                'date_to': fields.Date.to_string(seg_to),
                'state': bk.state,
                'guest_name': bk.partner_id.name or '',
                'is_arrival': seg_from == ci and start <= ci < end,
                'is_departure': seg_to == co and start < co <= end,
            })
        dates = [fields.Date.to_string(start + timedelta(days=i))
                 for i in range(days)]
        in_house = {}
        reserved_house = {}
        for line in lines:
            ci = _to_date(line.checkin_date)
            co = _to_date(line.checkout_date)
            if not (ci and co):
                continue
            for i in range(days):
                day = start + timedelta(days=i)
                if ci <= day < co:
                    key = fields.Date.to_string(day)
                    if line.booking_id.state == 'check_in':
                        in_house.setdefault(key, set()).add(
                            line.room_id.id)
                    elif line.booking_id.state == 'reserved':
                        reserved_house.setdefault(key, set()).add(
                            line.room_id.id)
        sellable = max(len(rooms) - len(ooo_ids & set(rooms.ids)), 0)
        occupancy = {}
        for d in dates:
            sold = len(in_house.get(d, set()))
            reserved = len(reserved_house.get(d, set()))
            pct = round(100.0 * sold / sellable, 1) if sellable else 0.0
            occupancy[d] = {'sold': sold, 'reserved': reserved,
                            'sellable': sellable, 'pct': pct}
        return {'date_from': fields.Date.to_string(start), 'days': days,
                'dates': dates, 'rooms': room_rows, 'segments': segments,
                'occupancy': occupancy}

    @api.model
    def get_blocked_dates(self, room_id, date_from=None, date_to=None,
                          ignore_booking_id=False,
                          ignore_line_id=False):
        """Blocked nights for one room. Read-only.

        Expands each active line (``reserved``/``check_in``) to
        ``[checkin_date, checkout_date)`` — checkout day stays free
        so same-day turnover works. Also flags OOO/dirty (open
        maintenance/cleaning blocks any date server-side).
        """
        today = fields.Date.context_today(self)
        start = fields.Date.from_string(date_from) if date_from else today
        if date_to:
            end = fields.Date.from_string(date_to)
        else:
            end = start + timedelta(days=13)
        if end < start:
            raise ValidationError(
                _("Blocked end date (%s) is before start (%s).")
                % (end, start))
        # Single-room query (picker UX): allow a wide window so future
        # months stay covered. The 31-day cap lives on get_rack, which
        # fans out over every room x day.
        if (end - start).days > 366:
            end = start + timedelta(days=366)
        room = self.env['product.template'].browse(int(room_id or 0))
        if not room.exists():
            raise ValidationError(_("Unknown room (id %s).") % room_id)
        window_start = fields.Datetime.to_string(
            datetime.combine(start, datetime.min.time()))
        window_end = fields.Datetime.to_string(
            datetime.combine(end + timedelta(days=1),
                             datetime.min.time()))
        domain = [
            ('room_id', '=', room.id),
            ('booking_id.company_id', '=', self.env.company.id),
            ('booking_id.state', 'in', ('reserved', 'check_in')),
            ('checkin_date', '<', window_end),
            ('checkout_date', '>', window_start),
        ]
        if ignore_booking_id:
            domain.append(('booking_id', '!=', int(ignore_booking_id)))
        if ignore_line_id:
            domain.append(('id', '!=', int(ignore_line_id)))
        lines = self.env['room.booking.line'].search(domain)
        booked = set()
        for line in lines:
            ci = _to_date(line.checkin_date)
            co = _to_date(line.checkout_date)
            if not (ci and co) or co <= ci:
                continue
            day = max(ci, start)
            last = min(co, end + timedelta(days=1))
            while day < last:
                booked.add(fields.Date.to_string(day))
                day += timedelta(days=1)
        ooo = room.id in self._ooo_room_ids()
        dirty = room.id in self._dirty_room_ids()
        blocked = set(booked)
        if ooo or dirty:
            day = start
            while day <= end:
                blocked.add(fields.Date.to_string(day))
                day += timedelta(days=1)
        return {
            'room_id': room.id,
            'date_from': fields.Date.to_string(start),
            'date_to': fields.Date.to_string(end),
            'blocked': sorted(blocked),
            'booked': sorted(booked),
            'ooo': bool(ooo),
            'dirty': bool(dirty),
        }
