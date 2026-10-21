# -*- coding: utf-8 -*-
"""Task 10: service ops — linen, lost&found, complaints, wake-up, rosters, assets.

No HR/maintenance core changes: staff links use res.users + cleaning.team only.
All models company-safe (company_id default env.company, company-scoped guards).
All rejections via ValidationError.
"""
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class HotelLinenType(models.Model):
    _name = 'hotel.linen.type'
    _description = "Hotel Linen Type"

    name = fields.Char(string="Name", required=True)
    company_id = fields.Many2one('res.company', string="Company",
                                 required=True, index=True,
                                 default=lambda self: self.env.company)
    active = fields.Boolean(default=True)

    _name_company_uniq = models.Constraint(
        'unique(name, company_id)',
        'Linen type must be unique per company.')


class HotelLinenMove(models.Model):
    _name = 'hotel.linen.move'
    _description = "Hotel Linen Move"
    _order = 'id desc'

    linen_type_id = fields.Many2one('hotel.linen.type', string="Linen",
                                    required=True, ondelete="restrict", index=True)
    room_id = fields.Many2one('product.template', string="Room", index=True,
                              domain=[('is_room', '=', True)])
    qty = fields.Float(string="Qty", required=True, default=1.0)
    direction = fields.Selection([('issue', 'Issue'), ('return', 'Return'),
                                  ('soiled', 'Soiled')],
                                 default='issue', required=True)
    state = fields.Selection([('draft', 'Draft'), ('done', 'Done'),
                              ('returned', 'Returned')],
                             default='draft', required=True)
    company_id = fields.Many2one('res.company', string="Company",
                                 required=True, index=True,
                                 default=lambda self: self.env.company)

    @api.constrains('qty')
    def _check_qty(self):
        for rec in self:
            if rec.qty <= 0:
                raise ValidationError("Linen qty must be positive.")

    @api.constrains('linen_type_id', 'company_id')
    def _check_company(self):
        for rec in self:
            if (rec.linen_type_id.company_id
                    and rec.linen_type_id.company_id.id != rec.company_id.id):
                raise ValidationError(
                    "Linen type belongs to %s."
                    % rec.linen_type_id.company_id.display_name)

    def action_issue(self):
        self.ensure_one()
        if self.direction == 'soiled':
            raise ValidationError(
                "Soiled linen cannot be issued: create a fresh issue move.")
        if self.state != 'draft':
            raise ValidationError("Only draft moves can be issued.")
        self.write({'state': 'done', 'direction': 'issue'})
        return self

    def action_return(self):
        self.ensure_one()
        if self.direction == 'soiled':
            raise ValidationError(
                "Soiled linen cannot be returned: create a laundry return.")
        if self.state not in ('draft', 'done'):
            raise ValidationError("Only open moves can be returned.")
        self.write({'state': 'returned', 'direction': 'return'})
        return self


class HotelLostFound(models.Model):
    _name = 'hotel.lost.found'
    _description = "Hotel Lost and Found"
    _order = 'id desc'

    name = fields.Char(string="Item", required=True)
    room_id = fields.Many2one('product.template', string="Room", index=True,
                              domain=[('is_room', '=', True)])
    partner_id = fields.Many2one('res.partner', string="Guest", index=True)
    description = fields.Text(string="Description")
    found_date = fields.Date(string="Found Date", default=fields.Date.today)
    state = fields.Selection([('found', 'Found'), ('claimed', 'Claimed'),
                              ('returned', 'Returned'), ('disposed', 'Disposed')],
                             default='found', required=True)
    company_id = fields.Many2one('res.company', string="Company",
                                 required=True, index=True,
                                 default=lambda self: self.env.company)

    def action_claim(self):
        self.ensure_one()
        if self.state != 'found':
            raise ValidationError("Only found items can be claimed.")
        self.write({'state': 'claimed'})
        return self

    def action_return(self):
        self.ensure_one()
        if self.state != 'claimed':
            raise ValidationError("Only claimed items can be returned.")
        self.write({'state': 'returned'})
        return self

    def action_dispose(self):
        self.ensure_one()
        if self.state not in ('found', 'claimed'):
            raise ValidationError(
                "Only found or claimed items can be disposed (now %s)."
                % self.state)
        self.write({'state': 'disposed'})
        return self


