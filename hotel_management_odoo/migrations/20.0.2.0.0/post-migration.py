# -*- coding: utf-8 -*-
"""Post-migration for 20.0.2.0.0: period-line values from stashed rules.

Step 1: ensure five zero lines on every period (missing-only).
Step 2: resolve each stashed rule to its final period — old link
  wins; else the single active period covering both rule endpoint
  month-days in the rule year (applies_year must be null or equal;
  the All Year catch-all is excluded from candidates and serves as
  the fallback); else All Year. Writes rule.period_id/period_year.
Step 3: per period+plan, the highest-priority (then lowest rule id)
  stashed value wins; writes it onto the period line. Every
  overridden conflicting value is logged as PERIOD_LINE_CONFLICT
  with rule, plan, losing and winning values.
Step 4: drop the temp table. Idempotent: reruns find lines present
  and an empty temp table and do nothing.
"""
import logging

from odoo import SUPERUSER_ID, api, fields

_logger = logging.getLogger(__name__)

_MIG_TAG = "PERIOD_MEAL_MIGRATION"
_CONFLICT_TAG = "PERIOD_LINE_CONFLICT"


def _has_table(cr, name):
    cr.execute("SELECT to_regclass(%s)", ('public.' + name,))
    return bool(cr.fetchone()[0])


def _all_year(env):
    period = env['hotel.rate.period'].search(
        [('start_md', '=', '01-01'), ('end_md', '=', '12-31')],
        order='id', limit=1)
    if not period:
        # Sequence 999: month periods (low sequences) win pick-first
        # loops (default_get, matrix labels); All Year stays fallback.
        period = env['hotel.rate.period'].create({
            'name': 'All Year',
            'start_md': '01-01',
            'end_md': '12-31',
            'sequence': 999,
            'priority': 0,
        })
        _logger.info("%s: created All Year period (id %s).",
                     _MIG_TAG, period.id)
    return period


def _resolve_period(env, active_periods, all_year, old_period_id,
                    rule_from, rule_to, year):
    if old_period_id:
        old = env['hotel.rate.period'].browse(old_period_id)
        if old.exists() and (
                not year or not old.applies_year
                or old.applies_year == year):
            return old
    if rule_from and rule_to and year:
        from_md = (rule_from.month, rule_from.day)
        to_md = (rule_to.month, rule_to.day)
        fits = [
            p for p in active_periods
            if (all_year is None or p.id != all_year.id)
            and (not p.applies_year or p.applies_year == year)
            and p.covers(*from_md) and p.covers(*to_md)
        ]
        if len(fits) == 1:
            return fits[0]
    return all_year


def _write_winners(env, grouped):
    line_model = env['hotel.rate.period.meal.line']
    written = 0
    conflicts = 0
    for (period_id, plan_id), rows in sorted(grouped.items()):
        rows = sorted(rows,
                      key=lambda r: (-(r['rule_priority'] or 0),
                                     r['rule_id']))
        winner = rows[0]
        line = line_model.search([
            ('period_id', '=', period_id),
            ('meal_plan_id', '=', plan_id),
        ], limit=1)
        if not line:
            line = line_model.create({
                'period_id': period_id,
                'meal_plan_id': plan_id,
                'rate_type': winner['rate_type'],
                'value': winner['value'] or 0.0,
            })
        else:
            line.write({
                'rate_type': winner['rate_type'],
                'value': winner['value'] or 0.0,
            })
        written += 1
        for loser in rows[1:]:
            if (loser['rate_type'], loser['value'] or 0.0) == \
                    (winner['rate_type'], winner['value'] or 0.0):
                continue
            conflicts += 1
            _logger.warning(
                "%s: rule %s (priority %s) plan %s losing %s %s "
                "overwritten by rule %s winning %s %s on period %s.",
                _CONFLICT_TAG, loser['rule_id'],
                loser['rule_priority'],
                loser['plan_code'], loser['rate_type'],
                loser['value'], winner['rule_id'],
                winner['rate_type'], winner['value'], period_id)
    return written, conflicts


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    periods = env['hotel.rate.period'].search([])
    if periods:
        periods.ensure_meal_lines()
    if not _has_table(cr, 'hotel_rule_meal_mig'):
        _logger.info("%s: no stash table (fresh install or rerun); "
                     "ensured meal lines only.", _MIG_TAG)
        return
    cr.execute("""
        SELECT line_id, rule_id, meal_plan_id, rate_type, value,
               rule_priority, rule_from, rule_to,
               old_period_id, old_period_year
        FROM hotel_rule_meal_mig
        ORDER BY rule_priority DESC NULLS LAST, rule_id, meal_plan_id
    """)
    cols = [d[0] for d in cr.description]
    stashed = [dict(zip(cols, row)) for row in cr.fetchall()]
    if not stashed:
        cr.execute("DROP TABLE hotel_rule_meal_mig")
        _logger.info("%s: empty stash; ensured meal lines on %s "
                     "period(s) and dropped temp table.",
                     _MIG_TAG, len(periods))
        return
    active_periods = env['hotel.rate.period'].search(
        [('active', '=', True)], order='sequence')
    all_year = env['hotel.rate.period'].search(
        [('start_md', '=', '01-01'), ('end_md', '=', '12-31')],
        order='id', limit=1)
    # All Year is created lazily: pre-migration may already have made
    # it for the NOT NULL fill, but a post-only fallback need must not
    # conjure one on DBs where every rule resolves elsewhere.
    plan_codes = {
        p.id: p.code
        for p in env['hotel.meal.plan'].search([])
    }
    grouped = {}
    resolved_lines = 0
    resolved_rules = set()
    for row in stashed:
        rule = env['hotel.rate.rule'].browse(row['rule_id'])
        if not rule.exists():
            _logger.warning(
                "%s: stashed rule %s no longer exists; skipping "
                "line %s.", _MIG_TAG, row['rule_id'], row['line_id'])
            continue
        year = row['old_period_year'] or rule.period_year \
            or fields.Date.today().year
        final = _resolve_period(
            env, active_periods, all_year, row['old_period_id'],
            row['rule_from'], row['rule_to'], year)
        # Empty recordset (no All Year on DB) is falsy like None:
        # both mean the rule needs the lazily created fallback.
        if not final:
            all_year = _all_year(env)
            all_year.ensure_meal_lines()
            active_periods = env['hotel.rate.period'].search(
                [('active', '=', True)], order='sequence')
            final = all_year
        vals = {}
        if rule.period_id.id != final.id:
            vals['period_id'] = final.id
        if rule.period_year != year:
            vals['period_year'] = year
        if vals:
            rule.write(vals)
        resolved_lines += 1
        resolved_rules.add(row['rule_id'])
        row['plan_code'] = plan_codes.get(row['meal_plan_id'], '?')
        grouped.setdefault((final.id, row['meal_plan_id']),
                           []).append(row)
    written, conflicts = _write_winners(env, grouped)
    cr.execute("DROP TABLE hotel_rule_meal_mig")
    _logger.info(
        "%s: resolved %s stashed line(s) across %s rule(s), wrote %s "
        "period line value(s) with %s conflict(s); dropped temp table.",
        _MIG_TAG, resolved_lines, len(resolved_rules), written, conflicts)
