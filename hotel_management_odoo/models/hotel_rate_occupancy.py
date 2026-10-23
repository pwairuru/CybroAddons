# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError

from .hotel_business_date import _to_date

OCCUPANCY_BANDS = ('adult', 'child', 'toddler')


class HotelRateOccupancy(models.Model):
    """Extra-guest charge per room type and band.

    One record covers guests beyond ``included_count`` for a band:
    extra = max(0, requested - included). Charge is ``value`` flat
    or ``value`` percent of the resolved nightly rate
    (``resolved_rate``) or the type BAR (``bar`` = type base_rate).
    ``plan_id`` empty means type default; a plan-specific record for
    the same type+band wins over the default. No record for a band
    means no extra charge (legacy stays without occupancy records
    price exactly the resolved rate).
    """
    _name = 'hotel.rate.occupancy'
    _description = "Hotel Rate Occupancy"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'room_type_id, band'

    room_type_id = fields.Many2one('hotel.room.type', string="Room Type",
                                   required=True, ondelete="cascade",
                                   index=True, tracking=True)
    company_id = fields.Many2one('res.company', string="Company",
                                 related='room_type_id.company_id',
                                 store=True, readonly=True, index=True)
    plan_id = fields.Many2one('hotel.rate.plan', string="Plan",
                              help="Plan this occupancy applies to; "
                              "empty = default for the type.",
                              ondelete="cascade", index=True,
                              tracking=True)
    band = fields.Selection([('adult', 'Adult'), ('child', 'Child'),
                             ('toddler', 'Toddler')],
                            string="Band", required=True, tracking=True)
    included_count = fields.Integer(string="Included", default=0,
                                    tracking=True)
    max_count = fields.Integer(string="Max", default=0,
                               help="Max guests in this band (0 = no cap "
                               "beyond type/room capacity).",
                               tracking=True)
    mode = fields.Selection([('fixed', 'Fixed'), ('percent', 'Percent')],
                            string="Mode", default='percent', required=True,
                            tracking=True)
    value = fields.Float(string="Value", default=0.0, tracking=True)
    basis = fields.Selection([('resolved_rate', 'Resolved Rate'),
                              ('bar', 'BAR (type base rate)')],
                             string="Basis", default='resolved_rate',
                             required=True, tracking=True)
    service_product_id = fields.Many2one('product.product',
                                         string="Service Product",
                                         help="Product used when posting "
                                         "extra-guest charges.",
                                         ondelete="set null",
                                         tracking=True)

    @api.constrains('included_count', 'max_count', 'value')
    def _check_counts(self):
        for rec in self:
            if rec.included_count < 0:
                raise ValidationError("Included count cannot be negative.")
            if rec.max_count < 0:
                raise ValidationError("Max count cannot be negative.")
            if rec.max_count and rec.max_count < rec.included_count:
                raise ValidationError(
                    "Max (%d) cannot be below included (%d)."
                    % (rec.max_count, rec.included_count))
            if rec.value < 0:
                raise ValidationError("Occupancy value cannot be negative.")

    @api.constrains('room_type_id', 'plan_id', 'band')
    def _check_unique_band(self):
        for rec in self:
            dup = self.search([
                ('id', '!=', rec.id),
                ('room_type_id', '=', rec.room_type_id.id),
                ('plan_id', '=', rec.plan_id.id or False),
                ('band', '=', rec.band),
            ], limit=1)
            if dup:
                raise ValidationError(
                    "Occupancy already set for type %s, band %s%s."
                    % (rec.room_type_id.display_name, rec.band,
                       " plan %s" % rec.plan_id.display_name
                       if rec.plan_id else " (type default)"))


