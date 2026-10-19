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
from datetime import datetime, timedelta

from odoo import api, fields, models

_RACK_STATUSES = ('available', 'reserved', 'occupied', 'dirty', 'ooo')
_DISPLAY = {
    'available': 'Available',
    'reserved': 'Reserved',
    'occupied': 'In-House',
    'dirty': 'Dirty',
    'ooo': 'OOO',
}


def _to_date(value):
    if not value:
        return None
    if isinstance(value, str):
        return fields.Date.from_string(value)
    from datetime import datetime
    if isinstance(value, datetime):
        return value.date()
    return value


def _nights(checkin_day, checkout_day):
    """Nights in a stay; minimum 1 so same-day/day-use splits sanely."""
    return max((checkout_day - checkin_day).days, 1)


class HotelDailyInventory(models.AbstractModel):
    """Computed availability. OWL tape-chart reads it, no new table."""
    _name = 'hotel.daily.inventory'
    _description = "Hotel Daily Inventory (computed)"

    @api.model
    def _rooms(self):
        return self.env['product.template'].search(
            [('is_room', '=', True)], order='name')

    @api.model
    def _ooo_room_ids(self):
        reqs = self.env['maintenance.request'].search([
            ('type', '=', 'room'),
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
            start, end = end, start
        if (end - start).days > 31:
            end = start + timedelta(days=31)
        rooms = self._rooms()
        ooo_ids = self._ooo_room_ids()
        dirty_ids = self._dirty_room_ids()
        window_start_dt = fields.Datetime.to_string(
            datetime.combine(start, datetime.now().time()).replace(
                hour=0, minute=0, second=0))
        window_end_dt = fields.Datetime.to_string(
            datetime.combine(end, datetime.now().time()).replace(
                hour=23, minute=59, second=59))
        lines = self.env['room.booking.line'].search([
            ('booking_id.state', 'in', ('reserved', 'check_in')),
            ('checkin_date', '<=', window_end_dt),
            ('checkout_date', '>', window_start_dt),
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
                    for line in lines:
                        if line.room_id.id != room.id:
                            continue
                        ci = _to_date(line.checkin_date)
                        co = _to_date(line.checkout_date)
                        if ci and co and ci <= day < co:
                            if line.booking_id.state == 'check_in':
                                status = 'occupied'
                                booking_id = line.booking_id.id
                                break
                            if status != 'occupied' and line.booking_id.state == 'reserved':
                                status = 'reserved'
                                booking_id = line.booking_id.id
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

        lines = self.env['room.booking.line'].search([
            ('booking_id.state', 'in', ('reserved', 'check_in')),
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
                nightly = (line.price_total or 0.0) / _nights(ci, co)
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
        # Arrivals: lines starting today (reserved or checked-in).
        arrivals = sum(
            1 for line in lines
            if _to_date(line.checkin_date) == today
            and line.booking_id.state in ('reserved', 'check_in'))
        # Departures: in-house lines ending today.
        departures = sum(
            1 for line in lines
            if _to_date(line.checkout_date) == today
            and line.booking_id.state == 'check_in')
        occupied = len(occupied_ids)
        occupancy = round(100.0 * occupied / sellable, 1) if sellable else 0.0
        adr = round(revenue / occupied, 2) if occupied else 0.0
        revpar = round(revenue / sellable, 2) if sellable else 0.0
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
        }
