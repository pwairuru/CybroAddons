# models/public_booking_service.py
import html as _html
import re
from datetime import datetime, timezone
from odoo import api, fields, models


class HotelPublicBooking(models.AbstractModel):
    _name = 'hotel.public.booking'
    _description = 'Public booking service (isolated, no storage)'

    ALLOWED = {'room_id', 'ci', 'co', 'adults', 'children', 'name',
               'phone', 'email', 'notes', 'idem_key'}
    _IDEM_RE = re.compile(r'^[\w-]{1,64}$')
    _LAST3_RE = re.compile(r'^\d{3}$')

    @staticmethod
    def _like_escape(s):
        # Escape LIKE wildcards so ilike auto-wrap still matches literally.
        return s.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')

    @staticmethod
    def _normalize_phone(raw):
        # Canonicalize KE mobile: 07XX... / 2547XX... -> +2547XX...
        p = (raw or '').strip().replace(' ', '').replace('-', '')
        m = re.fullmatch(r'0(\d{9})', p)
        if m:
            return '+254' + m.group(1)
        m = re.fullmatch(r'254(\d{9})', p)
        if m:
            return '+' + p
        return p[:20]

    @api.model
    def get_public_confirmation(self, ref, last3):
        """Read-only PII gate for /book/done. Returns a sanitized dict
        (ref, ci, co, room, state) only when `ref` names a booking whose
        partner phone ends with `last3`; else None. Never raises, never
        writes, adds no stored fields."""
        try:
            ref = (ref or '').strip()[:64]
            tail = re.sub(r'\D', '', str(last3 or ''))[-3:]
            if not ref or not self._LAST3_RE.match(tail):
                return None
            S = self.sudo()
            bk = S.env['room.booking'].search([('name', '=', ref)], limit=1)
            if not bk:
                return None
            phone_digits = re.sub(r'\D', '', bk.partner_id.phone or '')
            if not phone_digits or not phone_digits.endswith(tail):
                return None
            line = S.env['room.booking.line'].search(
                [('booking_id', '=', bk.id)], limit=1)
            room_name = line.room_id.display_name if line and line.room_id else ''
            return {
                'ref': bk.name,
                'ci': fields.Date.to_string(bk.checkin_date.date()) if bk.checkin_date else '',
                'co': fields.Date.to_string(bk.checkout_date.date()) if bk.checkout_date else '',
                'room': room_name,
                'state': dict(bk._fields['state'].selection).get(bk.state, bk.state),
            }
        except Exception:
            return None
    @api.model
    def search_free(self, ci_date, co_date, adults=2, children=0):
        ci = fields.Date.from_string(ci_date); co = fields.Date.from_string(co_date)
        if not ci or not co or co <= ci or (co - ci).days > 30:
            return []
        rooms = self.env['product.template'].sudo().search([
            ('is_room','=',True),('website_published','=',True),('active','=',True)])
        if not rooms: return []
        ooo = set(self.env['hotel.daily.inventory'].sudo()._ooo_room_ids())
        dirty = set(self.env['hotel.daily.inventory'].sudo()._dirty_room_ids())
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
                        'nightly': float(nightly), 'total': float(nightly) * nights,
                        'nightly_str': 'KES {:,.0f}'.format(nightly),
                        'total_str': 'KES {:,.0f}'.format(float(nightly) * nights),
                        'image_url': '/book/room-image/%d' % r.id,
                        'adult_capacity': r.room_type_id.adult_capacity or 0,
                        'max_occupants': r.room_type_id.max_occupants or 0,
                        'amenities': [a.name for a in r.room_type_id.amenity_ids if a.name],
                        })
        out.sort(key=lambda d: d['nightly'])
        left = {}
        for d in out:
            left[d['type']] = left.get(d['type'], 0) + 1
        for d in out:
            d['type_left'] = left[d['type']] - 1
        return out
    @api.model
    def booked_ranges(self, room_id, dfrom, dto):
        return []

    @api.model
    def create_booking(self, vals):
        # Whitelist-only: model/res_id/method/__ etc all rejected here.
        vals = dict(vals or {})
        extra = set(vals) - self.ALLOWED
        if extra:
            raise ValueError('rejected fields: %s' % sorted(extra))
        # normalize + validate (no eval, no browsing arbitrary models)
        try:
            room_id = int(vals.get('room_id') or 0)
        except Exception:
            raise ValueError('bad room')
        ci = fields.Date.from_string(vals.get('ci'))
        co = fields.Date.from_string(vals.get('co'))
        if not ci or not co or co <= ci or (co - ci).days > 30:
            raise ValueError('bad dates')
        if ci < fields.Date.context_today(self):
            raise ValueError('bad dates')
        name = (vals.get('name') or '').strip()[:80]
        phone = self._normalize_phone(vals.get('phone'))
        if len(name) < 2 or len(phone) < 9:
            raise ValueError('bad guest')
        email = (vals.get('email') or '').strip()[:120]
        notes = (vals.get('notes') or '').strip()[:500]
        idem = (vals.get('idem_key') or '').strip()[:64]
        if idem and not self._IDEM_RE.match(idem):
            raise ValueError('bad idem_key')
        try:
            adults = max(1, int(vals.get('adults') or 1))
            children = max(0, int(vals.get('children') or 0))
        except Exception:
            raise ValueError('bad pax')
        S = self.sudo()
        # Capacity gate mirrors room.booking.line (room num_person, else
        # type max_occupants). Public books are always blocked, never warned.
        room = S.env['product.template'].browse(room_id)
        if not room.exists() or not room.is_room:
            raise ValueError('bad room')
        pax = adults + children
        rt_max = room.room_type_id.max_occupants if room.room_type_id else 0
        if (room.num_person and pax > room.num_person) or (rt_max and pax > rt_max):
            raise ValueError('over capacity')
        # idempotency: room.booking has no ref/client field (no new stored
        # fields allowed), so reuse the booking already posted with this
        # chatter marker.
        if idem:
            marker = 'public-idem:%s' % idem
            msg = S.env['mail.message'].search(
                [('model', '=', 'room.booking'),
                 ('body', 'ilike', self._like_escape(marker))],
                order='id desc', limit=1)
            if msg and msg.res_id:
                dup = S.env['room.booking'].browse(msg.res_id)
                if dup.exists():
                    return dup
        free = {r['id'] for r in self.search_free(vals.get('ci'), vals.get('co'))}
        if room_id not in free:
            raise ValueError('room just sold')
        company = S.env.company
        partner = S.env['res.partner'].search([('phone', '=', phone)], limit=1)
        if not partner:
            partner = S.env['res.partner'].create({
                'name': name, 'phone': phone, 'email': email or False,
                'company_id': company.id,
            })
        # 14:00/11:00 mirrors channel sync; sits inside search_free window.
        checkin_dt = fields.Datetime.to_string(
            datetime(ci.year, ci.month, ci.day, 14, 0, 0))
        checkout_dt = fields.Datetime.to_string(
            datetime(co.year, co.month, co.day, 11, 0, 0))
        bk = S.env['room.booking'].create({
            'partner_id': partner.id,
            'company_id': company.id,
            'checkin_date': checkin_dt,
            'checkout_date': checkout_dt,
        })
        S.env['room.booking.line'].create({
            'booking_id': bk.id,
            'company_id': company.id,
            'room_id': room_id,
            'checkin_date': checkin_dt,
            'checkout_date': checkout_dt,
            'adults': adults,
            'children': children,
        })
        body = 'source: public /book' + (' public-idem:%s' % idem if idem else '')
        if notes:
            body += '<br/>notes: %s' % _html.escape(notes)
        bk.message_post(body=body)
        if S.env.company.public_auto_confirm:
            try:
                bk.action_reserve()
            except Exception:
                pass
        return bk
