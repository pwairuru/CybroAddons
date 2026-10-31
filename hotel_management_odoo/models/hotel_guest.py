# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError

BLOCK_PARAM = 'hotel.checkin.block_expired_id'

# Values that disable the expired-ID check-in gate (case-insensitive).
BLOCK_OFF_VALUES = frozenset(['0', 'false', 'no', 'off', 'none', ''])


def _id_block_enabled(env):
    """Parse the expired-ID gate flag; default on, off only on explicit
    false-like values (False/0/no/off, any case)."""
    raw = env['ir.config_parameter'].sudo().get_str(BLOCK_PARAM, '1')
    return str(raw).strip().lower() not in BLOCK_OFF_VALUES


class ResPartner(models.Model):
    """Repeat-guest profile extension.

    Adds guest flags + computed stay history on top of res.partner.
    No res.partner core behaviour changed; new fields only.
    """
    _inherit = 'res.partner'

    is_hotel_guest = fields.Boolean(string="Hotel Guest", default=False)
    nationality = fields.Char(string="Nationality", size=2)
    date_of_birth = fields.Date(string="Date of Birth")
    vip = fields.Boolean(string="VIP", default=False)
    document_ids = fields.One2many('hotel.document', 'partner_id',
                                   string="ID Documents")
    folio_ids = fields.One2many('hotel.folio', 'partner_id',
                                string="Folios")
    booking_ids = fields.One2many('room.booking', 'partner_id',
                                  string="Bookings")
    loyalty_entry_ids = fields.One2many('hotel.loyalty.entry', 'partner_id',
                                        string="Loyalty Entries")
    loyalty_points = fields.Float(string="Loyalty Points",
                                  compute='_compute_loyalty', store=True)
    stay_count = fields.Integer(string="Stays", compute='_compute_stays',
                                store=False)
    total_nights = fields.Integer(string="Nights", compute='_compute_stays',
                                  store=False)
    total_spent = fields.Float(string="Total Spent",
                               compute='_compute_stays', store=False)

    @api.depends('loyalty_entry_ids.points')
    def _compute_loyalty(self):
        for partner in self:
            partner.loyalty_points = sum(
                partner.loyalty_entry_ids.mapped('points'))

    def _stay_bookings_folios(self, order_bookings=False,
                              order_folios=False):
        """Shared stay search: bookings + folios for allowed companies."""
        self.ensure_one()
        allowed = self.env.companies.ids
        bookings = self.env['room.booking'].search(
            [('partner_id', '=', self.id),
             ('company_id', 'in', allowed)],
            order=order_bookings or None)
        folios = self.env['hotel.folio'].search(
            [('partner_id', '=', self.id),
             ('company_id', 'in', allowed)],
            order=order_folios or None)
        return bookings, folios

    def _compute_stays(self):
        for partner in self:
            bookings, folios = partner._stay_bookings_folios()
            nights = 0
            for booking in bookings:
                if booking.checkin_date and booking.checkout_date:
                    delta = (booking.checkout_date.date()
                             - booking.checkin_date.date()).days
                    nights += max(delta, 0)
            partner.stay_count = len(bookings)
            partner.total_nights = nights
            # folio.total is the ledger truth (gross + tax - deposits),
            # not a qty*price re-computation.
            partner.total_spent = sum(folios.mapped('total'))

    def get_stay_history(self):
        """Repeat-guest history following the partner record.

        Company-scoped to the current allowed companies."""
        self.ensure_one()
        bookings, folios = self._stay_bookings_folios(
            order_bookings='checkin_date desc', order_folios='id desc')
        return {
            'booking_ids': bookings.ids,
            'bookings': [{
                'id': b.id,
                'name': b.name,
                'checkin_date': b.checkin_date,
                'checkout_date': b.checkout_date,
                'state': b.state,
            } for b in bookings],
            'folio_ids': folios.ids,
            'stay_count': len(bookings),
        }

    def _expired_documents(self):
        today = fields.Date.today()
        return self.document_ids.filtered(
            lambda d: d.expiry_date and d.expiry_date < today)

    def check_documents_valid(self):
        """Expired-ID gate for check-in.

        Configurable via ir.config_parameter hotel.checkin.block_expired_id
        (default on). All rejections via ValidationError.
        """
        if not _id_block_enabled(self.env):
            return True
        expired = self._expired_documents()
        if expired:
            raise ValidationError(
                "Expired ID document(s): %s. Renew before check-in."
                % ', '.join(expired.mapped('number')))
        return True

    def get_portal_folios(self):
        """Portal folio balances for this guest, company-scoped."""
        self.ensure_one()
        allowed = set(self.env.companies.ids)
        rows = []
        for folio in self.folio_ids.sorted('id', reverse=True):
            if folio.company_id.id not in allowed:
                continue
            rows.append({
                'folio_id': folio.id,
                'state': folio.state,
                'total': folio.total,
                'deposit_total': folio.deposit_total,
                'balance': folio.amount_due,
            })
        return rows


