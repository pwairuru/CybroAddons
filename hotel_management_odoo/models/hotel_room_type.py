# -*- coding: utf-8 -*-
from odoo import api, fields, models


class HotelRoomType(models.Model):
    _name = 'hotel.room.type'
    _description = "Hotel Room Type"
    _inherit = ['mail.thread', 'mail.activity.mixin', 'avatar.mixin']
    _order = 'name'

    name = fields.Char(required=True, tracking=True)
    code = fields.Char(tracking=True)
    company_id = fields.Many2one('res.company', required=True, index=True,
                                 default=lambda self: self.env.company,
                                 tracking=True)
    adult_capacity = fields.Integer(default=2, tracking=True)
    child_capacity = fields.Integer(default=0, tracking=True)
    max_occupants = fields.Integer(default=2, tracking=True)
    base_rate = fields.Float(required=True, default=0.0, tracking=True)
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
        default='RO', required=True, tracking=True)
    meal_price_ids = fields.One2many('hotel.room.type.meal.price',
                                     'room_type_id',
                                     string="Meal Prices")
    website_published = fields.Boolean(default=False, tracking=True)
    amenity_ids = fields.Many2many('hotel.amenity', string="Amenities")
    image = fields.Image()
    active = fields.Boolean(default=True, tracking=True)

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
