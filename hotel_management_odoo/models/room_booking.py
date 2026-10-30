# -*- coding: utf-8 -*-
#############################################################################
#
#    Cybrosys Technologies Pvt. Ltd.
#
#    Copyright (C) 2026-TODAY Cybrosys Technologies(<https://www.cybrosys.com>)
#    Author: Cybrosys Techno Solutions(<https://www.cybrosys.com>)
#
#    You can modify it under the terms of the GNU LESSER
#    GENERAL PUBLIC LICENSE (LGPL v3), Version 3.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU LESSER GENERAL PUBLIC LICENSE (LGPL v3) for more details.
#
#    You should have received a copy of the GNU LESSER GENERAL PUBLIC LICENSE
#    (LGPL v3) along with this program.
#    If not, see <http://www.gnu.org/licenses/>.
#
#############################################################################
from datetime import datetime, timedelta
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class RoomBooking(models.Model):
    """Model that handles the hotel room booking and all operations related
     to booking"""
    _name = "room.booking"
    _description = "Hotel Room Reservation"
    _inherit = ['mail.thread', 'mail.activity.mixin', 'avatar.mixin']

    name = fields.Char(string="Folio Number", readonly=True, index=True,
                       default="New", help="Name of Folio")
    company_id = fields.Many2one('res.company', string="Company",
                                 help="Choose the Company",
                                 required=True, index=True,
                                 default=lambda self: self.env.company)
    partner_id = fields.Many2one('res.partner', string="Customer",
                                 help="Customers of hotel",
                                 required=True, index=True, tracking=1,
                                 domain="[('type', '!=', 'private'),"
                                        " ('company_id', 'in', "
                                        "(False, company_id))]")
    date_order = fields.Datetime(string="Order Date",
                                 required=True, copy=False,
                                 help="Creation date of draft/sent orders,"
                                      " Confirmation date of confirmed orders",
                                 default=fields.Datetime.now)
    is_checkin = fields.Boolean(default=False, string="Is Checkin",
                                help="sets to True if the room is occupied")
    maintenance_request_sent = fields.Boolean(default=False,
                                              string="Maintenance Request sent"
                                                     "or Not",
                                              help="sets to True if the "
                                                   "maintenance request send "
                                                   "once")
    checkin_date = fields.Datetime(string="Check In",
                                    help="Date of Checkin",
                                    default=fields.Datetime.now,
                                    tracking=True)
    checkout_date = fields.Datetime(
        string="Check Out", help="Date of Checkout", tracking=True,
        default=lambda self: fields.Datetime.now() + timedelta(
            hours=23, minutes=59, seconds=59))
    actual_checkout_date = fields.Datetime(
        string="Actual Check-Out",
        help="When the guest really left; the booked Check Out above "
             "is never mutated so history and audit stay intact.",
        readonly=True, copy=False)
    hotel_policy = fields.Selection([("prepaid", "On Booking"),
                                     ("manual", "On Check In"),
                                     ("picking", "On Checkout"),
                                     ],
                                    default="manual", string="Hotel Policy",
                                    help="Hotel policy for payment that "
                                         "either the guest has to pay at "
                                         "booking time, check-in "
                                         "or check-out time.", tracking=True)
    duration = fields.Integer(string="Duration in Days",
                               compute='_compute_duration', store=True,
                               readonly=True, tracking=True,
                               help="Nights between check-in and check-out.")
    invoice_button_visible = fields.Boolean(string='Invoice Button Display',
                                            help="Invoice button will be "
                                                 "visible if this button is "
                                                 "True")
    invoice_status = fields.Selection(
        selection=[('no_invoice', 'Nothing To Invoice'),
                   ('to_invoice', 'To Invoice'),
                   ('invoiced', 'Invoiced'),
                   ('paid', 'Paid')], string="Invoice Status",
        help="Status of the Invoice",
        compute='_compute_invoice_count',
        default='no_invoice', tracking=True)
    hotel_invoice_id = fields.Many2one("account.move",
                                       string="Invoice",
                                       help="Indicates the invoice",
                                       copy=False)
    need_service = fields.Boolean(default=False, string="Need Service",
                                  help="Check if a Service to be added with"
                                       " the Booking")
    need_fleet = fields.Boolean(default=False, string="Need Vehicle",
                                help="Check if a Fleet to be"
                                     " added with the Booking")
    need_food = fields.Boolean(default=False, string="Need Food",
                               help="Check if a Food to be added with"
                                    " the Booking")
    need_event = fields.Boolean(default=False, string="Need Event",
                                help="Check if a Event to be added with"
                                     " the Booking")
    service_line_ids = fields.One2many("service.booking.line",
                                       "booking_id",
                                       string="Service",
                                       help="Hotel services details provided to"
                                            "Customer and it will included in "
                                            "the main Invoice.")
    event_line_ids = fields.One2many("event.booking.line",
                                     'booking_id',
                                     string="Event",
                                     help="Hotel event reservation detail.")
    vehicle_line_ids = fields.One2many("fleet.booking.line",
                                       "booking_id",
                                       string="Vehicle",
                                       help="Hotel fleet reservation detail.")
    room_line_ids = fields.One2many("room.booking.line",
                                    "booking_id", string="Room",
                                    help="Hotel room reservation detail.")
    food_order_line_ids = fields.One2many("food.booking.line",
                                          "booking_id",
                                          string='Food',
                                          help="Food details provided"
                                               " to Customer and"
                                               " it will included in the "
                                               "main invoice.", )
    state = fields.Selection(selection=[('draft', 'Draft'),
                                             ('reserved', 'Reserved'),
                                             ('check_in', 'Check In'),
                                             ('check_out', 'Check Out'),
                                             ('cancel', 'Cancelled'),
                                             ('done', 'Done')], string='State',
                              help="State of the Booking. Server-side "
                                   "transitions only (action methods); direct "
                                   "writes are rejected.",
                              default='draft', tracking=True, readonly=True)
    invoice_address_id = fields.Many2one(
        comodel_name='res.partner', string="Invoice Address",
        compute='_compute_invoice_address_id', store=True, readonly=False,
        domain="['|', ('company_id', '=', False), "
               "('company_id', '=', company_id)]",
        help="Invoice recipient; defaults to the customer.")
    @api.depends('checkin_date', 'checkout_date')
    def _compute_duration(self):
        for rec in self:
            if rec.checkin_date and rec.checkout_date \
                    and rec.checkout_date > rec.checkin_date:
                rec.duration = (rec.checkout_date.date()
                                - rec.checkin_date.date()).days or 1
            else:
                rec.duration = 0

    @api.model
    def _default_pricelist(self):
        """Company pricelist default (search only — never create inside
        a default: creation races under concurrency)."""
        pricelist = self.env['product.pricelist'].search(
            [('company_id', 'in', (False, self.env.company.id))], limit=1)
        return pricelist or False

    # hotel_pos_extension overrides _compute_has_pos_orders with real
    # POS logic; base stays False so the POS page hides without POS.
    has_pos_orders = fields.Boolean(
        compute='_compute_has_pos_orders', string='Has POS Orders',
        help='Indicates if there are POS orders linked to this booking')

    def _compute_has_pos_orders(self):
        for rec in self:
            rec.has_pos_orders = False

    @api.model
    def _company_pricelist(self, company):
        pricelist = self.env['product.pricelist'].search(
            [('company_id', 'in', (False, company.id))], limit=1)
        if not pricelist:
            pricelist = self.env['product.pricelist'].create({
                'name': 'Default %s' % (company.currency_id.name or ''),
                'currency_id': company.currency_id.id,
                'company_id': company.id,
            })
        return pricelist

    pricelist_id = fields.Many2one(comodel_name='product.pricelist',
                                   string="Pricelist",
                                   compute='_compute_pricelist_id',
                                   store=True, readonly=False,
                                   required=True, precompute=True,
                                   default=_default_pricelist,
                                   tracking=1,
                                   help="If you change the pricelist,"
                                        " only newly added lines"
                                        " will be affected.")
    currency_id = fields.Many2one(
        string="Currency", help="This is the Currency used",
        related='pricelist_id.currency_id',
        depends=['pricelist_id.currency_id'],
    )
    invoice_count = fields.Integer(compute='_compute_invoice_count',
                                   string="Invoice "
                                          "Count",
                                   help="The number of invoices created")
    payment_count = fields.Integer(compute='_compute_invoice_count',
                                   string="Payment Count",
                                   help="Payments linked to this booking "
                                        "or its folios.")
    amount_due = fields.Float(compute='_compute_invoice_count',
                              string="Amount Due",
                              help="Residual of posted invoices linked "
                                   "to this booking or its folios.")
    account_move = fields.Integer(string='Invoice Id',
                                  help="Id of the invoice created")
    amount_untaxed = fields.Monetary(string="Total Untaxed Amount",
                                     help="This indicates the total untaxed "
                                          "amount", store=True,
                                     compute='_compute_amount_untaxed',
                                     tracking=5)
    amount_tax = fields.Monetary(string="Taxes", help="Total Tax Amount",
                                 store=True, compute='_compute_amount_untaxed')
    amount_total = fields.Monetary(string="Total", store=True,
                                   help="The total Amount including Tax",
                                   compute='_compute_amount_untaxed',
                                   tracking=4)
    # Port fix 20.0: breakdown fields must be stored like the totals they share
    # _compute_amount_untaxed with (Odoo 20 rejects mixed store in one compute).
    amount_untaxed_room = fields.Monetary(string="Room Untaxed",
                                          help="Untaxed Amount for Room",
                                          compute='_compute_amount_untaxed',
                                          store=True, tracking=5)
    amount_untaxed_food = fields.Monetary(string="Food Untaxed",
                                          help="Untaxed Amount for Food",
                                          compute='_compute_amount_untaxed',
                                          store=True, tracking=5)
    amount_untaxed_event = fields.Monetary(string="Event Untaxed",
                                            help="Untaxed Amount for Event",
                                            compute='_compute_amount_untaxed',
                                            store=True, tracking=5)
    amount_untaxed_service = fields.Monetary(
        string="Service Untaxed", help="Untaxed Amount for Service",
        compute='_compute_amount_untaxed', store=True, tracking=5)
    amount_untaxed_fleet = fields.Monetary(string="Amount Untaxed",
                                            help="Untaxed amount for Fleet",
                                            compute='_compute_amount_untaxed',
                                            store=True, tracking=5)
    amount_taxed_room = fields.Monetary(string="Rom Tax", help="Tax for Room",
                                        compute='_compute_amount_untaxed',
                                        store=True, tracking=5)
    amount_taxed_food = fields.Monetary(string="Food Tax", help="Tax for Food",
                                        compute='_compute_amount_untaxed',
                                        store=True, tracking=5)
    amount_taxed_event = fields.Monetary(string="Event Tax",
                                          help="Tax for Event",
                                          compute='_compute_amount_untaxed',
                                          store=True, tracking=5)
    amount_taxed_service = fields.Monetary(string="Service Tax",
                                            compute='_compute_amount_untaxed',
                                            store=True,
                                            help="Tax for Service",
                                            tracking=5)
    amount_taxed_fleet = fields.Monetary(string="Fleet Tax",
                                          compute='_compute_amount_untaxed',
                                          store=True, tracking=5)
    amount_total_room = fields.Monetary(string="Total Amount for Room",
                                        compute='_compute_amount_untaxed',
                                        store=True,
                                        help="This is the Total Amount for "
                                             "Room", tracking=5)
    amount_total_food = fields.Monetary(string="Total Amount for Food",
                                        compute='_compute_amount_untaxed',
                                        store=True,
                                        help="This is the Total Amount for "
                                             "Food", tracking=5)
    amount_total_event = fields.Monetary(string="Total Amount for Event",
                                          compute='_compute_amount_untaxed',
                                          store=True,
                                          help="This is the Total Amount for "
                                               "Event", tracking=5)
    amount_total_service = fields.Monetary(
        string="Total Amount for Service",
        compute='_compute_amount_untaxed', store=True,
        help="This is the Total Amount for Service", tracking=5)
    amount_total_fleet = fields.Monetary(string="Total Amount for Fleet",
                                        compute='_compute_amount_untaxed',
                                        store=True,
                                        help="This is the Total Amount for "
                                             "Fleet", tracking=5)
    @api.model
    def _resolve_pricelist(self, partner, company):
        """Pricelist for a partner/company: partner property first,
        else a company-currency pricelist (created if missing)."""
        pricelist = partner.with_company(
            company).property_product_pricelist
        if not pricelist:
            pricelist = self._company_pricelist(company)
        return pricelist

    @api.model
    def _search_pricelist(self, partner, company):
        """Search-only variant for computes (no creation inside a
        computed field)."""
        pricelist = partner.with_company(
            company).property_product_pricelist
        if not pricelist:
            pricelist = self.env['product.pricelist'].search(
                [('company_id', 'in', (False, company.id))], limit=1)
        return pricelist

    @api.model_create_multi
    def create(self, vals_list):
        """Sequence Generation + pricelist fill (stored computed fields
        INSERT before computing, so a required computed field must be
        present in vals or the INSERT hits NOT NULL)."""
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'room.booking')
            if not vals.get('pricelist_id'):
                company = self.env['res.company'].browse(
                    vals.get('company_id')) or self.env.company
                if vals.get('partner_id'):
                    partner = self.env['res.partner'].browse(
                        vals['partner_id'])
                    if partner.exists():
                        vals['pricelist_id'] = self._resolve_pricelist(
                            partner, company).id
                if not vals.get('pricelist_id'):
                    vals['pricelist_id'] = self._company_pricelist(
                        company).id
        return super().create(vals_list)

    @api.depends('partner_id', 'company_id')
    def _compute_invoice_address_id(self):
        """Computes the invoice address from the customer, falling
        back to the customer itself (never False)."""
        for order in self:
            address = False
            if order.partner_id:
                address = order.partner_id.address_get(
                    ['invoice', 'contact']).get('invoice')
            order.invoice_address_id = address or order.partner_id

    def _folio_domain(self):
        self.ensure_one()
        folios = self.env['hotel.folio'].search(
            [('booking_id', '=', self.id)])
        return folios

    def _ensure_folio(self):
        """Find-or-create the open folio for this booking (room scope).

        Copies partner, company and hotel_policy (policy_snapshot) so the
        statement banner stays frozen even if the booking policy changes.
        """
        self.ensure_one()
        folio = self.env['hotel.folio'].search([
            ('booking_id', '=', self.id),
            ('state', '=', 'open'),
        ], limit=1)
        if folio:
            return folio
        folio = self.env['hotel.folio'].create({
            'partner_id': self.partner_id.id,
            'booking_id': self.id,
            'company_id': self.company_id.id,
            'policy_snapshot': self.hotel_policy or False,
        })
        self.message_post(
            body="Folio %s created (policy %s)."
            % (folio.id, folio.policy_snapshot or '-'))
        return folio

    def _payment_domain(self):
        """Domain covering payments/moves linked to this booking directly
        or via any of its folios."""
        self.ensure_one()
        folio_ids = self.env['hotel.folio'].search(
            [('booking_id', '=', self.id)]).ids
        if folio_ids:
            return ['|', ('hotel_booking_id', '=', self.id),
                    ('hotel_folio_id', 'in', folio_ids)]
        return [('hotel_booking_id', '=', self.id)]

    def _compute_invoice_count(self):
        """Compute invoice/payment counts, amount due and invoice status
        via booking + folio links."""
        for record in self:
            folio_ids = self.env['hotel.folio'].search(
                [('booking_id', '=', record.id)]).ids
            if folio_ids:
                domain = ['|', ('hotel_booking_id', '=', record.id),
                          ('hotel_folio_id', 'in', folio_ids)]
            else:
                domain = [('hotel_booking_id', '=', record.id)]
            # Count only (no content): the booking form renders for
            # reception, who has no direct journal access.
            Move = self.env['account.move'].sudo()
            record.invoice_count = Move.search_count(domain)
            posted = Move.search(domain + [('move_type', '=', 'out_invoice'),
                                           ('state', '=', 'posted')])
            record.payment_count = self.env['account.payment'].sudo() \
                .search_count(domain)
            record.amount_due = sum(posted.mapped('amount_residual'))
            if posted:
                if all(m.payment_state == 'paid' for m in posted):
                    record.invoice_status = 'paid'
                else:
                    record.invoice_status = 'invoiced'
            elif folio_ids and self.env['hotel.folio.line'].search_count(
                    [('folio_id', 'in', folio_ids)]):
                record.invoice_status = 'to_invoice'
            else:
                record.invoice_status = 'no_invoice'

    @api.depends('partner_id', 'company_id')
    def _compute_pricelist_id(self):
        """Computes PriceList (search only; creation happens in
        create()/write() so computes stay side-effect free)."""
        for order in self:
            if order.pricelist_id:
                continue
            company = order.company_id or self.env.company
            pricelist = self._search_pricelist(order.partner_id, company) \
                if order.partner_id else self.env[
                    'product.pricelist'].search(
                        [('company_id', 'in', (False, company.id))],
                        limit=1)
            order.pricelist_id = pricelist or order.pricelist_id

    @api.depends('room_line_ids.price_subtotal', 'room_line_ids.price_tax',
                 'room_line_ids.price_total',
                 'food_order_line_ids.price_subtotal',
                 'food_order_line_ids.price_tax',
                 'food_order_line_ids.price_total',
                 'service_line_ids.price_subtotal',
                 'service_line_ids.price_tax', 'service_line_ids.price_total',
                 'vehicle_line_ids.price_subtotal',
                 'vehicle_line_ids.price_tax', 'vehicle_line_ids.price_total',
                 'event_line_ids.price_subtotal', 'event_line_ids.price_tax',
                 'event_line_ids.price_total',
                 )
    def _compute_amount_untaxed(self):
        """Pure totals over booking lines (no invoice queries, no
        side effects — safe inside @api.depends)."""
        for record in self:
            # Rooms
            record.amount_untaxed_room = sum(
                record.room_line_ids.mapped('price_subtotal'))
            record.amount_taxed_room = sum(
                record.room_line_ids.mapped('price_tax'))
            record.amount_total_room = sum(
                record.room_line_ids.mapped('price_total'))
            # Food
            record.amount_untaxed_food = sum(
                record.food_order_line_ids.mapped('price_subtotal'))
            record.amount_taxed_food = sum(
                record.food_order_line_ids.mapped('price_tax'))
            record.amount_total_food = sum(
                record.food_order_line_ids.mapped('price_total'))
            # Service
            record.amount_untaxed_service = sum(
                record.service_line_ids.mapped('price_subtotal'))
            record.amount_taxed_service = sum(
                record.service_line_ids.mapped('price_tax'))
            record.amount_total_service = sum(
                record.service_line_ids.mapped('price_total'))
            # Fleet
            record.amount_untaxed_fleet = sum(
                record.vehicle_line_ids.mapped('price_subtotal'))
            record.amount_taxed_fleet = sum(
                record.vehicle_line_ids.mapped('price_tax'))
            record.amount_total_fleet = sum(
                record.vehicle_line_ids.mapped('price_total'))
            # Event
            record.amount_untaxed_event = sum(
                record.event_line_ids.mapped('price_subtotal'))
            record.amount_taxed_event = sum(
                record.event_line_ids.mapped('price_tax'))
            record.amount_total_event = sum(
                record.event_line_ids.mapped('price_total'))

            record.amount_untaxed = (record.amount_untaxed_room
                                     + record.amount_untaxed_food
                                     + record.amount_untaxed_fleet
                                     + record.amount_untaxed_event
                                     + record.amount_untaxed_service)
            record.amount_tax = (record.amount_taxed_room
                                 + record.amount_taxed_food
                                 + record.amount_taxed_fleet
                                 + record.amount_taxed_event
                                 + record.amount_taxed_service)
            record.amount_total = record.amount_untaxed + record.amount_tax

    def _to_invoice_lines(self):
        """Booking lines minus what hotel_booking_id invoices already
        cover. Separate from the totals compute so stored amounts never
        depend on invoice state."""
        self.ensure_one()
        invoiced = {}
        for aml in self.env['account.move.line'].search([
                ('move_id.hotel_booking_id', '=', self.id),
                ('display_type', '!=', 'payment_term')]):
            key = (aml.name, aml.price_unit, aml.product_type)
            invoiced[key] = invoiced.get(key, 0.0) + aml.quantity
        pending = []

        def _delta(name, qty, price, ptype):
            return max(0.0, qty - invoiced.get((name, price, ptype), 0.0))

        for room in self.room_line_ids:
            qty = _delta(room.room_id.name, room.uom_qty,
                         room.price_unit, 'room')
            if qty > 0:
                pending.append({'name': room.room_id.name, 'quantity': qty,
                                'price_unit': room.price_unit,
                                'product_type': 'room',
                                'product_id':
                                room.room_id.product_variant_id.id,
                                'tax_ids': room.tax_ids.ids})
        for food in self.food_order_line_ids:
            qty = _delta(food.food_id.name, food.uom_qty,
                         food.price_unit, 'food')
            if qty > 0:
                pending.append({'name': food.food_id.name, 'quantity': qty,
                                'price_unit': food.price_unit,
                                'product_type': 'food',
                                'product_id': False,
                                'tax_ids': food.tax_ids.ids})
        for service in self.service_line_ids:
            qty = _delta(service.service_id.name, service.uom_qty,
                         service.price_unit, 'service')
            if qty > 0:
                pending.append({'name': service.service_id.name,
                                'quantity': qty,
                                'price_unit': service.price_unit,
                                'product_type': 'service',
                                'product_id': False,
                                'tax_ids': service.tax_ids.ids})
        for fleet in self.vehicle_line_ids:
            qty = _delta(fleet.fleet_id.name, fleet.uom_qty,
                         fleet.price_unit, 'fleet')
            if qty > 0:
                pending.append({'name': fleet.fleet_id.name, 'quantity': qty,
                                'price_unit': fleet.price_unit,
                                'product_type': 'fleet',
                                'product_id': False,
                                'tax_ids': fleet.tax_ids.ids})
        for event in self.event_line_ids:
            qty = _delta(event.event_id.name, event.uom_qty,
                         event.price_unit, 'event')
            if qty > 0:
                pending.append({'name': event.event_id.name, 'quantity': qty,
                                'price_unit': event.price_unit,
                                'product_type': 'event',
                                'product_id': False,
                                'tax_ids': event.tax_ids.ids})
        return pending

    @api.onchange('need_food')
    def _onchange_need_food(self):
        """Unlink Food Booking Line if Need Food is false"""
        if not self.need_food and self.food_order_line_ids \
                and self.state in ('draft', 'reserved', 'check_in'):
            self.food_order_line_ids = [
                (2, line.id, 0) for line in self.food_order_line_ids
                if line.id]

    @api.onchange('need_service')
    def _onchange_need_service(self):
        """Unlink Service Booking Line if Need Service is False"""
        if not self.need_service and self.service_line_ids \
                and self.state in ('draft', 'reserved', 'check_in'):
            self.service_line_ids = [
                (2, line.id, 0) for line in self.service_line_ids
                if line.id]

    @api.onchange('need_fleet')
    def _onchange_need_fleet(self):
        """Unlink Fleet Booking Line if Need Fleet is False"""
        if not self.need_fleet and self.vehicle_line_ids \
                and self.state in ('draft', 'reserved', 'check_in'):
            self.vehicle_line_ids = [
                (2, line.id, 0) for line in self.vehicle_line_ids
                if line.id]

    @api.onchange('need_event')
    def _onchange_need_event(self):
        """Unlink Event Booking Line if Need Event is False"""
        if not self.need_event and self.event_line_ids \
                and self.state in ('draft', 'reserved', 'check_in'):
            self.event_line_ids = [
                (2, line.id, 0) for line in self.event_line_ids
                if line.id]

    @api.onchange('food_order_line_ids', 'room_line_ids',
                  'service_line_ids', 'vehicle_line_ids', 'event_line_ids')
    def _onchange_room_line_ids(self):
        """Reset the invoice flag when lines change."""
        self.invoice_button_visible = False

    _STATE_TRANSITIONS = {
        'draft': ('reserved', 'cancel'),
        'reserved': ('check_in', 'cancel'),
        'check_in': ('check_out',),
        'check_out': ('done',),
        'cancel': (),
        'done': (),
    }

    def _check_transition(self, target):
        for rec in self:
            allowed = self._STATE_TRANSITIONS.get(rec.state, ())
            if target not in allowed:
                raise ValidationError(
                    _("Cannot move booking %s from %s to %s.")
                    % (rec.name, rec.state, target))

    def write(self, vals):
        """State is server-authoritative: only action methods move it.
        Pricelist follows the customer unless explicitly set."""
        if 'state' in vals and not self.env.context.get(
                'hotel_allow_state_write'):
            raise ValidationError(
                _("State changes must go through Reserve / Check-In / "
                  "Check-Out / Done / Cancel actions."))
        if ('partner_id' in vals or 'company_id' in vals) \
                and 'pricelist_id' not in vals:
            for rec in self:
                partner = self.env['res.partner'].browse(
                    vals.get('partner_id', rec.partner_id.id))
                company = self.env['res.company'].browse(
                    vals.get('company_id', rec.company_id.id))
                if partner.exists() and company.exists():
                    vals = dict(
                        vals,
                        pricelist_id=self._resolve_pricelist(
                            partner, company).id)
                    break
        return super().write(vals)

    def _room_held_elsewhere(self, room, states=('reserved', 'check_in')):
        """True if another booking actively holds this room."""
        return bool(self.env['room.booking.line'].search([
            ('room_id', '=', room.id),
            ('booking_id.state', 'in', list(states)),
            ('booking_id', 'not in', self.ids),
        ], limit=1))

    def _release_rooms(self):
        """Free rooms no other active booking holds (status + flag kept
        in sync — single writer)."""
        rooms = self.mapped('room_line_ids.room_id')
        for room in rooms:
            if not self._room_held_elsewhere(room):
                # System side-effect of the booking flow (reception has
                # no direct room write): sudo only this status flip.
                room.sudo().write(
                    {'status': 'available', 'is_room_avail': True})

    def _hold_rooms(self, status):
        for room in self.mapped('room_line_ids.room_id'):
            # Same sudo-scoped status flip as _release_rooms.
            room.sudo().write({'status': status, 'is_room_avail': False})

    @api.model
    def _check_room_available(self, room, checkin, checkout,
                              ignore_booking=False):
        """Server-side availability: overlap + OOO + dirty. View domains
        are UX only; this is the enforcement point."""
        booking_domain = [
            ('room_id', '=', room.id),
            ('booking_id.state', 'in', ('reserved', 'check_in')),
            ('checkin_date', '<', checkout),
            ('checkout_date', '>', checkin),
        ]
        if ignore_booking:
            booking_domain.append(('booking_id', '!=', ignore_booking.id))
        clash = self.env['room.booking.line'].search(booking_domain,
                                                     limit=1)
        if clash:
            raise ValidationError(
                _("Room %s is already booked %s - %s (booking %s).")
                % (room.display_name, clash.checkin_date,
                   clash.checkout_date, clash.booking_id.name))
        ooo = self.env['maintenance.request'].search([
            ('type', '=', 'room'),
            ('state', 'not in', ('done', 'cancel')),
            ('room_maintenance_ids', 'in', room.id),
        ], limit=1)
        if ooo:
            raise ValidationError(
                _("Room %s is out of order (%s).")
                % (room.display_name, ooo.sequence or ooo.name))
        dirty = self.env['cleaning.request'].search([
            ('cleaning_type', '=', 'room'),
            ('room_id', '=', room.id),
            ('state', 'not in', ('done',)),
            '|', ('room_status', '=', False),
            ('room_status', 'not in', ('clean', 'inspected')),
        ], limit=1)
        if dirty:
            raise ValidationError(
                _("Room %s is dirty (%s); clean it first.")
                % (room.display_name, dirty.sequence))

    @api.constrains("room_line_ids")
    def _check_duplicate_folio_room_line(self):
        """
        This method is used to validate the room_lines.
        ------------------------------------------------
        @param self: object pointer
        @return: raise warning depending on the validation
        """
        for record in self:
            # Create a set of unique ids
            ids = set()
            for line in record.room_line_ids:
                if line.room_id.id in ids:
                    raise ValidationError(
                        (
                            """Room Entry Duplicates Found!, """
                            """You Cannot Book "%s" Room More Than Once!"""
                        )
                        % line.room_id.name
                    )
                ids.add(line.room_id.id)

    def action_reserve(self):
        """Button Reserve Function"""
        for record in self:
            record._check_transition('reserved')
            if not record.room_line_ids:
                raise ValidationError(("Please Enter Room Details"))
            if not record.checkin_date or not record.checkout_date \
                    or record.checkout_date <= record.checkin_date:
                raise ValidationError(
                    ("Check-out must be after check-in."))
            for line in record.room_line_ids:
                self._check_room_available(
                    line.room_id, line.checkin_date, line.checkout_date,
                    ignore_booking=record)
            record._hold_rooms('reserved')
            record.room_line_ids._compute_rate_snapshot()
            record.with_context(hotel_allow_state_write=True).write(
                {"state": "reserved"})
            record._ensure_folio()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'message': "Rooms reserved Successfully!",
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }

    def action_cancel(self):
        """
        @param self: object pointer
        """
        for record in self:
            record._check_transition('cancel')
            folios = self.env['hotel.folio'].search(
                [('booking_id', '=', record.id)])
            open_folios = folios.filtered(lambda f: f.state == 'open')
            if open_folios.mapped('deposit_ids').filtered(
                    lambda d: d.state in ('draft', 'applied')):
                raise ValidationError(
                    _("Cannot cancel booking %s: its folio holds "
                      "deposits; refund or settle them first.")
                    % record.name)
            if folio_ids := folios.ids:
                domain = ['|', ('hotel_booking_id', '=', record.id),
                          ('hotel_folio_id', 'in', folio_ids)]
            else:
                domain = [('hotel_booking_id', '=', record.id)]
            posted = self.env['account.move'].search(
                domain).filtered(lambda m: m.state == 'posted')
            if posted:
                raise ValidationError(
                    _("Cannot cancel booking %s: posted invoices exist "
                      "(%s).") % (record.name, ', '.join(
                          posted.mapped(lambda m: m.name or 'Draft'))))
            for folio in open_folios:
                folio_posted = self.env['account.move'].search_count([
                    ('hotel_folio_id', '=', folio.id),
                    ('state', '=', 'posted'),
                ])
                if folio.state != 'open' or folio_posted:
                    raise ValidationError(
                        _("Cannot cancel booking %s: folio %s is not "
                          "voidable (posted invoices exist).")
                        % (record.name, folio.id))
                folio.action_void()
            record._release_rooms()
            record.with_context(hotel_allow_state_write=True).write(
                {"state": "cancel"})

    def action_maintenance_request(self):
        """
        Function that handles the maintenance request
        """
        rooms = self.mapped('room_line_ids.room_id')
        if not rooms:
            raise ValidationError(("Please Enter Room Details"))
        existing = self.env['maintenance.request'].search([
            ('type', '=', 'room'),
            ('state', 'not in', ('done', 'cancel')),
            ('room_maintenance_ids', 'in', rooms.ids),
        ], limit=1)
        if existing:
            raise ValidationError(
                _("An open maintenance request already covers these "
                  "rooms (%s).") % (existing.sequence or existing.name))
        self.env['maintenance.request'].with_company(
            self.company_id).sudo().create({
                'name': 'Maintenance Request - %s' % self.name,
                'date': fields.Date.today(),
                'state': 'draft',
                'type': 'room',
                'room_maintenance_ids': rooms.ids,
                'is_hotel': True,
            })
        self.maintenance_request_sent = True
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'message': "Maintenance Request Sent Successfully",
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }

    def action_done(self):
        """Button action_confirm function"""
        for record in self:
            record._check_transition('done')
            folio_ids = self.env['hotel.folio'].search(
                [('booking_id', '=', record.id)]).ids
            # sudo(): reception has no journal access, so a plain search
            # would see zero moves and let an unpaid Done slip through.
            if folio_ids:
                moves = self.env['account.move'].sudo().search(
                    ['|', ('hotel_booking_id', '=', record.id),
                     ('hotel_folio_id', 'in', folio_ids),
                     ('move_type', '=', 'out_invoice')])
            else:
                moves = self.env['account.move'].sudo().search(
                    [('hotel_booking_id', '=', record.id),
                     ('move_type', '=', 'out_invoice')])
            unpaid_moves = moves.filtered(
                lambda m: m.state == 'posted'
                and m.payment_state in ('not_paid', 'partial'))
            has_ledger = bool(self.env['hotel.city.ledger'].sudo().search(
                [('folio_id', 'in', folio_ids), ('state', '=', 'open')],
                limit=1)) if folio_ids else False
            if unpaid_moves and not has_ledger:
                invoice_names = ', '.join(
                    unpaid_moves.mapped(lambda m: m.name or 'Draft'))
                raise ValidationError(
                    ('Your Invoice (%s) is Due for Payment.')
                    % invoice_names)
            record._release_rooms()
            record.with_context(hotel_allow_state_write=True).write(
                {"state": "done", "is_checkin": False})
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'message': "Booking Checked Out Successfully!",
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }

    def action_checkout(self):
        """Check out: clears uninvoiced future folio lines, frees rooms,
        stamps the actual checkout time, auto-posts the folio invoice.
        The booked line dates are never mutated. A folio with no
        uninvoiced charges posts nothing (no empty invoice) but checkout
        still proceeds; the cashier voids the folio separately."""
        for record in self:
            record._check_transition('check_out')
            record._auto_post_stay_nights()
            record._clear_future_folio_lines()
            record._release_rooms()
            record.with_context(hotel_allow_state_write=True).write({
                "state": "check_out",
                "actual_checkout_date": fields.Datetime.now(),
            })
            folio = record._ensure_folio()
            pending = folio.line_ids.filtered(
                lambda l: (l.quantity - (l.invoiced_qty or 0.0)) > 0.0)
            if pending:
                posted_move = folio.action_post_invoice()
                record.message_post(
                    body="Checkout posted %s."
                    % (posted_move.name or posted_move.id))
            else:
                record.message_post(
                    body="Checkout with no uninvoiced charges; "
                         "no invoice posted.")
            # invoice_status is non-stored so the stored room-line
            # locked flag won't recompute on its own; flush it here.
            # First post is the only False->True transition. Settle
            # pending recomputes first (while lines are unlocked) so a
            # later flush never trips _check_locked, then invalidate the
            # possibly-cached pre-post status before flushing the lock.
            record.flush_recordset()
            record.invalidate_recordset(['invoice_status'])
            record.room_line_ids._compute_locked()

    def _auto_post_stay_nights(self):
        """Post consumed room nights missing from the folio.

        Runs at checkout so the invoice always covers the stay even
        when Post Stay was never clicked. post_stay_nights dedups on
        (folio, product, hotel date, room), so audit-posted nights
        are skipped and re-runs are safe. Rate failures raise while
        still check_in (rooms held, nothing stranded).
        """
        self.ensure_one()
        folio = self._ensure_folio()
        plan = self.env['hotel.rate.plan']._plan_for_booking(self)
        if not plan:
            self.message_post(body="Checkout auto-post skipped: no rate plan.")
            return self.env['hotel.folio.line'].browse()
        lines = self.env['hotel.folio.line'].browse()
        engine = self.env['hotel.rate.engine']
        for rline in self.room_line_ids:
            if not rline.room_id or not rline.checkin_date \
                    or not rline.checkout_date:
                continue
            try:
                posted = engine.post_stay_nights(
                    folio.id, rline.room_id.id,
                    fields.Date.to_string(rline.checkin_date.date()),
                    fields.Date.to_string(rline.checkout_date.date()),
                    plan.id, adults=rline.adults or 0,
                    children=rline.children or 0)
            except ValidationError:
                raise ValidationError(
                    _("Checkout blocked for %s: %s has no rate "
                      "for the stay; price it before checkout.")
                    % (self.name, rline.room_id.display_name))
            lines |= posted
        if lines:
            self.message_post(
                body="Checkout auto-posted %d night line(s)."
                % len(lines))
        return lines

    def _clear_future_folio_lines(self):
        """Delete open-folio lines past today not yet invoiced.

        Early-checkout cleanup: future charges (hotel_date > today)
        with no invoiced qty and no lock are removed; consumed nights
        stay for invoicing. Each affected folio gets a chatter note.
        """
        self.ensure_one()
        today = fields.Date.today()
        folios = self.env['hotel.folio'].search(
            [('booking_id', '=', self.id), ('state', '=', 'open')])
        for folio in folios:
            lines = self.env['hotel.folio.line'].search([
                ('folio_id', '=', folio.id),
                ('hotel_date', '>', today),
                ('invoiced_qty', '=', 0),
                ('locked', '=', False),
            ])
            if not lines:
                continue
            dates = sorted({str(line.hotel_date) for line in lines})
            count = len(lines)
            lines.unlink()
            folio.message_post(
                body="Early checkout cleared %d future uninvoiced "
                     "line(s) (%s)." % (count, ', '.join(dates)))

    def action_invoice(self):
        """Retired parallel path: folio unification owns invoicing.

        Kept as a stub for compat; raises with a redirect message instead
        of double-billing. Use the booking folio's draft/post/settle flow.
        """
        self.ensure_one()
        folio = self.env['hotel.folio'].search(
            [('booking_id', '=', self.id)], limit=1)
        hint = ("folio %s" % folio.id) if folio else "reserve first"
        raise ValidationError(
            _("Booking invoices retired; use %s "
              "action_generate_draft_invoice / action_post_invoice / "
              "action_settle (no double-billing).") % hint)

    def action_view_folio(self):
        """Open this booking's folios (single -> form, multi -> list)."""
        self.ensure_one()
        folios = self.env['hotel.folio'].search(
            [('booking_id', '=', self.id)])
        if len(folios) == 1:
            return {
                'type': 'ir.actions.act_window',
                'name': 'Folio',
                'res_model': 'hotel.folio',
                'view_mode': 'form',
                'res_id': folios.id,
                'context': "{'create': False}"
            }
        return {
            'type': 'ir.actions.act_window',
            'name': 'Folios',
            'res_model': 'hotel.folio',
            'view_mode': 'list,form',
            'domain': [('id', 'in', folios.ids)],
            'context': "{'create': False}"
        }

    def action_charge_ancillaries(self):
        """Post unposted service/food/fleet/event lines to the open folio.

        Requires check_in state and booking company == env company.
        Idempotent: only lines with folio_line_id == False are posted.
        Zero unposted posts a 'nothing new' chatter note and still
        returns the folio form action (no raise).
        """
        self.ensure_one()
        if self.state != 'check_in':
            raise ValidationError(
                _("Ancillaries can only be charged in Check-In state "
                  "(booking %s is %s).") % (self.name, self.state))
        if self.company_id.id != self.env.company.id:
            raise ValidationError(
                _("Booking %s belongs to %s; charge from that company.")
                % (self.name, self.company_id.display_name))
        folio = self._ensure_folio()
        today = fields.Date.today()
        charger = self.env['hotel.charge.service']
        pending = []
        for field_name, source in (
                ('service_line_ids', 'service'),
                ('food_order_line_ids', 'food'),
                ('vehicle_line_ids', 'fleet'),
                ('event_line_ids', 'event')):
            for line in self[field_name].filtered(
                    lambda l: not l.folio_line_id):
                pending.append((line, source))
        count = 0
        for line, source in pending:
            product = line._charge_product()
            folio_line = charger.post_charge(
                folio.id, product.id, line.uom_qty or 1.0,
                line.price_unit, 'to_guest',
                hotel_date=today, source=source)
            if line.tax_ids:
                folio_line.write(
                    {'tax_ids': [(6, 0, line.tax_ids.ids)]})
            line.write({'folio_line_id': folio_line.id})
            count += 1
        if count:
            self.message_post(
                body="Charged %d ancillary line(s) to folio %s."
                % (count, folio.id))
        else:
            self.message_post(
                body="Charge Ancillaries: nothing new to post "
                     "to folio %s." % folio.id)
        return {
            'type': 'ir.actions.act_window',
            'name': 'Folio',
            'res_model': 'hotel.folio',
            'view_mode': 'form',
            'res_id': folio.id,
        }

    def action_view_invoices(self):
        """Method for Returning invoice View (booking + folio invoices)."""
        self.ensure_one()
        folio_ids = self.env['hotel.folio'].search(
            [('booking_id', '=', self.id)]).ids
        if folio_ids:
            domain = ['|', ('hotel_booking_id', '=', self.id),
                      ('hotel_folio_id', 'in', folio_ids)]
        else:
            domain = [('hotel_booking_id', '=', self.id)]
        return {
            'type': 'ir.actions.act_window',
            'name': 'Invoices',
            'view_mode': 'list,form',
            'view_type': 'list,form',
            'res_model': 'account.move',
            'domain': domain,
            'context': "{'create': False}"
        }

    def action_view_payments(self):
        """Open payments linked to this booking directly or via folios."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Payments',
            'view_mode': 'list,form',
            'res_model': 'account.payment',
            'domain': self._payment_domain(),
            'context': "{'create': False}"
        }

    def action_register_payment(self):
        """Booking-level Register Payment: delegates to the open folio."""
        self.ensure_one()
        folio = self.env['hotel.folio'].search(
            [('booking_id', '=', self.id), ('state', '=', 'open')], limit=1)
        if not folio:
            raise ValidationError("Reserve first: no open folio.")
        return folio.action_register_payment()

    def action_checkin(self):
        """
        @param self: object pointer
        """
        for record in self:
            record._check_transition('check_in')
            if not record.room_line_ids:
                raise ValidationError(("Please Enter Room Details"))
            record.partner_id.check_documents_valid()
            for line in record.room_line_ids:
                self._check_room_available(
                    line.room_id, line.checkin_date, line.checkout_date,
                    ignore_booking=record)
            record._hold_rooms('occupied')
            record.room_line_ids._compute_rate_snapshot()
            record.with_context(hotel_allow_state_write=True).write(
                {"state": "check_in", "is_checkin": True})
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'message': "Booking Checked In Successfully!",
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }

    @api.model
    def get_details(self):
        """Dashboard counters. Company-scoped, domain-filtered, currency
        converted — no full-table scans."""
        company = self.env.company
        today_date = fields.Date.context_today(self)
        Room = self.env['product.template'].with_company(company)
        Booking = self.env['room.booking'].with_company(company)
        Move = self.env['account.move'].with_company(company)
        total_room = Room.search_count([('is_room', '=', True)])
        available_room = Room.search_count(
            [('is_room', '=', True), ('status', '=', 'available')])
        check_in = Booking.search_count([('state', '=', 'check_in')])
        reservation = Booking.search_count([('state', '=', 'reserved')])
        check_out = self.env['room.booking.line'].search_count([
            ('booking_id.state', '=', 'check_in'),
            ('booking_id.company_id', '=', company.id),
            ('checkout_date', '>=', fields.Datetime.to_string(
                datetime.combine(today_date,
                                 datetime.min.time()))),
            ('checkout_date', '<', fields.Datetime.to_string(
                datetime.combine(today_date + timedelta(days=1),
                                 datetime.min.time()))),
        ])
        staff = self.env['res.users'].search_count([
            ('company_ids', 'in', company.id),
            ('group_ids', 'in', [
                self.env.ref(
                    'hotel_management_odoo.hotel_group_admin').id,
                self.env.ref(
                    'hotel_management_odoo.cleaning_team_group_head').id,
                self.env.ref(
                    'hotel_management_odoo.cleaning_team_group_user').id,
                self.env.ref(
                    'hotel_management_odoo.hotel_group_reception').id,
                self.env.ref(
                    'hotel_management_odoo.maintenance_team_group_leader'
                ).id,
                self.env.ref(
                    'hotel_management_odoo.maintenance_team_group_user'
                ).id])])
        # Revenue aggregates only (no journal content): the dashboard
        # renders for reception, who has no direct journal access.
        revenues = Move.sudo().search_read(
            [('hotel_booking_id', '!=', False),
             ('state', '=', 'posted')],
            ['amount_total', 'currency_id', 'payment_state', 'date'])
        target_currency = company.currency_id
        total_revenue = today_revenue = pending_payment = 0.0
        for move in revenues:
            amount = target_currency._convert(
                move['amount_total'],
                self.env['res.currency'].browse(move['currency_id'][0])
                if move.get('currency_id') else target_currency,
                company, move['date'] or fields.Date.today())
            if move['payment_state'] == 'paid':
                total_revenue += amount
                if move['date'] and fields.Date.to_string(
                        move['date']) == fields.Date.to_string(today_date):
                    today_revenue += amount
            elif move['payment_state'] == 'not_paid':
                pending_payment += amount
        return {
            'total_room': total_room,
            'available_room': available_room,
            'staff': staff,
            'check_in': check_in,
            'reservation': reservation,
            'check_out': check_out,
            'total_revenue': round(total_revenue, 2),
            'today_revenue': round(today_revenue, 2),
            'pending_payment': round(pending_payment, 2),
            'currency_symbol': target_currency.symbol,
            'currency_position': target_currency.position,
        }

    def action_compute_bill(self):
        """Open the Compute Bill wizard"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Compute Bill',
            'res_model': 'compute.bill',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_booking_id': self.id}
        }