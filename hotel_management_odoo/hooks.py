# -*- coding: utf-8 -*-
"""Seed room type + room kanban images from the Esidai website galleries.

Source: https://www.esidaisparesort.com/rooms/ (client's own site).
Files live in static/src/img/rooms/ so fresh installs and upgrades can
re-seed without network access. Idempotent: only fills empty images,
never overwrites a user upload.
"""
import base64
import logging
import os

from odoo.modules.module import get_module_path

_logger = logging.getLogger(__name__)

ROOM_IMG_SUBDIR = os.path.join('static', 'src', 'img', 'rooms')

# Room-type keyword -> website gallery files (first = type cover).
TYPE_IMAGES = {
    'deluxe': ['deluxe_1.webp', 'deluxe_2.webp', 'deluxe_3.webp'],
    'family': ['family_1.webp', 'family_2.webp', 'family_3.webp'],
    'executive': ['exec_1.webp', 'exec_2.webp', 'exec_3.webp'],
}

# Hero cover per type (what the rooms page leads with).
TYPE_COVER = {
    'deluxe': 'deluxe_1.webp',
    'family': 'family_1.webp',
    'executive': 'exec_2.webp',
}


def _load(filename):
    base = get_module_path('hotel_management_odoo')
    path = os.path.join(base, ROOM_IMG_SUBDIR, filename) if base else None
    if not path or not os.path.exists(path):
        _logger.warning("Room image missing: %s", filename)
        return False
    with open(path, 'rb') as f:
        return base64.b64encode(f.read()).decode('ascii')


def _type_key(name):
    low = (name or '').lower()
    for key in TYPE_IMAGES:
        if key in low:
            return key
    return False


def seed_room_images(env):
    """Fill empty hotel.room.type.image + room product image_1920."""
    RoomType = env['hotel.room.type']
    Rooms = env['product.template']

    types = RoomType.search([])
    for rec in types:
        key = _type_key(rec.name)
        if not key:
            continue
        if rec.image:
            continue
        data = _load(TYPE_COVER[key])
        if data:
            rec.write({'image': data})
            _logger.info("Room type %s seeded with %s", rec.name, TYPE_COVER[key])

    rooms = Rooms.search([('is_room', '=', True)], order='name')
    grouped = {}
    for room in rooms:
        key = _type_key(room.room_type_id.name) if room.room_type_id else False
        if not key:
            # Fall back to legacy selection label (single/double/dormitory):
            # single -> deluxe look, double -> deluxe, dormitory -> family.
            legacy = (room.room_type or '').lower()
            key = 'family' if legacy == 'dormitory' else 'deluxe'
        grouped.setdefault(key, []).append(room)

    for key, recs in grouped.items():
        files = TYPE_IMAGES[key]
        for i, room in enumerate(recs):
            if room.image_1920:
                continue
            data = _load(files[i % len(files)])
            if data:
                room.write({'image_1920': data})
                _logger.info("Room %s seeded with %s", room.display_name, files[i % len(files)])
    return True


def post_init_hook(env):
    seed_room_images(env)