class HotelDocumentType(models.Model):
    """ID catalogue (passport, national ID, driving licence...)."""
    _name = 'hotel.document.type'
    _description = "Hotel Document Type"
    _order = 'name'

    name = fields.Char(string="Name", required=True)
    code = fields.Char(string="Code", required=True)
    requires_expiry = fields.Boolean(string="Requires Expiry", default=True)
    company_id = fields.Many2one('res.company', string="Company",
                                 required=True, index=True,
                                 default=lambda self: self.env.company)
    active = fields.Boolean(default=True)

    _code_company_uniq = models.Constraint(
        'unique(code, company_id)',
        'Document type code must be unique per company.')


class HotelDocument(models.Model):
    """Guest ID document with expiry + police export."""
    _name = 'hotel.document'
    _description = "Hotel Guest Document"
    _order = 'expiry_date'

    partner_id = fields.Many2one('res.partner', string="Guest",
                                 required=True, ondelete="cascade",
                                 index=True)
    type_id = fields.Many2one('hotel.document.type', string="Type",
                              required=True, ondelete="restrict")
    number = fields.Char(string="Number", required=True)
    expiry_date = fields.Date(string="Expiry Date")
    issuing_country = fields.Char(string="Issuing Country", size=2)
    company_id = fields.Many2one('res.company', string="Company",
                                 required=True, index=True,
                                 default=lambda self: self.env.company)
    state = fields.Selection([('valid', 'Valid'),
                              ('expiring', 'Expiring Soon'),
                              ('expired', 'Expired')],
                             string="Status", compute='_compute_state',
                             store=True)

    @api.constrains('number')
    def _check_number(self):
        for doc in self:
            if not (doc.number or '').strip():
                raise ValidationError("Document number is required.")

    @api.depends('expiry_date')
    def _compute_state(self):
        today = fields.Date.today()
        for doc in self:
            if not doc.expiry_date:
                doc.state = 'valid'
            elif doc.expiry_date < today:
                doc.state = 'expired'
            elif (doc.expiry_date - today).days <= 30:
                doc.state = 'expiring'
            else:
                doc.state = 'valid'

    @api.model
    def export_police_report(self, company_id, date_from, date_to):
        """Police export: in-house guests + their ID numbers.

        Pure read-only rows; CSV rendering stays in the report layer.
        Company-safe: only bookings/documents of company_id.
        """
        company = self.env['res.company'].browse(company_id)
        if not company.exists():
            raise ValidationError("Company %s does not exist."
                                  % company_id)
        if company.id != self.env.company.id:
            raise ValidationError(
                "Report belongs to %s; run from that company."
                % company.display_name)
        bookings = self.env['room.booking'].search([
            ('company_id', '=', company.id),
            ('state', 'in', ('check_in', 'check_out', 'done')),
            ('checkin_date', '<=', '%s 23:59:59' % date_to),
            ('checkout_date', '>=', '%s 00:00:00' % date_from),
        ])
        rows = []
        for booking in bookings:
            docs = self.search([
                ('partner_id', '=', booking.partner_id.id),
                ('company_id', '=', company.id),
            ])
            doc = docs[:1]
            rows.append({
                'guest': booking.partner_id.display_name,
                'nationality': booking.partner_id.nationality or '',
                'doc_type': doc.type_id.code if doc else '',
                'doc_number': doc.number if doc else '',
                'doc_expiry': doc.expiry_date if doc else False,
                'checkin': booking.checkin_date,
                'checkout': booking.checkout_date,
                'room': ', '.join(
                    booking.room_line_ids.mapped('room_id.display_name')),
            })
        return rows

    @api.model
    def format_guest_message(self, template, booking_id):
        """Render an SMS/WhatsApp template for a booking.

        Placeholders: {guest} {room} {checkin} {checkout} {balance}.
        """
        booking = self.env['room.booking'].browse(booking_id)
        if not booking.exists():
            raise ValidationError("Booking %s does not exist."
                                  % booking_id)
        folios = self.env['hotel.folio'].search(
            [('booking_id', '=', booking.id),
             ('partner_id', '=', booking.partner_id.id)])
        balance = sum(f.amount_due for f in folios)
        rooms = ', '.join(
            booking.room_line_ids.mapped('room_id.display_name'))
        try:
            return template.format(
                guest=booking.partner_id.display_name,
                room=rooms,
                checkin=booking.checkin_date,
                checkout=booking.checkout_date,
                balance=balance,
            )
        except (KeyError, IndexError, ValueError) as exc:
            raise ValidationError(
                "Bad message template: %s" % exc) from exc


