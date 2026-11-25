# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class RoomBookingOrigin(models.Model):
    """Booking origin catalogue (Reception, Website, Phone, ...).

    Staff-managed table: new origins (OTA, agents, ...) are added
    here without a code change. ``code`` is the stable technical key
    used for lookups (``_by_code``); renames never break links.
    Seeded on install; seed rows survive upgrades (noupdate).
    """
    _name = 'room.booking.origin'
    _description = "Booking Origin"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'sequence, code'

    name = fields.Char(string="Name", required=True, tracking=True)
    code = fields.Char(
        string="Code", required=True, tracking=True,
        help="Stable technical key used by website-booking logic "
             "(_by_code lookups, public booking flow, search filters). "
             "Do not rename casually: rename the Name instead; "
             "codes are normalized to stripped lowercase.")
    sequence = fields.Integer(default=10, tracking=True)
    active = fields.Boolean(default=True, tracking=True)

    @api.model_create_multi
    def create(self, vals_list):
        """Normalize code so imports/XML seed variants match the
        lowercase unique key (constrains run on stored values)."""
        for vals in vals_list:
            code = vals.get('code')
            if isinstance(code, str):
                vals['code'] = code.strip().lower()
        return super().create(vals_list)

    def write(self, vals):
        """Normalize code on write for the same reason as create."""
        code = vals.get('code')
        if isinstance(code, str):
            vals = dict(vals, code=code.strip().lower())
        return super().write(vals)

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
                    "Booking origin code %s already used by %s."
                    % (rec.code, dup.display_name))

    @api.model
    def _by_code(self, code):
        """Return the active origin for ``code`` (empty record if missing)."""
        if not code:
            return self.browse()
        return self.search([
            ('code', '=', code),
            ('active', '=', True),
        ], limit=1)

    def unlink(self):
        raise ValidationError(
            "Booking origins cannot be deleted; archive them instead "
            "so booking history keeps its origin.")
