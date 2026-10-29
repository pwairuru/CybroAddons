# -*- coding: utf-8 -*-
from odoo import api, fields, models


class HotelRoomType(models.Model):
    _name = 'hotel.room.type'
    _description = "Hotel Room Type"
    _inherit = ['mail.thread', 'mail.activity.mixin', 'avatar.mixin']
    _order = 'name'

    name = fields.Char(required=True, tracking=True,
                        help="Category guests book, e.g. Standard, Deluxe, Family. Bookings, rate lines and occupancy extras all point at the type, never at a single room.")
    code = fields.Char(tracking=True,
                       help="Short label shown on the tape chart and reports, e.g. DLX. Keep it unique per company.")
    company_id = fields.Many2one('res.company', required=True, index=True,
                                 default=lambda self: self.env.company,
                                 tracking=True,
                                 help="Hotel this type belongs to. Types, prices and rules never cross companies.")
    adult_capacity = fields.Integer(default=2, tracking=True,
                                    help="Adults the rent normally covers. Extra adults beyond the rate line's included count are billed on top.")
    child_capacity = fields.Integer(default=0, tracking=True,
                                    help="Children the rooms of this type can take. Informational: the hard limit is Max Occupants.")
    max_occupants = fields.Integer(default=2, tracking=True,
                                   help="Hard ceiling for adults + children together. Bookings and pricing refuse anything above this number.")
    base_rate = fields.Float(required=True, default=0.0, tracking=True,
                             help="Reference nightly rent for this type. Engine pricing comes from rate lines; this stays as the fallback reference.")
    charge_mode = fields.Selection(
        [('per_room', 'Per Room'), ('per_person', 'Per Person')],
        string="Charge Mode", default='per_room', required=True,
        tracking=True,
        help="Per Room: plan price covers adult_capacity + included "
        "children, extras via occupancy bands. Per Person: total = "
        "plan price x heads / standard heads.")
    standard_heads = fields.Integer(
        string="Standard Heads", default=0, tracking=True,
        help="Divisor for per-person pricing; 0 falls back to "
        "adult_capacity (then 1).")
    default_board = fields.Selection(
        [('RO', 'Room Only'), ('BB', 'Bed & Breakfast'),
         ('HB', 'Half Board'), ('FB', 'Full Board')],
        default='RO', required=True, tracking=True,
        help="Board pre-filled on new bookings of this type. Only a suggestion: any booking can still pick another board, and a board only changes the price if a rate line exists for it.")
    meal_price_ids = fields.One2many('hotel.room.type.meal.price',
                                     'room_type_id',
                                     string="Meal Prices",
                                     help="Legacy per-board prices, no longer used for pricing since rate lines took over. Kept for history.")
    website_published = fields.Boolean(default=False, tracking=True,
                                       help="Show this room type on the website booking page.")
    amenity_ids = fields.Many2many('hotel.amenity', string="Amenities",
                                   help="Features of this type, e.g. sea view, balcony. Shown to guests, never affects price.")
    image = fields.Image(help="Photo shown on the website and the type card.")
    active = fields.Boolean(default=True, tracking=True,
                            help="Archived types disappear from new bookings but keep their history on old ones.")

    def default_rate(self):
        self.ensure_one()
        return self.base_rate

    def ensure_meal_price_lines(self):
        """Create the missing per-plan price lines (0.0)."""
        plans = self.env['hotel.meal.plan'].search(
            [('active', '=', True)])
        line_model = self.env['hotel.room.type.meal.price']
        for rtype in self:
            have = set(rtype.meal_price_ids.mapped('meal_plan_id.id'))
            for plan in plans:
                if plan.id not in have:
                    line_model.create({
                        'room_type_id': rtype.id,
                        'meal_plan_id': plan.id,
                        'price': 0.0,
                    })
        return True

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records.ensure_meal_price_lines()
        return records
