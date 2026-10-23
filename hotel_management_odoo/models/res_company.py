# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class ResCompany(models.Model):
    """Company-level hotel defaults.

    ``default_rate_plan_id`` preselects the Post Stay wizard plan
    (and rate calendar) so front desk never starts on an arbitrary
    lowest-id plan. Must belong to the same company.
    """
    _inherit = 'res.company'

    default_rate_plan_id = fields.Many2one(
        'hotel.rate.plan', string='Default Rate Plan',
        ondelete='set null',
        help='Preselected in the Post Stay wizard and rate calendar. '
        'Falls back to the Rack plan when empty.')

    @api.constrains('default_rate_plan_id')
    def _check_default_rate_plan_company(self):
        for company in self:
            plan = company.default_rate_plan_id
            if plan and plan.company_id.id != company.id:
                raise ValidationError(
                    'Default rate plan %s belongs to %s, not %s.'
                    % (plan.display_name,
                       plan.company_id.display_name,
                       company.display_name))
