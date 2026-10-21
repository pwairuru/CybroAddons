# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError


SLOTS = [('full', 'Full Day'), ('half_am', 'Half Day AM'),
         ('half_pm', 'Half Day PM')]


def _slots_conflict(a, b):
    """Full day blocks everything; half slots block themselves + full."""
    if a == 'full' or b == 'full':
        return True
    return a == b


class HotelVenue(models.Model):
    """Bookable conference/venue space. Master under Configuration."""
    _name = 'hotel.venue'
    _description = "Hotel Venue"

    name = fields.Char(string="Name", required=True)
    company_id = fields.Many2one('res.company', string="Company",
                                 required=True, index=True,
                                 default=lambda self: self.env.company)
    capacity = fields.Integer(string="Capacity", default=0)
    flat_price = fields.Float(string="Venue Flat Price", default=0.0)
    pax_price = fields.Float(string="Price per Pax", default=0.0)
    venue_product_id = fields.Many2one('product.product',
                                       string="Venue Product")
    pax_product_id = fields.Many2one('product.product',
                                     string="Pax Product")
    active = fields.Boolean(default=True)

    @api.constrains('capacity')
    def _check_capacity(self):
        for rec in self:
            if rec.capacity < 0:
                raise ValidationError("Venue capacity cannot be negative.")


