# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class HotelMealPlan(models.Model):
    """Meal plan master (Day Pass, Room Only, BB, HB, FB).

    Standalone catalogue: short code + full name + description.
    Not linked to rooms — every room type carries its own price
    per plan via ``hotel.room.type.meal.price`` (total room price
    per night). Seeded on install; managers may edit after.
    """
    _name = 'hotel.meal.plan'
    _description = "Hotel Meal Plan"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'sequence, code'

    name = fields.Char(string="Full Name", required=True, tracking=True)
    code = fields.Char(string="Short Code", required=True, tracking=True)
    description = fields.Text(tracking=True)
    sequence = fields.Integer(default=10, tracking=True)
    active = fields.Boolean(default=True, tracking=True)

    @api.constrains('code')
    def _check_unique_code(self):
        for rec in self:
            if not rec.code:
                continue
            dup = self.search([
                ('id', '!=', rec.id),
                ('code', '=', rec.code),
            ], limit=1)
            if dup:
                raise ValidationError(
                    "Meal plan code %s already used by %s."
                    % (rec.code, dup.display_name))

    @api.model_create_multi
    def create(self, vals_list):
        plans = super().create(vals_list)
        self.env['hotel.room.type'].search([]).ensure_meal_price_lines()
        return plans


class HotelRoomTypeMealPrice(models.Model):
    """Total room price per night for one room type x meal plan.

    The price lives on the room type, not on the meal plan.
    Lines are auto-created (one per active plan, 0.0) and must
    never be deleted — every room type keeps every plan.
    """
    _name = 'hotel.room.type.meal.price'
    _description = "Hotel Room Type Meal Price"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'room_type_id, meal_plan_id'

    room_type_id = fields.Many2one('hotel.room.type', string="Room Type",
                                   required=True, ondelete="cascade",
                                   index=True, tracking=True)
    company_id = fields.Many2one('res.company', string="Company",
                                 related='room_type_id.company_id',
                                 store=True, readonly=True, index=True)
    meal_plan_id = fields.Many2one('hotel.meal.plan', string="Meal Plan",
                                   required=True, ondelete="restrict",
                                   index=True, tracking=True)
    meal_plan_code = fields.Char(string="Code",
                                 related='meal_plan_id.code',
                                 readonly=True)
    meal_plan_description = fields.Text(
        string="Description", related='meal_plan_id.description',
        readonly=True)
    price = fields.Float(string="Price / Night", default=0.0,
                         tracking=True,
                         help="Total room price per night for this "
                         "room type on this meal plan.")

    @api.constrains('price')
    def _check_price(self):
        for rec in self:
            if rec.price < 0:
                raise ValidationError(
                    "Meal price cannot be negative.")

    @api.constrains('room_type_id', 'meal_plan_id')
    def _check_unique_type_plan(self):
        for rec in self:
            dup = self.search([
                ('id', '!=', rec.id),
                ('room_type_id', '=', rec.room_type_id.id),
                ('meal_plan_id', '=', rec.meal_plan_id.id),
            ], limit=1)
            if dup:
                raise ValidationError(
                    "Price already set for type %s, plan %s."
                    % (rec.room_type_id.display_name,
                       rec.meal_plan_id.display_name))

    def unlink(self):
        raise ValidationError(
            "Meal price lines cannot be deleted; every room type "
            "keeps every meal plan. Set the price instead.")
