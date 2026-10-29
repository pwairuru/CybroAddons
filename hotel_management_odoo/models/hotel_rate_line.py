# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError

class HotelRateLine(models.Model):
    _name = 'hotel.rate.line'
    _description = "Hotel Rate Line"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'period_id, room_type_id, meal_plan_id'
    _rate_line_uniq = models.Constraint(
        'unique(period_id, room_type_id, meal_plan_id, company_id)',
        'A rate already exists for this period, room type and meal plan.',
    )
    company_id = fields.Many2one('res.company', required=True, index=True, default=lambda self: self.env.company, tracking=True,
                                     help="Hotel this rate belongs to. Lines never apply across companies.")
    period_id = fields.Many2one('hotel.rate.period', required=True, ondelete='cascade', index=True, tracking=True,
                                help="Season window this price applies in. When several periods cover a night, the highest-priority period with a line for this type and board wins; the rest fall through.")
    room_type_id = fields.Many2one('hotel.room.type', required=True, index=True, tracking=True,
                                   help="Room type this price is for. Only one line per period, type and board — duplicates are rejected.")
    meal_plan_id = fields.Many2one('hotel.meal.plan', required=True, ondelete='restrict', index=True, tracking=True,
                                   help="Board this price is for (Room Only, BB, HB, FB). A booking uses this line only when its board matches.")
    currency_id = fields.Many2one('res.currency', required=True, default=lambda self: self.env.company.currency_id,
                                  help="Currency of the price below. Follows the company currency.")
    price = fields.Monetary(required=True, tracking=True,
                            help="Nightly rent covering the included adults and children below. Guests beyond the included counts pay the extras.")
    included_adults = fields.Integer(default=2, tracking=True,
                                     help="Adults covered by the rent. Each extra adult pays the adult extra below.")
    included_children = fields.Integer(default=0, tracking=True,
                                       help="Children covered by the rent. Each extra child pays the child extra below.")
    extra_adult_mode = fields.Selection([('fixed','Fixed'),('percent','Percent')], default='fixed', required=True, tracking=True,
                                        help="How an extra adult is charged: a flat amount, or a percent of the per-slot rate (price divided by included adults + children).")
    extra_adult_value = fields.Float(default=0.0, tracking=True,
                                     help="Flat amount per extra adult, or percent of the per-slot rate. 0 means extra adults stay free.")
    extra_child_mode = fields.Selection([('fixed','Fixed'),('percent','Percent')], default='percent', required=True, tracking=True,
                                        help="How an extra child is charged: a flat amount, or a percent of the per-slot rate (price divided by included adults + children).")
    extra_child_value = fields.Float(default=50.0, tracking=True,
                                     help="Flat amount per extra child, or percent of the per-slot rate — 50 is half price. 0 means extra children stay free.")
    extra_bed_price = fields.Monetary(default=0.0, tracking=True,
                                      help="Charged separately per night when an extra bed is used. Bed use never changes the rent above by itself.")

    @api.constrains('price', 'extra_adult_value', 'extra_child_value', 'extra_bed_price')
    def _check_nonneg(self):
        for r in self:
            if r.price < 0 or r.extra_adult_value < 0 or r.extra_child_value < 0 or r.extra_bed_price < 0:
                raise ValidationError("Prices and extra values cannot be negative.")

    @api.constrains('included_adults', 'included_children')
    def _check_included(self):
        for r in self:
            if r.included_adults < 0 or r.included_children < 0:
                raise ValidationError("Included counts cannot be negative.")
            if r.room_type_id and r.room_type_id.max_occupants and (r.included_adults + r.included_children) > r.room_type_id.max_occupants:
                raise ValidationError("Included %d exceeds type max %d." % (r.included_adults + r.included_children, r.room_type_id.max_occupants))

    @api.constrains('extra_adult_mode', 'extra_adult_value', 'extra_child_mode', 'extra_child_value')
    def _check_percent(self):
        for r in self:
            if r.extra_adult_mode == 'percent' and (r.extra_adult_value < 0 or r.extra_adult_value > 999):
                raise ValidationError("Extra adult percent must be between 0 and 999.")
            if r.extra_child_mode == 'percent' and (r.extra_child_value < 0 or r.extra_child_value > 999):
                raise ValidationError("Extra child percent must be between 0 and 999.")

    @api.constrains('period_id', 'room_type_id', 'company_id')
    def _check_company(self):
        Period = self.env['hotel.rate.period']
        period_has_company = 'company_id' in Period._fields
        for r in self:
            if period_has_company and r.period_id.company_id and r.period_id.company_id.id != r.company_id.id:
                raise ValidationError("Line company must match period company.")
            if r.room_type_id.company_id.id != r.company_id.id:
                raise ValidationError("Line company must match room type company.")

    @api.model
    def find_line(self, period_id, room_type_id, meal_code, company_id=None):
        company_id = company_id or self.env.company.id
        meal = self.env['hotel.meal.plan'].search([('code','=',meal_code)], limit=1)
        if not meal:
            return self.browse()
        return self.search([('period_id','=',period_id),('room_type_id','=',room_type_id),('meal_plan_id','=',meal.id),('company_id','=',company_id)], limit=1)

    def compute_night(self, adults=0, children=0):
        self.ensure_one()
        adults = int(adults or 0); children = int(children or 0)
        rtype = self.room_type_id
        if rtype.charge_mode == 'per_person':
            extra_c = max(0, children - (self.included_children or 0))
            if self.extra_child_mode == 'fixed':
                c_amt = extra_c * (self.extra_child_value or 0.0)
            else:
                c_amt = extra_c * float(self.price or 0.0) * (self.extra_child_value or 0.0) / 100.0
            net = float(self.price or 0.0) * adults + c_amt
            return {'net': round(net,2), 'extra_a': 0.0, 'extra_c': round(c_amt,2)}
        div = max((self.included_adults or 0) + (self.included_children or 0), 1)
        per_slot = float(self.price or 0.0) / div
        extra_a = max(0, adults - (self.included_adults or 0))
        extra_c = max(0, children - (self.included_children or 0))
        if self.extra_adult_mode == 'fixed':
            a_amt = extra_a * (self.extra_adult_value or 0.0)
        else:
            a_amt = extra_a * per_slot * (self.extra_adult_value or 0.0) / 100.0
        if self.extra_child_mode == 'fixed':
            c_amt = extra_c * (self.extra_child_value or 0.0)
        else:
            c_amt = extra_c * per_slot * (self.extra_child_value or 0.0) / 100.0
        return {'net': round(float(self.price or 0.0) + a_amt + c_amt,2), 'extra_a': round(a_amt,2), 'extra_c': round(c_amt,2)}