class HotelConference(models.Model):
    """Conference booking: venue slot + package explosion + routing.

    Master bill (venue flat + pax package) posts to the company folio
    with routing to_master; attendee extras post to personal folios
    with routing to_personal. POS bill-to is read-only integration:
    resolve_pos_bill_to() only reads pos.order, never writes POS code.
    """
    _name = 'hotel.conference'
    _description = "Hotel Conference"
    _order = 'date desc, id desc'

    name = fields.Char(string="Reference", default="New", index=True)
    company_id = fields.Many2one('res.company', string="Company",
                                 required=True, index=True,
                                 default=lambda self: self.env.company)
    venue_id = fields.Many2one('hotel.venue', string="Venue",
                               required=True, index=True, ondelete="restrict")
    date = fields.Date(string="Date", required=True, index=True,
                       default=fields.Date.today)
    slot = fields.Selection(SLOTS, string="Slot", required=True,
                            default='full')
    partner_id = fields.Many2one('res.partner', string="Master Bill-To",
                                 help="Company customer paying the master "
                                 "bill (venue + package).",
                                 index=True)
    pax = fields.Integer(string="Pax", default=0)
    venue_price = fields.Float(string="Venue Price", default=0.0)
    pax_price = fields.Float(string="Pax Unit Price", default=0.0)
    state = fields.Selection(
        [('draft', 'Draft'), ('confirmed', 'Confirmed'),
         ('done', 'Done'), ('cancel', 'Cancelled')],
        default='draft', required=True)
    master_folio_id = fields.Many2one('hotel.folio', string="Master Folio",
                                      readonly=True, ondelete="set null")
    attendee_ids = fields.One2many('hotel.conference.attendee',
                                   'conference_id', string="Attendees")
    master_total = fields.Float(string="Master Total",
                                compute='_compute_totals')
    personal_total = fields.Float(string="Personal Total",
                                  compute='_compute_totals')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                venue = self.env['hotel.venue'].browse(
                    vals.get('venue_id')) if vals.get('venue_id') else None
                vname = venue.name if venue and venue.exists() else 'CONF'
                vals['name'] = '%s/%s/%s' % (
                    vname, vals.get('date', ''), vals.get('slot', ''))
            if 'venue_price' not in vals or not vals.get('venue_price'):
                venue = self.env['hotel.venue'].browse(
                    vals.get('venue_id')) if vals.get('venue_id') else None
                if venue and venue.exists() and venue.flat_price:
                    vals.setdefault('venue_price', venue.flat_price)
            if 'pax_price' not in vals or not vals.get('pax_price'):
                venue = self.env['hotel.venue'].browse(
                    vals.get('venue_id')) if vals.get('venue_id') else None
                if venue and venue.exists() and venue.pax_price:
                    vals.setdefault('pax_price', venue.pax_price)
        return super().create(vals_list)

    @api.depends('master_folio_id.line_ids.quantity',
                 'master_folio_id.line_ids.price_unit',
                 'attendee_ids.personal_folio_id.line_ids.quantity',
                 'attendee_ids.personal_folio_id.line_ids.price_unit')
    def _compute_totals(self):
        """Pre-tax gross totals (sum of qty x price_unit, tax excluded).

        Matches hotel.folio.total semantics: folio lines carry tax_ids
        but the staged ledger sums untaxed amounts; taxes apply at
        settle time when the account.move is created.
        """
        for conf in self:
            master = conf.master_folio_id
            conf.master_total = sum(
                (line.quantity or 0.0) * (line.price_unit or 0.0)
                for line in master.line_ids) if master else 0.0
            conf.personal_total = sum(
                (line.quantity or 0.0) * (line.price_unit or 0.0)
                for att in conf.attendee_ids
                for line in att.personal_folio_id.line_ids
            ) if conf.attendee_ids else 0.0

    @api.constrains('venue_id', 'date', 'slot', 'company_id', 'state')
    def _check_no_double_book(self):
        for rec in self:
            if rec.state == 'cancel':
                continue
            if not rec.venue_id or not rec.date or not rec.slot:
                continue
            clash = self.search([
                ('id', '!=', rec.id),
                ('company_id', '=', rec.company_id.id),
                ('venue_id', '=', rec.venue_id.id),
                ('date', '=', rec.date),
                ('state', '!=', 'cancel'),
            ])
            for other in clash:
                if _slots_conflict(rec.slot, other.slot):
                    raise ValidationError(
                        "Venue %s is already booked on %s (%s)."
                        % (rec.venue_id.display_name, rec.date,
                           other.slot))

    @api.constrains('venue_id', 'company_id')
    def _check_company(self):
        for rec in self:
            venue_company = rec.venue_id.company_id
            if venue_company and venue_company.id != rec.company_id.id:
                raise ValidationError(
                    "Venue belongs to %s; book from that company."
                    % venue_company.display_name)

    @api.constrains('pax')
    def _check_pax(self):
        for rec in self:
            if rec.pax < 0:
                raise ValidationError("Pax cannot be negative.")

    def _service_product(self, xml_name, label):
        product = self.env['product.product'].search(
            [('sale_ok', '=', True), ('name', '=', label)], limit=1)
        if not product:
            product = self.env['product.product'].create({
                'name': label,
                'sale_ok': True,
                'purchase_ok': False,
                'type': 'service',
                'list_price': 0.0,
                'taxes_id': [(6, 0, [])],
            })
        return product

    def _venue_product(self):
        self.ensure_one()
        if self.venue_id.venue_product_id:
            return self.venue_id.venue_product_id
        return self._service_product('conf_venue',
                                     'Conference Venue Hire')

    def _pax_product(self):
        self.ensure_one()
        if self.venue_id.pax_product_id:
            return self.venue_id.pax_product_id
        return self._service_product('conf_pax', 'Conference Pax Package')

    def _ensure_master_folio(self):
        self.ensure_one()
        if self.master_folio_id:
            folio = self.master_folio_id
            if folio.company_id.id != self.company_id.id:
                raise ValidationError(
                    "Master folio belongs to %s."
                    % folio.company_id.display_name)
            return folio
        if not self.partner_id:
            raise ValidationError("Set the master bill-to before confirming.")
        folio = self.env['hotel.folio'].create({
            'partner_id': self.partner_id.id,
        })
        if folio.company_id.id != self.company_id.id:
            folio.write({'company_id': self.company_id.id})
        self.write({'master_folio_id': folio.id})
        return folio

    def action_confirm(self):
        """Block the venue slot and explode the package to master folio."""
        for conf in self:
            if conf.state == 'confirmed':
                continue
            if conf.state == 'cancel':
                raise ValidationError("Cannot confirm a cancelled booking.")
            if conf.state == 'done':
                raise ValidationError("Cannot re-confirm a done conference.")
            folio = conf._ensure_master_folio()
            charge = conf.env['hotel.charge.service']
            venue_price = conf.venue_price or conf.venue_id.flat_price or 0.0
            if venue_price <= 0:
                raise ValidationError("Venue price must be positive.")
            charge.post_charge(
                folio.id, conf._venue_product().id, 1, venue_price,
                'to_master', hotel_date=conf.date)
            if conf.pax > 0:
                pax_price = conf.pax_price or conf.venue_id.pax_price or 0.0
                if pax_price <= 0:
                    raise ValidationError("Pax price must be positive.")
                charge.post_charge(
                    folio.id, conf._pax_product().id, conf.pax, pax_price,
                    'to_master', hotel_date=conf.date)
            conf.write({'state': 'confirmed'})
        return True

    def add_attendee(self, partner_id):
        """Register an attendee with their own personal folio."""
        self.ensure_one()
        if self.state in ('cancel', 'done'):
            raise ValidationError(
                "Cannot add attendees to a %s conference." % self.state)
        partner = self.env['res.partner'].browse(partner_id)
        if not partner.exists():
            raise ValidationError("Attendee partner %s does not exist."
                                  % partner_id)
        if any(att.partner_id.id == partner.id
               for att in self.attendee_ids):
            raise ValidationError(
                "Attendee %s is already registered."
                % partner.display_name)
        if self.venue_id.capacity and \
                len(self.attendee_ids) + 1 > self.venue_id.capacity:
            raise ValidationError(
                "Venue %s holds %d; cannot add attendee %d."
                % (self.venue_id.display_name, self.venue_id.capacity,
                   len(self.attendee_ids) + 1))
        if self.pax and len(self.attendee_ids) + 1 > self.pax:
            raise ValidationError(
                "Conference is capped at %d pax." % self.pax)
        folio = self.env['hotel.folio'].create({
            'partner_id': partner.id,
        })
        if folio.company_id.id != self.company_id.id:
            folio.write({'company_id': self.company_id.id})
        attendee = self.env['hotel.conference.attendee'].create({
            'conference_id': self.id,
            'partner_id': partner.id,
            'personal_folio_id': folio.id,
        })
        return attendee

    def post_personal_extra(self, attendee_id, product_id, qty, price_unit):
        """Post an attendee bar/minibar extra to their personal folio."""
        self.ensure_one()
        attendee = self.env['hotel.conference.attendee'].browse(attendee_id)
        if not attendee.exists() or attendee.conference_id.id != self.id:
            raise ValidationError("Attendee %s is not on this conference."
                                  % attendee_id)
        folio = attendee.personal_folio_id
        if not folio:
            raise ValidationError("Attendee has no personal folio.")
        line = self.env['hotel.charge.service'].post_charge(
            folio.id, product_id, qty, price_unit, 'to_personal',
            hotel_date=self.date)
        return line

    def action_settle_master(self):
        """Settle the master folio; returns the account.move record."""
        self.ensure_one()
        folio = self.master_folio_id
        if not folio:
            raise ValidationError("No master folio to settle.")
        return folio.action_settle()

    @api.model
    def resolve_pos_bill_to(self, pos_reference):
        """Read-only POS bill-to lookup. Never writes to POS.

        Returns the partner record (or False) for a pos.order reference.
        Safe when POS is not installed: returns False.
        """
        if not pos_reference:
            return False
        if 'pos.order' not in self.env:
            return False
        order = self.env['pos.order'].search(
            [('pos_reference', '=', pos_reference)], limit=1)
        if not order:
            order = self.env['pos.order'].search(
                [('name', '=', pos_reference)], limit=1)
        if not order:
            return False
        return order.partner_id

    def action_done(self):
        """Close a confirmed conference (master settles separately)."""
        for conf in self:
            if conf.state != 'confirmed':
                raise ValidationError(
                    "Only a confirmed conference can be marked done.")
        self.write({'state': 'done'})
        return True

    def action_cancel(self):
        self.write({'state': 'cancel'})
        return True


class HotelConferenceAttendee(models.Model):
    """Conference attendee with a personal folio for extras."""
    _name = 'hotel.conference.attendee'
    _description = "Hotel Conference Attendee"

    conference_id = fields.Many2one('hotel.conference', string="Conference",
                                    required=True, ondelete="cascade",
                                    index=True)
    partner_id = fields.Many2one('res.partner', string="Attendee",
                                 required=True, index=True)
    personal_folio_id = fields.Many2one('hotel.folio',
                                        string="Personal Folio",
                                        required=True, ondelete="restrict")
    company_id = fields.Many2one('res.company', string="Company",
                                 related='conference_id.company_id',
                                 store=True, readonly=True)

    @api.constrains('personal_folio_id', 'conference_id')
    def _check_company(self):
        for rec in self:
            folio_company = rec.personal_folio_id.company_id
            conf_company = rec.conference_id.company_id
            if folio_company and conf_company and \
                    folio_company.id != conf_company.id:
                raise ValidationError(
                    "Personal folio belongs to %s."
                    % folio_company.display_name)
