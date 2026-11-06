"""Seed room type + room images from the Esidai website galleries.

One-shot backfill for existing DBs; fresh installs use post_init_hook.
Idempotent: hooks.seed_room_images only fills empty images.
"""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    from odoo.addons.hotel_management_odoo.hooks import seed_room_images
    env = api.Environment(cr, SUPERUSER_ID, {})
    seed_room_images(env)
