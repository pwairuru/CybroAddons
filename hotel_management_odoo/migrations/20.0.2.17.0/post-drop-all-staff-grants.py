# -*- coding: utf-8 -*-
"""Post-migration for 20.0.2.17.0: drop obsolete all-staff hotel grants.

security/ir.access.csv no longer contains the base.group_user rows for
guest-data and operational models (bookings, folios, deposits, ledgers,
guest documents, loyalty entries, reports, rosters, ...). Odoo never
garbage-collects access rows removed from CSV, so the old grants would
otherwise stay active after upgrade and POS cashiers would keep seeing
hotel data in the backend.

Idempotent: missing external ids are skipped.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

OBSOLETE_XML_IDS = [
    'access_room_booking_user',
    'access_room_booking_line_user',
    'access_food_booking_line_user',
    'access_service_booking_line_user',
    'access_fleet_booking_line_user',
    'access_event_booking_line_user',
    'access_room_booking_detail_user',
    'access_sale_order_detail_user',
    'access_compute_bill_user',
    'access_hotel_post_stay_user',
    'access_hotel_folio_split_user',
    'access_hotel_folio_user',
    'access_hotel_deposit_user',
    'access_hotel_city_ledger_user',
    'access_hotel_cashier_shift_user',
    'access_hotel_folio_line_user',
    'access_hotel_business_date_user',
    'access_hotel_night_audit_user',
    'access_hotel_conference_attendee_user',
    'access_hotel_channel_message_user',
    'access_hotel_document_user',
    'access_hotel_loyalty_entry_user',
    'access_hotel_linen_move_user',
    'access_hotel_lost_found_user',
    'access_hotel_complaint_user',
    'access_hotel_wakeup_call_user',
    'access_hotel_staff_roster_user',
    'access_hotel_shift_handover_user',
    'access_hotel_report_pack_user',
]


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    dropped = 0
    for xml_id in OBSOLETE_XML_IDS:
        access = env.ref(
            'hotel_management_odoo.' + xml_id, raise_if_not_found=False)
        if access is None:
            continue
        _logger.info("CASHIER_LOCKDOWN: dropping obsolete grant %s (id %s)",
                     xml_id, access.id)
        access.unlink()
        dropped += 1
    _logger.info("CASHIER_LOCKDOWN: dropped %s obsolete all-staff grants",
                 dropped)
