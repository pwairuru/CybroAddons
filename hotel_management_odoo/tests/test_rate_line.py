# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase
from odoo.exceptions import ValidationError


class TestRateLine(TransactionCase):
    def test_find_applicable_orders_priority(self):
        co = self.env.company
        base = self.env['hotel.rate.period'].create({
            'name': 'BasePri', 'start_md': '01-01', 'end_md': '12-31',
            'sequence': 10, 'priority': 10, 'company_id': co.id})
        promo = self.env['hotel.rate.period'].create({
            'name': 'PromoPri', 'start_md': '04-18', 'end_md': '04-21',
            'sequence': 5, 'priority': 100, 'company_id': co.id,
            'applies_year': 2027})
        found = self.env['hotel.rate.period']._find_applicable('2027-04-19')
        ids = [p.id for p in found]
        self.assertIn(promo.id, ids)
        self.assertIn(base.id, ids)
        self.assertLess(ids.index(promo.id), ids.index(base.id))


class TestRateLineMath(TransactionCase):
    def setUp(self):
        super().setUp()
        self.co = self.env.company
        self.type = self.env['hotel.room.type'].create({'name':'Family','base_rate':20000.0,'adult_capacity':2,'child_capacity':3,'max_occupants':5,'charge_mode':'per_room'})
        self.meal_ro = self.env['hotel.meal.plan'].search([('code','=','RO')], limit=1)
        self.h1 = self.env['hotel.rate.period'].create({'name':'H1','start_md':'01-01','end_md':'06-30','sequence':10,'priority':10,'company_id':self.co.id})
        self.room = self.env['product.template'].create({'name':'FAM-101','is_room':True,'room_type':'double','num_person':5,'list_price':20000.0,'room_type_id':self.type.id})
    def test_family_fifth_child_half(self):
        line = self.env['hotel.rate.line'].create({'company_id':self.co.id,'period_id':self.h1.id,'room_type_id':self.type.id,'meal_plan_id':self.meal_ro.id,'price':20000.0,'included_adults':2,'included_children':2,'extra_child_mode':'percent','extra_child_value':50.0})
        calc = line.compute_night(adults=2, children=3)
        self.assertEqual(calc['net'], 22500.0)
    def test_per_person(self):
        self.type.write({'charge_mode':'per_person'})
        line = self.env['hotel.rate.line'].create({'company_id':self.co.id,'period_id':self.h1.id,'room_type_id':self.type.id,'meal_plan_id':self.meal_ro.id,'price':10000.0,'included_children':1,'extra_child_mode':'fixed','extra_child_value':1500.0})
        calc = line.compute_night(adults=2, children=2)
        self.assertEqual(calc['net'], 21500.0)
    def test_priority_override_fallback(self):
        promo = self.env['hotel.rate.period'].create({'name':'Easter','start_md':'04-18','end_md':'04-21','sequence':5,'priority':100,'company_id':self.co.id,'applies_year':2027})
        eng = self.env['hotel.rate.engine']
        base = self.env['hotel.rate.line'].create({'company_id':self.co.id,'period_id':self.h1.id,'room_type_id':self.type.id,'meal_plan_id':self.meal_ro.id,'price':20000.0})
        over = self.env['hotel.rate.line'].create({'company_id':self.co.id,'period_id':promo.id,'room_type_id':self.type.id,'meal_plan_id':self.meal_ro.id,'price':25000.0})
        self.assertEqual(eng.price_for(self.room.id, '2027-04-19', None, adults=2, board='RO'), 25000.0)
        self.assertEqual(eng.price_for(self.room.id, '2027-05-01', None, adults=2, board='RO'), 20000.0)
    def test_missing_line_raises(self):
        eng = self.env['hotel.rate.engine']
        with self.assertRaises(ValidationError):
            eng.price_for(self.room.id, '2027-02-01', None, adults=2, board='BB')
    def test_over_capacity_raises(self):
        eng = self.env['hotel.rate.engine']
        self.env['hotel.rate.line'].create({'company_id':self.co.id,'period_id':self.h1.id,'room_type_id':self.type.id,'meal_plan_id':self.meal_ro.id,'price':20000.0})
        with self.assertRaises(ValidationError):
            eng.price_for(self.room.id, '2027-02-01', None, adults=4, children=2, board='RO')
    def test_percent_upper_bound_raises(self):
        with self.assertRaises(ValidationError):
            self.env['hotel.rate.line'].create({'company_id':self.co.id,'period_id':self.h1.id,'room_type_id':self.type.id,'meal_plan_id':self.meal_ro.id,'price':20000.0,'extra_child_mode':'percent','extra_child_value':1000.0})
        with self.assertRaises(ValidationError):
            self.env['hotel.rate.line'].create({'company_id':self.co.id,'period_id':self.h1.id,'room_type_id':self.type.id,'meal_plan_id':self.meal_ro.id,'price':20000.0,'extra_adult_mode':'percent','extra_adult_value':1000.0})
    def test_included_counts_constrained(self):
        with self.assertRaises(ValidationError):
            self.env['hotel.rate.line'].create({'company_id':self.co.id,'period_id':self.h1.id,'room_type_id':self.type.id,'meal_plan_id':self.meal_ro.id,'price':20000.0,'included_adults':-1})
        with self.assertRaises(ValidationError):
            self.env['hotel.rate.line'].create({'company_id':self.co.id,'period_id':self.h1.id,'room_type_id':self.type.id,'meal_plan_id':self.meal_ro.id,'price':20000.0,'included_adults':3,'included_children':3})
    def test_plan_ignored_except_company(self):
        eng = self.env['hotel.rate.engine']
        plan = self.env['hotel.rate.plan'].create({'name': 'RackT6', 'company_id': self.co.id})
        self.env['hotel.rate.line'].create({'company_id':self.co.id,'period_id':self.h1.id,'room_type_id':self.type.id,'meal_plan_id':self.meal_ro.id,'price':20000.0})
        via_none = eng.price_for(self.room.id, '2027-02-01', None, adults=2, board='RO')
        via_plan = eng.price_for(self.room.id, '2027-02-01', plan.id, adults=2, board='RO')
        self.assertEqual(via_none, 20000.0)
        self.assertEqual(via_plan, via_none)
