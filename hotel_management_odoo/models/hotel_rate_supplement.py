# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class HotelRateMealSupplement(models.Model):
    _name = 'hotel.rate.meal.supplement'
    _description = 'Hotel Rate Meal Supplement'
    _order = 'room_type_id, meal_plan_id'
    room_type_id = fields.Many2one('hotel.room.type', required=True, ondelete='cascade', index=True)
    meal_plan_id = fields.Many2one('hotel.meal.plan', required=True, ondelete='restrict', index=True)
    company_id = fields.Many2one('res.company', related='room_type_id.company_id', store=True, readonly=True, index=True)
    active_uplift = fields.Boolean(default=False)
    mode = fields.Selection([('fixed','Fixed'),('percent','Percent')], default='percent', required=True)
    value = fields.Float(default=0.0)
    @api.constrains('value')
    def _check_value(self):
        for r in self:
            if r.mode == 'fixed' and r.value < 0:
                raise ValidationError('Supplement fixed value cannot be negative.')
    @api.constrains('room_type_id','meal_plan_id')
    def _check_unique(self):
        for r in self:
            if self.search_count([('id','!=',r.id),('room_type_id','=',r.room_type_id.id),('meal_plan_id','=',r.meal_plan_id.id)]) :
                raise ValidationError('Supplement already set for this type and meal.')


class HotelRatePlanAdjustment(models.Model):
    _name = 'hotel.rate.plan.adjustment'
    _description = 'Hotel Rate Plan Adjustment'
    _order = 'plan_id, room_type_id, period_id'
    plan_id = fields.Many2one('hotel.rate.plan', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one('res.company', related='plan_id.company_id', store=True, readonly=True, index=True)
    room_type_id = fields.Many2one('hotel.room.type', ondelete='cascade', index=True)
    period_id = fields.Many2one('hotel.rate.period', ondelete='cascade', index=True)
    mode = fields.Selection([('percent','Percent'),('fixed','Fixed')], default='percent', required=True)
    value = fields.Float(default=0.0)
