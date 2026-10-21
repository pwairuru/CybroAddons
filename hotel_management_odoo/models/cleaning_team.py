# -*- coding: utf-8 -*-
#############################################################################
#
#    Cybrosys Technologies Pvt. Ltd.
#
#    Copyright (C) 2026-TODAY Cybrosys Technologies(<https://www.cybrosys.com>)
#    Author: Cybrosys Techno Solutions(<https://www.cybrosys.com>)
#
#    You can modify it under the terms of the GNU LESSER
#    GENERAL PUBLIC LICENSE (LGPL v3), Version 3.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU LESSER GENERAL PUBLIC LICENSE (LGPL v3) for more details.
#
#    You should have received a copy of the GNU LESSER GENERAL PUBLIC LICENSE
#    (LGPL v3) along with this program.
#    If not, see <http://www.gnu.org/licenses/>.
#
#############################################################################
from odoo import fields, models


class CleaningTeam(models.Model):
    """ Model for creating Cleaning team and assigns Cleaning requests to
    each team"""
    _name = "cleaning.team"
    _description = "Cleaning Team"

    name = fields.Char(string="Team Name", help="Name of the Team")
    company_id = fields.Many2one('res.company', string="Company",
                                 index=True,
                                 default=lambda self: self.env.company,
                                 help="Property this team belongs to")
    team_head_id = fields.Many2one('res.users', string="Team Head",
                                   help="Choose the Team Head",
                                   domain=lambda self: [
                                       ('group_ids', 'in', self.env.ref(
                                           'hotel_management_odoo.'
                                           'cleaning_team_group_head').id)])
    member_ids = fields.Many2many('res.users',
                                  relation='cleaning_team_member_user_rel',
                                  column1='team_id', column2='user_id',
                                  string="Member",
                                  help="Team Members",
                                  domain=lambda self: [
                                      ('group_ids', 'in', self.env.ref(
                                          'hotel_management_odoo.'
                                          'cleaning_team_group_user').id)])
    # Task 10 glue: roster coverage + active flag. No hr.employee link.
    area = fields.Char(string="Coverage Area",
                       help="Floors or zones this team covers")
    max_rooms_per_day = fields.Integer(string="Max Rooms / Day", default=12,
                                       help="Roster capacity guard")
    roster_ids = fields.One2many('hotel.staff.roster', 'team_id',
                                 string="Rosters")
    active = fields.Boolean(default=True)