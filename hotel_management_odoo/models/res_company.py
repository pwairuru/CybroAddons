# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class ResCompany(models.Model):
    """Company-level hotel defaults.

    ``default_rate_plan_id`` preselects the Post Room Charges wizard plan
    (and rate calendar) so front desk never starts on an arbitrary
    lowest-id plan. Must belong to the same company.
    """
    _inherit = 'res.company'

    default_rate_plan_id = fields.Many2one(
        'hotel.rate.plan', string='Default Rate Plan',
        ondelete='set null',
        help='Preselected in the Post Room Charges wizard and rate calendar. '
        'Falls back to the Rack plan when empty.')

    rate_missing_mode = fields.Selection([('strict','Strict'),('fallback','Fallback'),('warn','Warn')], default='strict', required=True,
        help='Missing rate handling: strict raises, fallback resolves silently, warn resolves with folio note.')

    hotel_capacity_policy = fields.Selection(
        [('block', 'Block saving'), ('warn', 'Warn only')],
        string='Over-capacity policy', default='block', required=True,
        help='How to handle a room line where adults + children exceed '
        'the room capacity (room persons or type max occupants; '
        'toddlers never count). Block saving refuses to save the '
        'line; Warn only allows it and flags the line.')

    no_show_policy = fields.Selection(
        [('no_charge', 'No Charge'),
         ('first_night', 'Charge First Night'),
         ('forfeit_deposit', 'Forfeit Deposit')],
        string='No-Show Policy', default='no_charge', required=True,
        help='Night-audit behaviour for reserved bookings whose '
        'check-in date passed unfulfilled. Per company so each '
        'property follows its own contract.')
    no_show_fee_product_id = fields.Many2one(
        'product.product', string='No-Show Fee Product',
        ondelete='set null',
        help='Optional product for the first-night no-show charge. '
        'Falls back to the room product when empty.')

    mpesa_paybill_number = fields.Char(
        string='M-Pesa Paybill',
        help='Paybill number printed on guest documents (bills, '
             'folio statements, invoices, POS receipts). Empty hides '
             'the paybill block.')
    mpesa_paybill_account = fields.Char(
        string='M-Pesa Account Name',
        help='Account name printed under the paybill on guest documents.')

    @api.model
    def _load_pos_data_fields(self, config):
        fields_list = super()._load_pos_data_fields(config)
        for name in ('mpesa_paybill_number', 'mpesa_paybill_account'):
            if name not in fields_list:
                fields_list.append(name)
        return fields_list

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

    @api.constrains('no_show_fee_product_id')
    def _check_no_show_fee_product_company(self):
        for company in self:
            product = company.no_show_fee_product_id
            if product and product.company_id \
                    and product.company_id.id != company.id:
                raise ValidationError(
                    'No-show fee product %s belongs to %s, not %s.'
                    % (product.display_name,
                       product.company_id.display_name,
                       company.display_name))