class HotelComplaint(models.Model):
    _name = 'hotel.complaint'
    _description = "Hotel Complaint"
    _order = 'id desc'

    name = fields.Char(string="Subject", required=True)
    partner_id = fields.Many2one('res.partner', string="Guest", index=True)
    room_id = fields.Many2one('product.template', string="Room", index=True,
                              domain=[('is_room', '=', True)])
    description = fields.Text(string="Details")
    priority = fields.Selection([('0', 'Low'), ('1', 'Normal'), ('2', 'High')],
                                default='1', required=True)
    sla_deadline = fields.Datetime(string="SLA Deadline")
    state = fields.Selection([('open', 'Open'), ('in_progress', 'In Progress'),
                              ('resolved', 'Resolved'), ('closed', 'Closed')],
                             default='open', required=True)
    sla_breach = fields.Boolean(string="SLA Breach", compute='_compute_sla_breach',
                                store=True)
    company_id = fields.Many2one('res.company', string="Company",
                                 required=True, index=True,
                                 default=lambda self: self.env.company)

    @api.depends('sla_deadline', 'state')
    def _compute_sla_breach(self):
        now = fields.Datetime.now()
        for rec in self:
            rec.sla_breach = bool(
                rec.sla_deadline and rec.state in ('open', 'in_progress')
                and rec.sla_deadline < now)

    def action_start(self):
        self.ensure_one()
        if self.state != 'open':
            raise ValidationError("Only open complaints can start.")
        self.write({'state': 'in_progress'})
        return self

    def action_resolve(self):
        self.ensure_one()
        if self.state not in ('open', 'in_progress'):
            raise ValidationError("Only open complaints can resolve.")
        self.write({'state': 'resolved'})
        return self

    def action_close(self):
        self.ensure_one()
        if self.state != 'resolved':
            raise ValidationError("Only resolved complaints can close.")
        self.write({'state': 'closed'})
        return self


class HotelWakeupCall(models.Model):
    _name = 'hotel.wakeup.call'
    _description = "Hotel Wake-up Call"
    _order = 'wake_time, id'

    room_id = fields.Many2one('product.template', string="Room", required=True,
                              index=True, domain=[('is_room', '=', True)])
    partner_id = fields.Many2one('res.partner', string="Guest", index=True)
    wake_time = fields.Datetime(string="Wake Time", required=True, index=True)
    state = fields.Selection([('scheduled', 'Scheduled'), ('done', 'Done'),
                              ('cancelled', 'Cancelled'), ('missed', 'Missed')],
                             default='scheduled', required=True)
    company_id = fields.Many2one('res.company', string="Company",
                                 required=True, index=True,
                                 default=lambda self: self.env.company)

    @api.constrains('wake_time')
    def _check_wake_time(self):
        for rec in self:
            if rec.wake_time and rec.wake_time < fields.Datetime.now():
                raise ValidationError("Wake-up time cannot be in the past.")

    def action_done(self):
        self.ensure_one()
        if self.state != 'scheduled':
            raise ValidationError("Only scheduled calls can complete.")
        self.write({'state': 'done'})
        return self

    def action_cancel(self):
        self.ensure_one()
        if self.state != 'scheduled':
            raise ValidationError("Only scheduled calls can cancel.")
        self.write({'state': 'cancelled'})
        return self


class HotelStaffRoster(models.Model):
    """Daily staff roster. Links res.users + cleaning.team — no hr.employee."""
    _name = 'hotel.staff.roster'
    _description = "Hotel Staff Roster"
    _order = 'roster_date desc, id desc'

    roster_date = fields.Date(string="Date", required=True, index=True,
                              default=fields.Date.today)
    shift = fields.Selection([('morning', 'Morning'), ('evening', 'Evening'),
                              ('night', 'Night')],
                             default='morning', required=True)
    user_id = fields.Many2one('res.users', string="Staff", required=True,
                              index=True)
    team_id = fields.Many2one('cleaning.team', string="Team", index=True)
    notes = fields.Text(string="Notes")
    company_id = fields.Many2one('res.company', string="Company",
                                 required=True, index=True,
                                 default=lambda self: self.env.company)

    _user_shift_day_uniq = models.Constraint(
        'unique(user_id, roster_date, shift, company_id)',
        'Staff already rostered for this shift.')


