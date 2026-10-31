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
{
    'name': 'Hotel Management',
    'version': '20.0.2.4.0',
    'category': 'Industries',
    'summary': """A complete Hotel Management System that cover all areas of 
     Hotel services""" ,
    'description': """The module helps you to manage rooms, amenities, 
     services, food, events and vehicles. End Users can book rooms and reserve 
     foods from hotel.""",
    'author': 'Cybrosys Techno Solutions',
    'company': 'Cybrosys Techno Solutions',
    'maintainer': 'Cybrosys Techno Solutions',
    'website': 'https://www.cybrosys.com',
    'depends': ['mail', 'account', 'event', 'fleet', 'lunch', 'maintenance', 'point_of_sale'],
    'data': [
        'security/hotel_management_odoo_groups.xml',
        'security/hotel_management_odoo_security.xml',
        'security/ir.access.csv',
        'data/ir_data_sequence.xml',
        'data/account_payment_fix.xml',
        'views/rate_calendar_view.xml',
        'views/account_move_views.xml',
        'views/hotel_menu_views.xml',
        'views/hotel_rate_line_views.xml',
        'views/hotel_room_type_views.xml',
        'views/hotel_kanban_card_templates.xml',
        'views/product_template.xml',
        'views/hotel_amenity_views.xml',
        'views/hotel_service_views.xml',
        'views/hotel_floor_views.xml',
        'views/lunch_product_views.xml',
        'views/fleet_vehicle_model_views.xml',
        'wizard/hotel_post_stay_views.xml',
        'wizard/hotel_folio_split_views.xml',
        'views/booking_line_lists.xml',
        'views/room_booking_views.xml',
        'views/maintenance_team_views.xml',
        'views/maintenance_request_views.xml',
        'views/cleaning_team_views.xml',
        'views/cleaning_request_views.xml',
        'views/hotel_service_ops_views.xml',
        'views/food_booking_line_views.xml',
        'views/hotel_folio_views.xml',
        'views/hotel_guest_views.xml',
        'data/hotel_guest_data.xml',
        'data/hotel_meal_plan_data.xml',
        'data/hotel_rate_period_data.xml',
        'views/hotel_night_audit_views.xml',
        'views/hotel_rate_views.xml',
        'views/hotel_rate_period_views.xml',
        'views/hotel_meal_plan_views.xml',
        'views/res_company_views.xml',
        'views/hotel_conference_views.xml',
        'views/hotel_cashier_views.xml',
        'views/dashboard_view.xml',
        'views/tape_chart_view.xml',
        'wizard/room_booking_detail_views.xml',
        'wizard/sale_order_detail_views.xml',
        'wizard/compute_bill_views.xml',
        'views/reporting_views.xml',
        'wizard/hotel_report_pack_views.xml',
        'wizard/hotel_rate_line_generator_views.xml',
        'report/room_booking_reports.xml',
        'report/sale_order_reports.xml',
        'report/combined_bill_report.xml',
        'report/hotel_reports.xml',
        'report/hotel_folio_statement.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'hotel_management_odoo/static/src/js/action_manager.js',
            'hotel_management_odoo/static/src/js/dashboard_action.js',
            'hotel_management_odoo/static/src/js/tape_chart.js',
            'hotel_management_odoo/static/src/js/rate_calendar.js',
            'hotel_management_odoo/static/src/css/dashboard.css',
            'hotel_management_odoo/static/src/css/list_avatar.css',
            'hotel_management_odoo/static/src/css/tape_chart.css',
            'hotel_management_odoo/static/src/css/rate_calendar.css',
            'hotel_management_odoo/static/src/xml/dashboard_templates.xml',
            'hotel_management_odoo/static/src/xml/tape_chart_templates.xml',
            'hotel_management_odoo/static/src/xml/rate_calendar_templates.xml',
        ],
    },
    'images': ['static/description/banner.jpg'],
    'license': 'LGPL-3',
    'installable': True,
    'auto_install': False,
    'application': True,
}
