# models/public_booking_service.py
import html as _html
import re
from datetime import datetime, timedelta, timezone
from odoo import api, fields, models


class HotelPublicBooking(models.AbstractModel):
    _name = 'hotel.public.booking'
    _description = 'Public booking service (isolated, no storage)'

    ALLOWED = {'room_id', 'ci', 'co', 'adults', 'children', 'board', 'name',
                'phone', 'email', 'notes', 'idem_key'}
    _IDEM_RE = re.compile(r'^[\w-]{1,64}$')
    _LAST3_RE = re.compile(r'^\d{3}$')

    # Day-use plans (no overnight stay) are never offered on the public
    # overnight booking page, even when active in the catalogue.
    BOARD_DAY_USE = ('DP',)

    # Fallback global guest cap when no publishable room exists. The page
    # still renders; the server filter stays source of truth.
    PAX_FALLBACK = 2

    @api.model
    def max_pax(self):
        """Global guest cap: max effective room occupancy.

        Effective per-room cap = min(num_person or type_max,
        type_max or num_person) over published active rooms.
        Falls back to PAX_FALLBACK when no room yields a cap."""
        S = self.sudo()
        rooms = S.env['product.template'].search([
            ('is_room', '=', True), ('website_published', '=', True),
            ('active', '=', True)])
        caps = []
        for r in rooms:
            np = r.num_person or 0
            rt_max = r.room_type_id.max_occupants if r.room_type_id else 0
            eff = min(np or rt_max, rt_max or np)
            if eff > 0:
                caps.append(eff)
        return max(caps) if caps else self.PAX_FALLBACK

    @api.model
    def _clamp_pax(self, adults, children):
        """Clamp guests to the global cap. Adults 1..GMAX, children
        0..GMAX, total adults+children <= GMAX (trim children first)."""
        gmax = max(1, int(self.max_pax() or self.PAX_FALLBACK))
        try:
            adults = max(1, int(adults or 1))
        except Exception:
            adults = 2
        try:
            children = max(0, int(children or 0))
        except Exception:
            children = 0
        adults = min(adults, gmax)
        children = min(children, gmax)
        if adults + children > gmax:
            children = max(0, gmax - adults)
        return adults, children, gmax

    @api.model
    def allowed_boards(self):
        """Overnight meal plans for the public page, from the DB catalogue.

        Returns [{'code','name','description'}] for active, non-day-use
        plans ordered by sequence. The widget renders these; validation
        uses the same list, so a new overnight plan appears with no code
        change."""
        S = self.sudo()
        plans = S.env['hotel.meal.plan'].search(
            [('active', '=', True), ('code', 'not in', list(self.BOARD_DAY_USE))],
            order='sequence, code')
        return [{'code': p.code, 'name': p.name,
                 'description': p.description or ''} for p in plans]

    @api.model
    def _default_board(self, boards=None):
        codes = [b['code'] for b in (boards if boards is not None
                                     else self.allowed_boards())]
        if 'BB' in codes:
            return 'BB'
        return codes[0] if codes else 'BB'

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
    def search_free(self, ci_date, co_date, adults=2, children=0, board='BB'):
        ci = fields.Date.from_string(ci_date); co = fields.Date.from_string(co_date)
        if not ci or not co or co <= ci or (co - ci).days > 30:
            return []
        try:
            adults = max(1, int(adults or 1))
            children = max(0, int(children or 0))
        except Exception:
            adults, children = 2, 0
        adults, children, _gmax = self._clamp_pax(adults, children)
        board = (board or 'BB').strip().upper()[:8]
        if board not in [b['code'] for b in self.allowed_boards()]:
            board = self._default_board()
        S = self.sudo()
        company = S.env.company
        # Same plan resolution the booking line uses (_plan_for_booking):
        # board-code plan, else the company default. The page quotes the
        # same board the booking is created with (room.booking default BB).
        plan = S.env['hotel.rate.plan'].search(
            [('company_id', '=', company.id), ('code', '=', board)],
            order='id', limit=1)
        if not plan:
            plan = S.env['hotel.rate.plan']._default_plan(company)
        engine = S.env['hotel.rate.engine']
        rooms = S.env['product.template'].search([
            ('is_room','=',True),('website_published','=',True),('active','=',True)])
        if not rooms: return []
        ooo = set(S.env['hotel.daily.inventory']._ooo_room_ids())
        dirty = set(S.env['hotel.daily.inventory']._dirty_room_ids())
        wstart = datetime.combine(ci, datetime.min.time()).replace(tzinfo=timezone.utc).replace(tzinfo=None)
        wend = datetime.combine(co, datetime.max.time()).replace(tzinfo=timezone.utc).replace(tzinfo=None)
        busy = set(S.env['room.booking.line'].search([
            # Draft blocks too: public bookings stay draft when
            # auto-confirm is off (or reserve fails), and draft-vs-draft
            # overlap is allowed by the line constraint — without this
            # the /book list keeps showing a just-booked room.
            ('booking_id.state','in',('draft','reserved','check_in')),
            ('checkin_date','<',fields.Datetime.to_string(wend)),
            ('checkout_date','>',fields.Datetime.to_string(wstart)),
        ]).mapped('room_id.id'))
        out = []
        nights = (co - ci).days
        pax = adults + children
        for r in rooms:
            if r.id in busy or r.id in ooo or r.id in dirty: continue
            # Capacity pre-check mirrors create_booking: an over-capacity
            # room cannot be booked, so it is not listed either.
            rt_max = r.room_type_id.max_occupants if r.room_type_id else 0
            if (r.num_person and pax > r.num_person) or (rt_max and pax > rt_max):
                continue
            # Canonical nightly: the same engine call the booking line
            # prices with (check-in anchor, board, pax). Fallback keeps
            # the page up when the engine cannot price a room.
            nightly = None
            try:
                q = engine.price_detailed(
                    r.id, fields.Date.to_string(ci), plan.id,
                    adults=adults, children=children, board=board)
                if q:
                    nightly = float(q.get('net', 0.0))
            except Exception:
                nightly = None
            if not nightly:
                nightly = r.room_type_id.base_rate or 0.0
                try:
                    line = S.env['hotel.rate.line'].find_line(False, r.room_type_id.id, 'BB', company.id, False)
                    if line: nightly = line.price
                except Exception: pass
            out.append({'id': r.id, 'name': r.name, 'type': r.room_type_id.name or '',
                        'type_id': r.room_type_id.id or False,
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
    def blocked_days(self, dfrom, dto):
        """Fully-booked nights in [dfrom, dto). Read-only.

        Night D = [D 14:00, D+1 11:00); a line blocks it iff
        checkin < night-end and checkout > night-start. A night is
        listed only when EVERY published room is busy (booking line
        in draft/reserved/check_in, OOO, or dirty) — absolute
        blocking, no pax filter. Garbage input (unparsable, empty
        window, span > 93 days) returns []."""
        try:
            d1 = fields.Date.from_string(dfrom)
            d2 = fields.Date.from_string(dto)
        except Exception:
            return []
        if not d1 or not d2 or d2 <= d1 or (d2 - d1).days > 93:
            return []
        S = self.sudo()
        rooms = S.env['product.template'].search([
            ('is_room', '=', True), ('website_published', '=', True),
            ('active', '=', True)])
        if not rooms:
            return []
        room_ids = set(rooms.ids)
        # OOO/dirty are date-independent: an open request blocks the
        # room for every night in the window (same set-union line).
        busy_all = (set(S.env['hotel.daily.inventory']._ooo_room_ids())
                    | set(S.env['hotel.daily.inventory']._dirty_room_ids())
                    ) & room_ids
        wstart = fields.Datetime.to_string(datetime(
            d1.year, d1.month, d1.day, 14, 0, 0))
        wend = fields.Datetime.to_string(datetime(
            d2.year, d2.month, d2.day, 11, 0, 0))
        lines = S.env['room.booking.line'].search([
            ('booking_id.state', 'in', ('draft', 'reserved', 'check_in')),
            ('room_id', 'in', list(room_ids)),
            ('checkin_date', '<', wend),
            ('checkout_date', '>', wstart),
        ])
        out = []
        day = d1
        while day < d2:
            start = datetime(day.year, day.month, day.day, 14, 0, 0)
            end = datetime(day.year, day.month, day.day, 11, 0, 0) + timedelta(days=1)
            busy = set(busy_all)
            for line in lines:
                if (line.checkin_date and line.checkout_date
                        and line.checkin_date < end
                        and line.checkout_date > start):
                    busy.add(line.room_id.id)
            if len(busy & room_ids) >= len(room_ids):
                out.append(fields.Date.to_string(day))
            day += timedelta(days=1)
        return out

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
        adults, children, _gmax = self._clamp_pax(adults, children)
        board = (vals.get('board') or 'BB').strip().upper()[:8]
        if board not in [b['code'] for b in self.allowed_boards()]:
            raise ValueError('bad board')
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
        free = {r['id'] for r in self.search_free(
            vals.get('ci'), vals.get('co'), adults=adults, children=children,
            board=board)}
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
            'meal_plan': board,
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
        # HOOK (booking web deposit, future M-Pesa): once a payment
        # provider is integrated, confirm the payment first, then call
        # bk.action_take_deposit(amount) here so the public booking
        # carries the same folio/deposit/collect path as reception.
        # Until then the web stays payment-free: reception takes the
        # deposit via the booking Take Deposit button.
        if S.env.company.public_auto_confirm:
            try:
                bk.action_reserve()
            except Exception as e:
                # Never leave a silent draft behind when auto-confirm was
                # requested: it would block the room (draft now counts as
                # busy) while the guest thinks they are reserved.
                # Overlap -> sold; anything else surfaces as invalid.
                bk.unlink()
                if 'already booked' in str(e):
                    raise ValueError('room just sold')
                raise
        return bk