class HotelShiftHandover(models.Model):
    _name = 'hotel.shift.handover'
    _description = "Hotel Shift Handover"
    _order = 'id desc'

    roster_id = fields.Many2one('hotel.staff.roster', string="Roster",
                                required=True, ondelete="cascade", index=True)
    notes = fields.Text(string="Handover Notes", required=True)
    state = fields.Selection([('draft', 'Draft'), ('confirmed', 'Confirmed')],
                             default='draft', required=True)
    company_id = fields.Many2one('res.company', string="Company",
                                 required=True, index=True,
                                 default=lambda self: self.env.company)

    def action_confirm(self):
        self.ensure_one()
        if not self.notes:
            raise ValidationError("Handover needs notes.")
        if self.state != 'draft':
            raise ValidationError("Only draft handovers confirm.")
        self.write({'state': 'confirmed'})
        return self


class HotelAsset(models.Model):
    """Trackable hotel asset with QR code, unique per company."""
    _name = 'hotel.asset'
    _description = "Hotel Asset"
    _order = 'id desc'

    name = fields.Char(string="Asset", required=True)
    qr_code = fields.Char(string="QR Code", required=True, index=True)
    room_id = fields.Many2one('product.template', string="Room", index=True,
                              domain=[('is_room', '=', True)])
    state = fields.Selection([('available', 'Available'), ('in_use', 'In Use'),
                              ('maintenance', 'Maintenance'),
                              ('retired', 'Retired')],
                             default='available', required=True)
    company_id = fields.Many2one('res.company', string="Company",
                                 required=True, index=True,
                                 default=lambda self: self.env.company)

    _qr_company_uniq = models.Constraint(
        'unique(qr_code, company_id)',
        'QR code must be unique per company.')

    @api.model_create_multi
    def create(self, vals_list):
        """Strip QR codes before insert so SQL unique cannot be bypassed."""
        for vals in vals_list:
            if vals.get('qr_code'):
                vals['qr_code'] = vals['qr_code'].strip()
        # Pre-insert duplicate guard: the SQL unique fires at INSERT,
        # before @api.constrains run, surfacing a raw UniqueViolation.
        # Check first so callers get ValidationError; the constraint
        # stays as the race-safe backstop.
        seen = set()
        for vals in vals_list:
            code = (vals.get('qr_code') or '').strip()
            if not code:
                continue
            company_id = vals.get('company_id') or self.env.company.id
            key = (code, company_id)
            if key in seen or self.search_count(
                    [('qr_code', '=', code),
                     ('company_id', '=', company_id)], limit=1):
                raise ValidationError(
                    "QR code %s already tracked." % code)
            seen.add(key)
        return super().create(vals_list)

    def write(self, vals):
        if vals.get('qr_code'):
            vals = dict(vals, qr_code=vals['qr_code'].strip())
        return super().write(vals)

    @api.constrains('qr_code')
    def _check_qr(self):
        for rec in self:
            if not (rec.qr_code or '').strip():
                raise ValidationError("QR code is required.")
            dup = self.search([
                ('qr_code', '=', rec.qr_code.strip()),
                ('company_id', '=', rec.company_id.id),
                ('id', '!=', rec.id),
            ], limit=1)
            if dup:
                raise ValidationError(
                    "QR code %s already tracked." % rec.qr_code.strip())

    @api.model
    def track_by_qr(self, qr_code):
        """Mobile/QR scan entry point: code -> asset (company-safe)."""
        if not (qr_code or '').strip():
            raise ValidationError("QR code is required.")
        asset = self.search([
            ('qr_code', '=', qr_code.strip()),
            ('company_id', '=', self.env.company.id),
        ], limit=1)
        if not asset:
            raise ValidationError("No asset for QR %s." % qr_code.strip())
        return asset

    def action_send_maintenance(self):
        self.ensure_one()
        if self.state not in ('available', 'in_use'):
            raise ValidationError("Only usable assets go to maintenance.")
        self.write({'state': 'maintenance'})
        return self
