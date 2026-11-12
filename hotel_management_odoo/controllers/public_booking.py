# controllers/public_booking.py
from odoo import http
from odoo.http import request

ALLOWED_POST = {'room_id', 'ci', 'co', 'adults', 'children', 'name',
                'phone', 'email', 'notes', 'idem_key', 'honeypot'}


class PublicBooking(http.Controller):
    @http.route('/book', type='http', auth='public', website=False, methods=['GET'])
    def book(self, **kw):
        rooms = request.env['hotel.public.booking'].sudo().search_free(
            kw.get('ci', ''), kw.get('co', '')) if kw.get('ci') and kw.get('co') else []
        return request.render('hotel_management_odoo.public_book_page', {'rooms': rooms, 'kw': kw})

    @http.route('/book/availability', type='json', auth='public', website=False, methods=['POST'], csrf=False)
    def avail(self, ci=None, co=None):
        return {'rooms': request.env['hotel.public.booking'].sudo().search_free(ci, co)}

    @http.route('/book/confirm', type='http', auth='public', website=False, methods=['POST'], csrf=True)
    def confirm(self, **kw):
        if kw.get('honeypot'):
            return request.redirect('/book?e=spam')
        vals = {k: kw.get(k) for k in ALLOWED_POST if k in kw and k != 'honeypot'}
        try:
            bk = request.env['hotel.public.booking'].sudo().create_booking(vals)
        except Exception as e:
            return request.redirect('/book?e=%s' % type(e).__name__)
        return request.redirect('/book/done?ref=%s' % bk.name)

    @http.route('/book/done', type='http', auth='public', website=False, methods=['GET'])
    def done(self, ref=None, **kw):
        # Whitelist-only gate params; lookup is read-only + PII-gated in service.
        last3 = kw.get('last3') if isinstance(kw.get('last3'), str) else None
        confirmation = None
        if ref and last3:
            confirmation = request.env['hotel.public.booking'].sudo().get_public_confirmation(ref, last3)
        return request.render('hotel_management_odoo.public_book_done', {
            'ref': ref, 'last3': last3, 'confirmation': confirmation,
        })
