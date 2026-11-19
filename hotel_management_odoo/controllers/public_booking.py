# controllers/public_booking.py
from types import SimpleNamespace

from odoo import fields, http
from odoo.http import request

ALLOWED_POST = {'room_id', 'ci', 'co', 'adults', 'children', 'board', 'name',
                'phone', 'email', 'notes', 'idem_key', 'honeypot'}

# ?e= taxonomy (never leak exception names to guests):
# spam = honeypot trip; unavailable = sold out / over capacity, retry dates;
# invalid = everything else (bad dates, guest, pax, room).
_UNAVAILABLE = ('room just sold', 'over capacity')


def _err_code(exc):
    msg = str(exc)
    for needle in _UNAVAILABLE:
        if needle in msg:
            return 'unavailable'
    return 'invalid'


def _group_rooms_by_type(rows):
    """Group free per-room search rows by room type. Pure (no env).

    Key: ('id', type_id) when truthy else ('name', type label).
    Representative: cheapest free row — min by (nightly, id).
    Output sorted by (nightly, type label)."""
    groups = {}
    for r in rows or []:
        tid = r.get('type_id')
        key = ('id', tid) if tid else ('name', r.get('type') or '')
        groups.setdefault(key, []).append(r)
    out = []
    for members in groups.values():
        rep = min(members, key=lambda r: (r.get('nightly') or 0.0, r.get('id') or 0))
        out.append({
            'type_id': rep.get('type_id'),
            'type': rep.get('type') or '',
            'count': len(members),
            'rep_id': rep.get('id'),
            'rep_name': rep.get('name'),
            'nightly': rep.get('nightly'),
            'total': rep.get('total'),
            'nightly_str': rep.get('nightly_str'),
            'total_str': rep.get('total_str'),
            'image_url': rep.get('image_url'),
            'adult_capacity': rep.get('adult_capacity'),
            'max_occupants': rep.get('max_occupants'),
            'amenities': rep.get('amenities'),
        })
    out.sort(key=lambda g: (g['nightly'] or 0.0, g['type'] or ''))
    return out


class PublicBooking(http.Controller):
    @http.route('/book', type='http', auth='public', website=False, methods=['GET'])
    def book(self, **kw):
        ci, co = kw.get('ci', ''), kw.get('co', '')
        try:
            adults = max(1, int(kw.get('adults', 2) or 2))
        except Exception:
            adults = 2
        try:
            children = max(0, int(kw.get('children', 0) or 0))
        except Exception:
            children = 0
        svc = request.env['hotel.public.booking'].sudo()
        adults, children, max_pax = svc._clamp_pax(adults, children)
        kw['adults'] = str(adults)
        kw['children'] = str(children)
        boards = svc.allowed_boards()
        codes = [b['code'] for b in boards]
        board = (kw.get('board', 'BB') or 'BB').strip().upper()[:8]
        if board not in codes:
            board = 'BB' if 'BB' in codes else (codes[0] if codes else 'BB')
        board_name = next((b['name'] for b in boards if b['code'] == board), board)
        kw['board'] = board
        dicts = svc.search_free(
            ci, co, adults=adults, children=children,
            board=board) if ci and co else []
        # QWeb t-esc cannot subscript dicts — expose attribute access.
        rooms = [SimpleNamespace(**d) for d in _group_rooms_by_type(dicts)]
        try:
            nights = max(0, (fields.Date.from_string(co) - fields.Date.from_string(ci)).days)
        except Exception:
            nights = 0
        return request.render('hotel_management_odoo.public_book_page',
                             {'rooms': rooms, 'kw': kw, 'nights': nights,
                              'boards': boards, 'board_name': board_name,
                              'max_pax': max_pax})

    @http.route('/book/availability', type='json', auth='public', website=False, methods=['POST'], csrf=False)
    def avail(self, ci=None, co=None, adults=2, children=0, board='BB'):
        return {'rooms': request.env['hotel.public.booking'].sudo().search_free(
            ci, co, adults=adults, children=children, board=board)}

    @http.route('/book/confirm', type='http', auth='public', website=False, methods=['POST'], csrf=True)
    def confirm(self, **kw):
        if kw.get('honeypot'):
            return request.redirect('/book?e=spam')
        vals = {k: kw.get(k) for k in ALLOWED_POST if k in kw and k != 'honeypot'}
        try:
            bk = request.env['hotel.public.booking'].sudo().create_booking(vals)
        except Exception as e:
            return request.redirect('/book?e=%s' % _err_code(e))
        # HOOK (booking web deposit, future M-Pesa): redirect to a
        # deposit/payment step here before /book/done, then call
        # bk.action_take_deposit(amount) after provider confirmation.
        # Nothing moves money yet — see public_booking_service hook.
        return request.redirect('/book/done?ref=%s' % bk.name)

    @http.route('/book/room-image/<int:room_id>', type='http', auth='public',
                 website=False, methods=['GET'])
    def room_image(self, room_id):
        """Room-type photo for public cards. Read-only; only published,
        active rooms; magic-byte content type; long cache (photos rarely
        change)."""
        room = request.env['product.template'].sudo().browse(room_id)
        if (not room.exists() or not room.is_room or not room.active
                or not room.website_published):
            return request.not_found()
        raw = bytes(room.room_type_id.image or b'')
        if not raw:
            return request.not_found()
        if raw[:2] == b'\xff\xd8':
            ctype = 'image/jpeg'
        elif raw[:4] == b'\x89PNG':
            ctype = 'image/png'
        else:
            ctype = 'application/octet-stream'
        return request.make_response(raw, [('Content-Type', ctype),
                                           ('Cache-Control', 'public, max-age=86400')])

    @http.route('/book/done', type='http', auth='public', website=False, methods=['GET'])
    def done(self, ref=None, **kw):
        # Whitelist-only gate params; lookup is read-only + PII-gated in service.
        ref = (ref or '').strip()[:64] or None
        last3 = kw.get('last3') if isinstance(kw.get('last3'), str) else None
        confirmation = None
        if ref and last3:
            data = request.env['hotel.public.booking'].sudo().get_public_confirmation(ref, last3)
            confirmation = SimpleNamespace(**data) if data else None
        return request.render('hotel_management_odoo.public_book_done', {
            'ref': ref, 'last3': last3, 'confirmation': confirmation,
        })
