# -*- coding: utf-8 -*-
"""Task 11: hotel report pack foundation (8 core reports, PDF + XLSX).

Each report renders from live queries scoped to the wizard company; empty
data still renders headers so reports never crash on fresh databases.
Remaining 19 reports are a documented follow-up (see task-11-report.md).
"""
import io
import json
from datetime import datetime, time as dtime

from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import json_default

try:
    from odoo.tools.misc import xlsxwriter
except ImportError:  # pragma: no cover
    import xlsxwriter


CORE_REPORTS = [
    ('hotel_occupancy', 'Occupancy Report'),
    ('hotel_inhouse', 'In-House Guests'),
    ('hotel_arrivals_departures', 'Arrivals & Departures'),
    ('hotel_cashier_shifts', 'Cashier Shifts'),
    ('hotel_housekeeping_status', 'Housekeeping Status'),
    ('hotel_flash', 'Manager Flash'),
    ('hotel_adr_revpar', 'ADR / RevPAR'),
    ('hotel_asset_register', 'Asset Register'),
]


def _company_name(company):
    """XLSX-safe company label: recordset -> display name, else str."""
    if hasattr(company, 'display_name'):
        return company.display_name or ''
    return str(company or '')


class HotelReportPack(models.TransientModel):
    _name = 'hotel.report.pack'
    _description = 'Hotel Report Pack'

    report_type = fields.Selection(CORE_REPORTS, string='Report',
                                   required=True, default='hotel_occupancy')
    date_from = fields.Date(string='From', default=fields.Date.today)
    date_to = fields.Date(string='To', default=fields.Date.today)
    company_id = fields.Many2one('res.company', string='Company',
                                 required=True,
                                 default=lambda self: self.env.company)

    @api.constrains('date_from', 'date_to')
    def _check_range(self):
        for rec in self:
            if rec.date_from and rec.date_to and rec.date_from > rec.date_to:
                raise ValidationError('From date must be before To date.')

    # ------------------------------------------------------------------
    # data builders (company-scoped, empty-safe)
    # ------------------------------------------------------------------
    def _bounds(self):
        self.ensure_one()
        start = datetime.combine(self.date_from or fields.Date.today(),
                                 dtime.min)
        end = datetime.combine(self.date_to or fields.Date.today(),
                               dtime.max)
        return start, end

    def _pack_data(self):
        self.ensure_one()
        builder = getattr(self, '_data_%s' % self.report_type)
        columns, rows, totals = builder()
        return {
            'report': self.report_type,
            'title': dict(CORE_REPORTS)[self.report_type],
            'date_from': str(self.date_from or ''),
            'date_to': str(self.date_to or ''),
            'company': self.company_id,
            'columns': [{'key': k, 'label': v} for k, v in columns],
            'rows': rows,
            'totals': totals,
        }

    def _booking_lines_in_range(self):
        start, end = self._bounds()
        return self.env['room.booking.line'].search([
            ('company_id', '=', self.company_id.id),
            ('checkin_date', '<=', end),
            ('checkout_date', '>=', start),
        ])

    def _data_hotel_occupancy(self):
        columns = [('guest', 'Guest'), ('room', 'Room'),
                   ('checkin', 'Check-In'), ('checkout', 'Check-Out'),
                   ('nights', 'Nights')]
        rows, nights = [], 0
        for line in self._booking_lines_in_range():
            n = max((line.checkout_date - line.checkin_date).days, 0) \
                if line.checkin_date and line.checkout_date else 0
            nights += n
            rows.append({
                'guest': line.booking_id.partner_id.display_name,
                'room': line.room_id.display_name,
                'checkin': str(line.checkin_date or ''),
                'checkout': str(line.checkout_date or ''),
                'nights': n,
            })
        rooms = len({line.room_id.id for line in
                     self._booking_lines_in_range()})
        return columns, rows, {'occupied_nights': nights,
                               'rooms_occupied': rooms}

    def _data_hotel_inhouse(self):
        columns = [('guest', 'Guest'), ('room', 'Room'),
                   ('checkin', 'Check-In'), ('checkout', 'Check-Out')]
        rows = []
        bookings = self.env['room.booking'].search([
            ('company_id', '=', self.company_id.id),
            ('state', '=', 'check_in'),
        ])
        for booking in bookings:
            for line in booking.room_line_ids:
                rows.append({
                    'guest': booking.partner_id.display_name,
                    'room': line.room_id.display_name,
                    'checkin': str(line.checkin_date or ''),
                    'checkout': str(line.checkout_date or ''),
                })
        return columns, rows, {'in_house': len(bookings)}

    def _data_hotel_arrivals_departures(self):
        start, end = self._bounds()
        columns = [('movement', 'Movement'), ('guest', 'Guest'),
                   ('room', 'Room'), ('date', 'Date')]
        rows = []
        arrivals = self.env['room.booking.line'].search([
            ('company_id', '=', self.company_id.id),
            ('checkin_date', '>=', start),
            ('checkin_date', '<=', end),
        ])
        departures = self.env['room.booking.line'].search([
            ('company_id', '=', self.company_id.id),
            ('checkout_date', '>=', start),
            ('checkout_date', '<=', end),
        ])
        for line in arrivals:
            rows.append({'movement': 'Arrival',
                         'guest': line.booking_id.partner_id.display_name,
                         'room': line.room_id.display_name,
                         'date': str(line.checkin_date or '')})
        for line in departures:
            rows.append({'movement': 'Departure',
                         'guest': line.booking_id.partner_id.display_name,
                         'room': line.room_id.display_name,
                         'date': str(line.checkout_date or '')})
        return columns, rows, {'arrivals': len(arrivals),
                               'departures': len(departures)}

    def _data_hotel_cashier_shifts(self):
        columns = [('cashier', 'Cashier'), ('state', 'State'),
                   ('opening', 'Opening'), ('expected', 'Expected'),
                   ('closing', 'Closing'), ('variance', 'Variance')]
        rows = []
        shifts = self.env['hotel.cashier.shift'].search([
            ('company_id', '=', self.company_id.id),
        ])
        for shift in shifts:
            rows.append({
                'cashier': shift.user_id.display_name,
                'state': shift.state,
                'opening': shift.opening_cash,
                'expected': shift.expected_cash,
                'closing': shift.closing_cash,
                'variance': shift.variance,
            })
        return columns, rows, {
            'shifts': len(shifts),
            'variance_total': sum(shifts.mapped('variance')),
        }

    def _data_hotel_housekeeping_status(self):
        columns = [('room', 'Room'), ('task', 'Task'),
                   ('status', 'Room Status'), ('state', 'State'),
                   ('breach', 'SLA Breach')]
        rows = []
        requests = self.env['cleaning.request'].search([
            ('company_id', '=', self.company_id.id),
        ])
        for req in requests:
            rows.append({
                'room': req.room_id.display_name,
                'task': req.task_type or '',
                'status': req.room_status or '',
                'state': req.state,
                'breach': 'Yes' if req.sla_breach else 'No',
            })
        return columns, rows, {
            'requests': len(requests),
            'breaches': len(requests.filtered(lambda r: r.sla_breach)),
        }

    def _data_hotel_flash(self):
        columns = [('date', 'Date'), ('state', 'State'),
                   ('room_nights', 'Room Nights'),
                   ('no_shows', 'No-Shows'), ('closed', 'Day Closed')]
        rows = []
        audits = self.env['hotel.night.audit'].search([
            ('company_id', '=', self.company_id.id),
            ('date', '>=', self.date_from or fields.Date.today()),
            ('date', '<=', self.date_to or fields.Date.today()),
        ])
        for audit in audits:
            closed = self.env['hotel.business.date'].is_day_closed(
                audit.date,
                company=self.company_id)
            rows.append({
                'date': str(audit.date or ''),
                'state': audit.state,
                'room_nights': audit.room_nights_posted,
                'no_shows': audit.no_show_count,
                'closed': 'Yes' if closed else 'No',
            })
        return columns, rows, {
            'room_nights': sum(audits.mapped('room_nights_posted')),
            'no_shows': sum(audits.mapped('no_show_count')),
        }

    def _data_hotel_adr_revpar(self):
        columns = [('folio', 'Folio'), ('guest', 'Guest'),
                   ('revenue', 'Revenue')]
        start, end = self._bounds()
        folios = self.env['hotel.folio'].search([
            ('company_id', '=', self.company_id.id),
            ('state', '=', 'settled'),
        ]).filtered(
            lambda f: f.booking_id and f.booking_id.checkin_date
            and start <= f.booking_id.checkin_date <= end)
        rows = [{'folio': f.name,
                 'guest': f.partner_id.display_name,
                 'revenue': f.total} for f in folios]
        revenue = sum(folios.mapped('total'))
        occupied = sum(
            max((line.checkout_date - line.checkin_date).days, 0)
            for f in folios for line in f.booking_id.room_line_ids
            if line.checkin_date and line.checkout_date) or 0
        days = max((self.date_to - self.date_from).days + 1, 1) \
            if self.date_from and self.date_to else 1
        rooms = self.env['product.template'].search_count([
            ('is_room', '=', True),
            '|', ('company_id', '=', False),
            ('company_id', '=', self.company_id.id),
        ]) or 1
        available = rooms * days
        adr = revenue / occupied if occupied else 0.0
        revpar = revenue / available if available else 0.0
        return columns, rows, {'revenue': revenue, 'adr': round(adr, 2),
                               'revpar': round(revpar, 2),
                               'occupied_nights': occupied,
                               'available_nights': available}

    def _data_hotel_asset_register(self):
        columns = [('asset', 'Asset'), ('qr', 'QR Code'),
                   ('room', 'Room'), ('state', 'State')]
        rows = []
        assets = self.env['hotel.asset'].search([
            ('company_id', '=', self.company_id.id),
        ])
        for asset in assets:
            rows.append({
                'asset': asset.name,
                'qr': asset.qr_code,
                'room': asset.room_id.display_name,
                'state': asset.state,
            })
        return columns, rows, {'assets': len(assets)}

    # ------------------------------------------------------------------
    # print actions
    # ------------------------------------------------------------------
    def action_print_pdf(self):
        self.ensure_one()
        return self.env.ref(
            'hotel_management_odoo.action_report_%s' % self.report_type
        ).report_action(self, data=self._pack_data())

    def action_print_xlsx(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.report',
            'data': {
                'model': 'hotel.report.pack',
                'options': json.dumps(self._pack_data(), default=json_default),
                'output_format': 'xlsx',
                'report_name': dict(CORE_REPORTS)[self.report_type],
            },
            'report_type': 'xlsx',
        }

    def get_xlsx_report(self, data, response):
        if isinstance(data, str):
            data = json.loads(data)
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet = workbook.add_worksheet(str(data.get('title', 'Report'))[:31])
        bold = workbook.add_format({'bold': True})
        sheet.write(0, 0, data.get('title', ''), bold)
        sheet.write(1, 0, '%s - %s' % (data.get('date_from', ''),
                                       data.get('date_to', '')))
        sheet.write(2, 0, _company_name(data.get('company', '')))
        for col, column in enumerate(data.get('columns', [])):
            sheet.write(4, col, column.get('label', ''), bold)
        for row_idx, row in enumerate(data.get('rows', [])):
            for col, column in enumerate(data.get('columns', [])):
                sheet.write(row_idx + 5, col, row.get(column.get('key'), ''))
        workbook.close()
        output.seek(0)
        response.stream.write(output.read())
        output.close()

    def _render_xlsx(self):
        """Return XLSX bytes (used by tests; mirrors get_xlsx_report)."""
        data = self._pack_data()

        class _Stream:
            def __init__(self):
                self.buf = io.BytesIO()

            def write(self, chunk):
                self.buf.write(chunk)

        class _Response:
            def __init__(self):
                self.stream = _Stream()

        response = _Response()
        self.get_xlsx_report(data, response)
        return response.stream.buf.getvalue()
