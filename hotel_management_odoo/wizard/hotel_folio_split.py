# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class HotelFolioSplit(models.TransientModel):
    """Split selected folio lines to an existing or brand-new folio."""
    _name = 'hotel.folio.split'
    _description = 'Split Folio Bill'

    folio_id = fields.Many2one('hotel.folio', string='Source Folio',
                               required=True)
    company_id = fields.Many2one('res.company', string='Company',
                                 related='folio_id.company_id', readonly=True)
    line_ids = fields.Many2many('hotel.folio.line', string='Lines to Move',
                                required=True,
                                domain="[('folio_id', '=', folio_id)]")
    target_mode = fields.Selection(
        [('existing', 'Existing folio'), ('new', 'New folio')],
        string='Target', default='existing', required=True)
    target_folio_id = fields.Many2one(
        'hotel.folio', string='Target Folio',
        domain="[('state', '=', 'open'), ('id', '!=', folio_id),"
               " ('company_id', '=', company_id)]")
    new_partner_id = fields.Many2one('res.partner', string='New Folio Guest')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        folio_id = self.env.context.get('default_folio_id')
        if not folio_id \
                and self.env.context.get('active_model') == 'hotel.folio':
            folio_id = self.env.context.get('active_id')
        folio = self.env['hotel.folio'].browse(folio_id) \
            if folio_id else self.env['hotel.folio'].browse()
        if folio.exists():
            if 'folio_id' in fields_list:
                res['folio_id'] = folio.id
            if 'new_partner_id' in fields_list \
                    and not res.get('new_partner_id'):
                res['new_partner_id'] = folio.partner_id.id
        return res

    def action_split(self):
        """Move lines to the target folio; returns the folio form action."""
        self.ensure_one()
        source = self.folio_id
        if source.state != 'open':
            raise ValidationError(
                "Can only split from an open folio.")
        if not self.line_ids:
            raise ValidationError("Select at least one line to move.")
        stray = self.line_ids.filtered(lambda l: l.folio_id != source)
        if stray:
            raise ValidationError(
                "All lines must belong to the source folio.")
        if self.target_mode == 'existing':
            target = self.target_folio_id
            if not target.exists():
                raise ValidationError("Select an existing target folio.")
            if target.id == source.id:
                raise ValidationError(
                    "Target folio must differ from the source.")
            if target.state != 'open':
                raise ValidationError(
                    "Can only transfer to an open folio.")
            if target.company_id.id != source.company_id.id:
                raise ValidationError(
                    "Transfer needs one company; %s -> %s."
                    % (source.company_id.display_name,
                       target.company_id.display_name))
        else:
            if not self.new_partner_id:
                raise ValidationError(
                    "Select a guest for the new folio.")
            target = self.env['hotel.folio'].create({
                'partner_id': self.new_partner_id.id,
                'booking_id': source.booking_id.id or False,
                'company_id': source.company_id.id,
            })
        for line in self.line_ids:
            line.action_transfer(target.id)
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'hotel.folio',
            'res_id': target.id,
            'views': [(False, 'form')],
        }
