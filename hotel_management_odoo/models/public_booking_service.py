# models/public_booking_service.py
from datetime import datetime, timezone
from odoo import api, fields, models
class HotelPublicBooking(models.AbstractModel):
    _name = 'hotel.public.booking'
    _description = 'Public booking service (isolated, no storage)'
    @api.model
    def search_free(self, ci_date, co_date, adults=2, children=0):
        ci = fields.Date.from_string(ci_date); co = fields.Date.from_string(co_date)
        if not ci or not co or co <= ci or (co - ci).days > 30:
            return []
        rooms = self.env['product.template'].sudo().search([
            ('is_room','=',True),('website_published','=',True),('active','=',True)])
        if not rooms: return []
        ooo = set(self.env['hotel.daily.inventory']._ooo_room_ids())
        dirty = set(self.env['hotel.daily.inventory']._dirty_room_ids())
        wstart = datetime.combine(ci, datetime.min.time()).replace(tzinfo=timezone.utc).replace(tzinfo=None)
        wend = datetime.combine(co, datetime.max.time()).replace(tzinfo=timezone.utc).replace(tzinfo=None)
        busy = set(self.env['room.booking.line'].sudo().search([
            ('booking_id.state','in',('reserved','check_in')),
            ('checkin_date','<',fields.Datetime.to_string(wend)),
            ('checkout_date','>',fields.Datetime.to_string(wstart)),
        ]).mapped('room_id.id'))
        out = []
        nights = (co - ci).days
        for r in rooms:
            if r.id in busy or r.id in ooo or r.id in dirty: continue
            nightly = r.room_type_id.base_rate or 0.0
            # rate-line override best-effort, never crashes pricing
            try:
                line = self.env['hotel.rate.line'].sudo().find_line(False, r.room_type_id.id, 'BB', self.env.company.id, False)
                if line: nightly = line.price
            except Exception: pass
            out.append({'id': r.id, 'name': r.name, 'type': r.room_type_id.name or '',
                        'nightly': float(nightly), 'total': float(nightly) * nights})
        return out
    @api.model
    def booked_ranges(self, room_id, dfrom, dto):
        return []
