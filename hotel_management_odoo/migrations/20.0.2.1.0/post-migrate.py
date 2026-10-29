# -*- coding: utf-8 -*-
"""Post-migration for 20.0.2.1.0: reseed rate lines from meal prices.

H1/H2 arrive via data XML; this backfills null period companies and
seeds one ``hotel.rate.line`` per H1/H2 period x room type x meal plan
where a price exists (meal price > 0, or RO falling back to the type
``base_rate``; other boards with no meal price are skipped).
Included counts come from occupancy bands (the rate plan matching
the meal code wins per band, else the type default) or the type
capacities; extra modes/values come
from occupancy or default to fixed 0. Missing-only: existing lines are
never overwritten (same effect as INSERT ... ON CONFLICT DO NOTHING on
the ``hotel_rate_line_rate_line_uniq`` guard). Idempotent: reruns find
lines present and do nothing.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

_MIG_TAG = "RATE_LINE_RESEED"

_H1H2 = (
    ('H1', '01-01', '06-30', 10),
    ('H2', '07-01', '12-31', 20),
)


def _band_map(env, room_type, plan=None):
    """Occupancy per band for one rate plan; generic type default wins.

    ``plan`` is a ``hotel.rate.plan``: its record for the band wins,
    otherwise the plan-empty type default applies. Records for other
    plans are ignored so each seeded line reflects its own plan.
    """
    out = {}
    for occ in env['hotel.rate.occupancy'].search(
            [('room_type_id', '=', room_type.id)]):
        if occ.plan_id and (not plan or occ.plan_id.id != plan.id):
            continue
        if occ.plan_id:
            out[occ.band] = occ
        else:
            out.setdefault(occ.band, occ)
    return out


def _rate_plan_for_meal(env, meal, company):
    """Rate plan matching a meal code, else empty (generic bands)."""
    if not meal or not meal.code:
        return env['hotel.rate.plan'].browse()
    return env['hotel.rate.plan'].search([
        ('company_id', '=', company.id),
        ('code', '=', meal.code),
    ], limit=1)


def _included(rtype, bands):
    inc_a = bands['adult'].included_count \
        if 'adult' in bands else (rtype.adult_capacity or 0)
    inc_c = bands['child'].included_count \
        if 'child' in bands else (rtype.child_capacity or 0)
    inc_a, inc_c = max(int(inc_a), 0), max(int(inc_c), 0)
    cap = int(rtype.max_occupants or 0)
    if cap and inc_a + inc_c > cap:
        inc_c = min(inc_c, max(cap - inc_a, 0))
        inc_a = min(inc_a, cap)
    return inc_a, inc_c


def _extras(bands):
    vals = {}
    for band, prefix in (('adult', 'extra_adult'),
                         ('child', 'extra_child')):
        occ = bands.get(band)
        if occ:
            vals[prefix + '_mode'] = occ.mode or 'fixed'
            vals[prefix + '_value'] = float(occ.value or 0.0)
        else:
            vals[prefix + '_mode'] = 'fixed'
            vals[prefix + '_value'] = 0.0
    return vals


_LEGACY_MONTHS = (
    'January', 'February', 'March', 'April', 'May', 'June',
    'July', 'August', 'September', 'October', 'November', 'December',
)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    # Retire only the legacy monthlies by exact name: H1/H2 (kept by
    # exclusion) and any promo override (custom names, applies_year)
    # are never touched.
    with cr.savepoint():
        cr.execute(
            "UPDATE hotel_rate_period SET active = false "
            "WHERE active AND name IN %s", (_LEGACY_MONTHS,))
        if cr.rowcount:
            _logger.info("%s: retired %d legacy period(s).",
                         _MIG_TAG, cr.rowcount)
    cr.execute(
        "UPDATE hotel_rate_period SET company_id = "
        "(SELECT id FROM res_company ORDER BY id LIMIT 1) "
        "WHERE company_id IS NULL")
    if cr.rowcount:
        _logger.info("%s: backfilled company on %d period(s).",
                     _MIG_TAG, cr.rowcount)
    company = env['res.company'].search([], order='id', limit=1)
    periods = env['hotel.rate.period'].search([('name', 'in', ['H1', 'H2'])])
    have = set(periods.mapped('name'))
    for name, start, end, seq in _H1H2:
        if name not in have:
            periods |= env['hotel.rate.period'].create({
                'name': name, 'start_md': start, 'end_md': end,
                'sequence': seq, 'priority': 10,
                'company_id': company.id,
            })
            _logger.info("%s: created missing period %s.", _MIG_TAG, name)
    if not periods:
        _logger.warning("%s: no H1/H2 periods; nothing to seed.", _MIG_TAG)
        return
    plans = env['hotel.meal.plan'].search(
        [('active', '=', True)], order='sequence')
    rtypes = env['hotel.room.type'].search([])
    Line = env['hotel.rate.line']
    created, present, skipped = 0, 0, 0
    for period in periods:
        for rtype in rtypes:
            if rtype.company_id.id != period.company_id.id:
                skipped += 1
                continue
            currency = (period.company_id.currency_id
                        or company.currency_id)
            for plan in plans:
                rate_plan = _rate_plan_for_meal(
                    env, plan, period.company_id)
                bands = _band_map(env, rtype, rate_plan)
                inc_a, inc_c = _included(rtype, bands)
                extras = _extras(bands)
                mline = rtype.meal_price_ids.filtered(
                    lambda l, pid=plan.id: l.meal_plan_id.id == pid)[:1]
                mprice = float(mline.price) if mline else 0.0
                if mprice > 0:
                    price = mprice
                elif plan.code == 'RO':
                    price = float(rtype.base_rate or 0.0)
                else:
                    skipped += 1
                    continue
                if Line.search([
                        ('period_id', '=', period.id),
                        ('room_type_id', '=', rtype.id),
                        ('meal_plan_id', '=', plan.id),
                        ('company_id', '=', period.company_id.id),
                        ], limit=1):
                    present += 1
                    continue
                try:
                    with cr.savepoint():
                        Line.create({
                            'period_id': period.id,
                            'room_type_id': rtype.id,
                            'meal_plan_id': plan.id,
                            'company_id': period.company_id.id,
                            'currency_id': currency.id,
                            'price': price,
                            'included_adults': inc_a,
                            'included_children': inc_c,
                            **extras,
                        })
                except Exception as exc:
                    _logger.warning(
                        "%s: skip %s/%s/%s: %s.", _MIG_TAG,
                        period.name, rtype.name, plan.code, exc)
                    skipped += 1
                    continue
                created += 1
    _logger.info("%s: seeded %d line(s), %d present, %d skipped.",
                 _MIG_TAG, created, present, skipped)