class HotelBoardRule(models.Model):
    """Board supplement per person/night by type/plan x dates x board.

    ``room_type_id`` empty = all types; ``plan_id`` empty = all plans
    when no plan context is given (meal posting), or the type/plan
    default when a plan is passed. Most specific wins: type+plan >
    type-only/plan-only > generic, then shortest window, latest
    date_from, latest id. Overlapping same-board windows are allowed;
    the matcher picks one deterministically — do not rely on stacking.
    """
    _name = 'hotel.board.rule'
    _description = "Hotel Board Rule"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_from desc'

    company_id = fields.Many2one('res.company', string="Company",
                                 required=True, index=True,
                                 default=lambda self: self.env.company,
                                 tracking=True)
    room_type_id = fields.Many2one('hotel.room.type', string="Room Type",
                                   help="Room type this board rule applies "
                                   "to; empty = all types.",
                                   ondelete="cascade", index=True,
                                   tracking=True)
    plan_id = fields.Many2one('hotel.rate.plan', string="Plan",
                              help="Plan this board rule applies to; "
                              "empty = default for the board.",
                              ondelete="cascade", index=True,
                              tracking=True)
    board = fields.Selection([('RO', 'Room Only'),
                              ('BB', 'Bed & Breakfast'),
                              ('HB', 'Half Board'),
                              ('FB', 'Full Board')],
                             string="Board", required=True, tracking=True)
    date_from = fields.Date(string="From", required=True, tracking=True)
    date_to = fields.Date(string="To", required=True, tracking=True)
    supplement = fields.Float(string="Supplement / person / night",
                              default=0.0, tracking=True)

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for rec in self:
            if rec.date_from and rec.date_to \
                    and rec.date_to < rec.date_from:
                raise ValidationError(
                    "Board rule end date must be on/after start.")

    @api.constrains('supplement')
    def _check_supplement(self):
        for rec in self:
            if rec.supplement < 0:
                raise ValidationError("Board supplement cannot be negative.")

    @api.model
    def _match(self, room_type_id, board, day, plan_id=None,
               company_id=None):
        day = _to_date(day)
        domain = [
            ('board', '=', board),
            ('date_from', '<=', day),
            ('date_to', '>=', day),
        ]
        if company_id:
            domain.append(('company_id', '=', company_id))
        rules = self.search(domain)
        candidates = []
        for rule in rules:
            type_ok = (not rule.room_type_id
                       or (room_type_id
                           and rule.room_type_id.id == room_type_id))
            if plan_id:
                plan_ok = (not rule.plan_id
                           or rule.plan_id.id == plan_id)
            else:
                plan_ok = not rule.plan_id
            if type_ok and plan_ok:
                candidates.append(rule)
        if not candidates:
            return None

        def _rank(rule):
            specificity = ((2 if rule.room_type_id else 0)
                           + (1 if rule.plan_id else 0))
            if rule.date_from and rule.date_to:
                window = (rule.date_to - rule.date_from).days
            else:
                window = 0
            return (specificity, -window, rule.date_from, rule.id)

        return max(candidates, key=_rank)


class HotelRateSnapshot(models.Model):
    """Immutable per-night rated price record.

    Written by ``hotel.rate.engine.post_stay_nights`` (one per folio
    line). Never edited in place: repricing writes a new snapshot
    (Task 4 folio flows consume these; Task 6 matrix reads them).
    """
    _name = 'hotel.rate.snapshot'
    _description = "Hotel Rate Snapshot"
    _order = 'hotel_date desc, id desc'

    company_id = fields.Many2one('res.company', string="Company",
                                 required=True, index=True,
                                 default=lambda self: self.env.company,
                                 tracking=True)
    hotel_date = fields.Date(string="Hotel Date", required=True,
                             index=True, tracking=True)
    room_template_id = fields.Many2one('product.template', string="Room",
                                       domain=[('is_room', '=', True)],
                                       required=True, index=True,
                                       tracking=True)
    plan_id = fields.Many2one('hotel.rate.plan', string="Plan",
                              ondelete="set null", index=True,
                              tracking=True)
    folio_id = fields.Many2one('hotel.folio', string="Folio",
                               ondelete="set null", index=True,
                               tracking=True)
    folio_line_id = fields.Many2one('hotel.folio.line', string="Folio Line",
                                    ondelete="set null", index=True,
                                    tracking=True)
    base = fields.Float(string="Base", default=0.0, tracking=True)
    adjustment = fields.Float(string="Adjustment", default=0.0,
                              tracking=True)
    occupancy = fields.Float(string="Occupancy", default=0.0,
                             tracking=True)
    board = fields.Float(string="Board", default=0.0, tracking=True)
    net = fields.Float(string="Net", default=0.0, tracking=True)
    tax = fields.Float(string="Tax", default=0.0, tracking=True)
    source_rule_id = fields.Many2one('hotel.rate.rule',
                                     string="Source Rule",
                                     ondelete="set null", index=True,
                                     tracking=True)
    override = fields.Boolean(string="Manual Override", default=False,
                              tracking=True)
