# -*- coding: utf-8 -*-
"""Pre-migration for 20.0.2.0.0: stash rule meal values + All Year fill.

Step 1: copies every rule meal line plus its rule's priority, dates
and old period link into temp table ``hotel_rule_meal_mig`` (the
source tables are dropped at sync, so post-migration cannot read
them via ORM).

Step 2: ``hotel.rate.rule.period_id`` becomes required. Pre-fill
nulls so the NOT NULL lands cleanly: null links point at a
pre-created "All Year" Jan-Dec period (created here only when
needed, sequence 999 so month periods win pick-first loops while
All Year remains the fallback); old links are kept as-is.
``period_year`` nulls fill from the rule year or current year.
Coverage refinement and value writing live in post-migration.
"""
import logging

_logger = logging.getLogger(__name__)

_MIG_TAG = "PERIOD_MEAL_MIGRATION"


def _has_table(cr, name):
    cr.execute("SELECT to_regclass(%s)", ('public.' + name,))
    return bool(cr.fetchone()[0])


def _stash_rule_lines(cr):
    cr.execute("""
        CREATE TABLE IF NOT EXISTS hotel_rule_meal_mig AS
        SELECT l.id AS line_id, l.rule_id, l.meal_plan_id,
               l.rate_type, l.value, r.priority AS rule_priority,
               r.date_from AS rule_from, r.date_to AS rule_to,
               r.period_id AS old_period_id,
               r.period_year AS old_period_year
        FROM hotel_rate_rule_meal_line l
        JOIN hotel_rate_rule r ON r.id = l.rule_id
    """)
    cr.execute("SELECT COUNT(*) FROM hotel_rule_meal_mig")
    stashed = cr.fetchone()[0]
    _logger.info("%s: stashed %s rule meal line(s) into "
                 "hotel_rule_meal_mig.", _MIG_TAG, stashed)


def _ensure_all_year_id(cr):
    cr.execute("""
        SELECT id FROM hotel_rate_period
        WHERE start_md = '01-01' AND end_md = '12-31'
        ORDER BY id LIMIT 1
    """)
    found = cr.fetchone()
    if found:
        return found[0]
    cr.execute("SELECT column_name FROM information_schema.columns "
               "WHERE table_name = 'hotel_rate_period' "
               "AND column_name = 'priority'")
    has_priority = bool(cr.fetchone())
    if has_priority:
        cr.execute("""
            INSERT INTO hotel_rate_period
                (name, start_md, end_md, sequence, priority, active)
            SELECT 'All Year', '01-01', '12-31', 999, 0, TRUE
            WHERE NOT EXISTS (
                SELECT 1 FROM hotel_rate_period
                WHERE start_md = '01-01' AND end_md = '12-31')
            RETURNING id
        """)
    else:  # pragma: no cover - intermediate-version safety net
        cr.execute("""
            INSERT INTO hotel_rate_period
                (name, start_md, end_md, sequence, active)
            SELECT 'All Year', '01-01', '12-31', 999, TRUE
            WHERE NOT EXISTS (
                SELECT 1 FROM hotel_rate_period
                WHERE start_md = '01-01' AND end_md = '12-31')
            RETURNING id
        """)
    created = cr.fetchone()
    if created:
        _logger.info("%s: created All Year period (id %s).",
                     _MIG_TAG, created[0])
        return created[0]
    cr.execute("""
        SELECT id FROM hotel_rate_period
        WHERE start_md = '01-01' AND end_md = '12-31'
        ORDER BY id LIMIT 1
    """)
    return cr.fetchone()[0]


def _prefill_period_links(cr):
    cr.execute("SELECT COUNT(*) FROM hotel_rate_rule "
               "WHERE period_id IS NULL")
    nulls = cr.fetchone()[0]
    if nulls:
        all_year_id = _ensure_all_year_id(cr)
        cr.execute("UPDATE hotel_rate_rule SET period_id = %s "
                   "WHERE period_id IS NULL", (all_year_id,))
        _logger.info("%s: pointed %s rule(s) with null period at "
                     "All Year (id %s).",
                     _MIG_TAG, cr.rowcount, all_year_id)
    else:
        _logger.info("%s: no null rule period links; All Year not "
                     "needed.", _MIG_TAG)
    cr.execute("""
        UPDATE hotel_rate_rule
        SET period_year = COALESCE(
            period_year,
            EXTRACT(YEAR FROM date_from)::int,
            EXTRACT(YEAR FROM now())::int)
        WHERE period_year IS NULL
    """)
    _logger.info("%s: filled period_year on %s rule(s).",
                 _MIG_TAG, cr.rowcount)


def migrate(cr, version):
    if not _has_table(cr, 'hotel_rate_rule_meal_line'):
        _logger.info("%s: no old rule meal line table (fresh install); "
                     "nothing to stash.", _MIG_TAG)
        return
    _stash_rule_lines(cr)
    _prefill_period_links(cr)
