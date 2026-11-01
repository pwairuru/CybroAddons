"""Drop the server-side kanban shell view (moved client-side).

hotel_kanban_card_shell was defined as a backend ir.ui.view QWeb record
but t-called from kanban archs, which render client-side in Owl and
cannot see server templates ("Missing template" OwlError). The shell
now lives in static/src/xml/kanban_card_templates.xml (web.assets_backend).
Removing the data file orphans the record, so delete it here.
"""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    view = env.ref(
        'hotel_management_odoo.hotel_kanban_card_shell', raise_if_not_found=False)
    if view:
        view.unlink()
