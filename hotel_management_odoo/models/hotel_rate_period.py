# -*- coding: utf-8 -*-
import calendar

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class HotelRatePeriod(models.Model):
    _name = 'hotel.rate.period'
    _description = "Hotel Rate Period"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'sequence'

    name = fields.Char(required=True, tracking=True)
    start_md = fields.Char(string="Start (MM-DD)", required=True,
                           tracking=True)
    end_md = fields.Char(string="End (MM-DD)", required=True, tracking=True)
    sequence = fields.Integer(default=10, tracking=True)
    active = fields.Boolean(default=True, tracking=True)

    @api.constrains('start_md', 'end_md')
    def _check_md(self):
        for rec in self:
            for val in (rec.start_md, rec.end_md):
                try:
                    m, d = (int(x) for x in val.split('-'))
                except (ValueError, AttributeError):
                    raise ValidationError(
                        "Bad month-day %r; use MM-DD." % (val,))
                if not 1 <= m <= 12 or not 1 <= d <= 31:
                    raise ValidationError(
                        "Bad month-day %r; use MM-DD." % (val,))
                if d > calendar.monthrange(2024, m)[1]:
                    raise ValidationError(
                        "Bad month-day %r; use MM-DD." % (val,))

    def covers(self, month, day):
        self.ensure_one()
        try:
            point = (int(month), int(day))
        except (TypeError, ValueError):
            raise ValidationError(
                "Bad month-day %r-%r; use MM-DD ints." % (month, day))
        if not 1 <= point[0] <= 12 or not 1 <= point[1] <= 31:
            raise ValidationError(
                "Bad month-day %r-%r; use MM-DD ints." % (month, day))
        start = tuple(int(x) for x in self.start_md.split('-'))
        end = tuple(int(x) for x in self.end_md.split('-'))
        if start <= end:
            return start <= point <= end
        return point >= start or point <= end
