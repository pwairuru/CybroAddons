# -*- coding: utf-8 -*-
"""Shared state-guard + meal-line helpers (behavior-preserving).

Covers cleaning/maintenance request transitions, service-ops
single-state guards, meal-line coverage, QR normalization and
capacity message formatting. All helpers raise the exact legacy
messages; callers keep identical behavior.
"""
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class HotelStateGuarded(models.AbstractModel):
    """Mixin for models with a _STATE_FLOW dict.

    Expects ``_STATE_FLOW = {current: (allowed_next, ...)}`` on the
    concrete model. Error text matches the legacy per-model messages:
    ``Cannot move <description> <key> from <state> to <target>.``
    where key is sequence (or name fallback).
    """
    _name = 'hotel.state.guarded'
    _description = "Hotel State Guarded"

    def _check_request_transition(self, target):
        for rec in self:
            allowed = (rec._STATE_FLOW or {}).get(rec.state, ())
            if target not in allowed:
                key = getattr(rec, 'sequence', False) \
                    or getattr(rec, 'name', '')
                raise ValidationError(
                    'Cannot move %s %s from %s to %s.'
                    % (rec._description.lower(), key,
                       rec.state, target))
        return True

    def _require_state(self, allowed, message):
        """Single-state guard for service-ops models.

        ``allowed`` is a state or tuple of states; raises
        ValidationError with the caller's exact legacy message.
        """
        if isinstance(allowed, str):
            allowed = (allowed,)
        for rec in self:
            if rec.state not in allowed:
                raise ValidationError(message)
        return True


def _normalize_qr(code):
    """Strip QR whitespace; empty stays empty (validators reject)."""
    return (code or '').strip()


def ensure_active_plan_lines(records, line_model_name, owner_field,
                             plan_field='meal_plan_id', defaults=None):
    """Create missing per-plan lines for each record in ``records``.

    ``owner_field`` is the Many2one on the line pointing back
    (e.g. ``period_id`` / ``room_type_id``). ``defaults`` are the
    extra vals for a missing line. Returns True.
    """
    if not records:
        return True
    env = records.env
    plans = env['hotel.meal.plan'].search([('active', '=', True)])
    if not plans:
        return True
    line_model = env[line_model_name]
    plan_ids = plans.ids
    owner_ids = records.ids
    have = {
        (line[owner_field].id, line[plan_field].id)
        for line in line_model.search([
            (owner_field, 'in', owner_ids),
            (plan_field, 'in', plan_ids),
        ])
    }
    missing = []
    for record in records:
        for plan in plans:
            if (record.id, plan.id) not in have:
                vals = {owner_field: record.id, plan_field: plan.id}
                vals.update(defaults or {})
                missing.append(vals)
    if missing:
        line_model.create(missing)
    return True