class HotelLoyaltyProgram(models.Model):
    """Loyalty points bridge: folio spend -> points."""
    _name = 'hotel.loyalty.program'
    _description = "Hotel Loyalty Program"
    _order = 'name'

    name = fields.Char(string="Name", required=True)
    points_per_1000 = fields.Float(string="Points per 1000",
                                   default=10.0, required=True)
    company_id = fields.Many2one('res.company', string="Company",
                                 required=True, index=True,
                                 default=lambda self: self.env.company)
    active = fields.Boolean(default=True)
    entry_ids = fields.One2many('hotel.loyalty.entry', 'program_id',
                                string="Entries")

    @api.constrains('points_per_1000')
    def _check_rate(self):
        for program in self:
            if program.points_per_1000 < 0:
                raise ValidationError("Points rate cannot be negative.")

    def accrue_for_folio(self, folio):
        """Credit points from folio gross. Company-safe.

        Idempotent on (program, folio): a second call returns the
        existing entry instead of double-crediting.
        """
        self.ensure_one()
        if folio.company_id.id != self.company_id.id:
            raise ValidationError(
                "Folio belongs to %s; accrue from the %s program."
                % (folio.company_id.display_name,
                   self.company_id.display_name))
        existing = self.env['hotel.loyalty.entry'].search([
            ('program_id', '=', self.id),
            ('folio_id', '=', folio.id),
        ], limit=1)
        if existing:
            return existing
        gross = folio.total
        if gross <= 0:
            raise ValidationError("Nothing to accrue on this folio.")
        points = round(gross / 1000.0 * self.points_per_1000, 2)
        return self.env['hotel.loyalty.entry'].create({
            'program_id': self.id,
            'partner_id': folio.partner_id.id,
            'folio_id': folio.id,
            'points': points,
            'company_id': self.company_id.id,
        })

    def redeem(self, partner, points):
        """Debit points; rejects overdraft via ValidationError.

        Balance is company-scoped to this program's company so points
        earned elsewhere never fund a redemption here."""
        self.ensure_one()
        if points <= 0:
            raise ValidationError("Redeem a positive point amount.")
        balance = sum(self.env['hotel.loyalty.entry'].search(
            [('program_id', '=', self.id),
             ('partner_id', '=', partner.id),
             ('company_id', '=', self.company_id.id)]).mapped('points'))
        if points > balance:
            raise ValidationError(
                "Insufficient points: %s available, %s requested."
                % (balance, points))
        return self.env['hotel.loyalty.entry'].create({
            'program_id': self.id,
            'partner_id': partner.id,
            'points': -points,
            'company_id': self.company_id.id,
        })


class HotelLoyaltyEntry(models.Model):
    """Points ledger line (earn positive, redeem negative)."""
    _name = 'hotel.loyalty.entry'
    _description = "Hotel Loyalty Entry"
    _order = 'id desc'

    _program_folio_uniq = models.Constraint(
        'unique(program_id, folio_id)',
        'Points already accrued for this folio/program.')

    program_id = fields.Many2one('hotel.loyalty.program', string="Program",
                                 ondelete="cascade")
    partner_id = fields.Many2one('res.partner', string="Guest",
                                 required=True, ondelete="cascade",
                                 index=True)
    folio_id = fields.Many2one('hotel.folio', string="Folio",
                               ondelete="set null")
    points = fields.Float(string="Points", required=True)
    company_id = fields.Many2one('res.company', string="Company",
                                 required=True, index=True,
                                 default=lambda self: self.env.company)
