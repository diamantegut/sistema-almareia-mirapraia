import json
from collections import Counter
import unittest

# Mock Data
products = [
    {"name": "OriginNoRule", "category": "None", "unit": "kg", "status": "Ativo"},
    {"name": "OriginOneRule", "category": "Meat", "unit": "kg", "status": "Ativo"},
    {"name": "OriginMultiRule", "category": "Fish", "unit": "kg", "status": "Ativo"},
    {"name": "Dest1", "category": "MeatPortion", "unit": "un", "status": "Ativo"},
    {"name": "Dest2", "category": "FishPortion1", "unit": "un", "status": "Ativo"},
    {"name": "Dest3", "category": "FishPortion2", "unit": "un", "status": "Inativo"}, # Inactive!
    {"name": "DestCompatible", "category": "MeatPortion", "unit": "kg", "status": "Ativo"}, # Same unit
    {"name": "DestIncompatible", "category": "MeatPortion", "unit": "L", "status": "Ativo"}, # Diff unit
]

settings = {
    "portioning_rules": [
        {"origin": "Meat", "destinations": ["MeatPortion"]},
        {"origin": "Fish", "destinations": ["FishPortion1", "FishPortion2"]}
    ],
    "product_portioning_rules": []
}

stock_entries = [
    {"supplier": "PORCIONAMENTO (ENTRADA)", "product": "Dest2"},
    {"supplier": "PORCIONAMENTO (ENTRADA)", "product": "Dest2"},
    {"supplier": "PORCIONAMENTO (ENTRADA)", "product": "Dest3"},
]

# Logic to Test
def get_rules_maps(settings):
    rules = settings.get('portioning_rules', [])
    product_rules = settings.get('product_portioning_rules', [])
    
    rules_map = {}
    for r in rules:
        origin = r.get('origin')
        dests = r.get('destinations', [])
        if origin:
            if origin not in rules_map:
                rules_map[origin] = []
            rules_map[origin] = list(set(rules_map[origin] + dests))
            
    product_rules_map = {}
    for r in product_rules:
        origin = r.get('origin')
        dests = r.get('destinations', [])
        if origin:
            product_rules_map[origin] = dests
            
    return rules_map, product_rules_map

def get_usage_ranking(entries):
    port_entries = [e for e in entries if e.get('supplier') == "PORCIONAMENTO (ENTRADA)"]
    counts = Counter([e.get('product') for e in port_entries if e.get('product')])
    return dict(counts)

def get_allowed_destinations(origin_product, rules_map, product_rules_map, check_status=True, check_unit=False):
    origin_name = origin_product['name']
    origin_cat = origin_product['category']
    origin_unit = origin_product['unit']
    
    allowed_prods = product_rules_map.get(origin_name)
    allowed_cats = rules_map.get(origin_cat)
    
    use_prod_filter = allowed_prods is not None and len(allowed_prods) > 0
    use_cat_filter = not use_prod_filter and allowed_cats is not None and len(allowed_cats) > 0
    
    valid_dests = []
    
    for p in products:
        # 1. Status Check
        if check_status and p.get('status', 'Ativo') != 'Ativo':
            continue
            
        # 2. Unit Check (Optional)
        if check_unit:
            # Simple check: same unit string
            # In reality, might need conversion table (kg <-> g, L <-> ml)
            if p.get('unit') != origin_unit:
                # Allow Un for portioning usually? 
                # Request said: "unidade de medida compatível"
                # Let's assume strict equality for test
                continue

        is_valid = False
        if use_prod_filter:
            if p['name'] in allowed_prods:
                is_valid = True
        elif use_cat_filter:
            if p['category'] in allowed_cats:
                is_valid = True
        
        if is_valid:
            valid_dests.append(p)
            
    return valid_dests

def search_products(query, products):
    query = query.lower()
    results = []
    for p in products:
        if query in p['name'].lower():
            results.append(p)
    return results[:10]

class TestPortionLogic(unittest.TestCase):
    
    def setUp(self):
        self.rules_map, self.product_rules_map = get_rules_maps(settings)
        self.usage_ranking = get_usage_ranking(stock_entries)

    def test_usage_ranking(self):
        self.assertEqual(self.usage_ranking.get("Dest2"), 2)
        self.assertEqual(self.usage_ranking.get("Dest3"), 1)

    def test_no_rules(self):
        p = next(p for p in products if p['name'] == "OriginNoRule")
        dests = get_allowed_destinations(p, self.rules_map, self.product_rules_map)
        self.assertEqual(len(dests), 0)

    def test_status_filtering(self):
        # Dest3 is Inactive, but category matches Fish
        p = next(p for p in products if p['name'] == "OriginMultiRule") # Fish
        dests = get_allowed_destinations(p, self.rules_map, self.product_rules_map, check_status=True)
        dest_names = [d['name'] for d in dests]
        
        self.assertIn("Dest2", dest_names)
        self.assertNotIn("Dest3", dest_names) # Should be filtered out

    def test_unit_compatibility(self):
        # DestCompatible (kg) vs DestIncompatible (L) vs Dest1 (un)
        # OriginOneRule (Meat, kg) -> MeatPortion
        p = next(p for p in products if p['name'] == "OriginOneRule")
        
        # Test with unit check
        dests = get_allowed_destinations(p, self.rules_map, self.product_rules_map, check_unit=True)
        dest_names = [d['name'] for d in dests]
        
        self.assertIn("DestCompatible", dest_names) # kg == kg
        self.assertNotIn("DestIncompatible", dest_names) # L != kg
        self.assertNotIn("Dest1", dest_names) # un != kg (Strict check)

    def test_partial_search(self):
        results = search_products("dest", products)
        self.assertTrue(len(results) > 0)
        self.assertTrue(all("dest" in r['name'].lower() for r in results))
        
        results_partial = search_products("ompat", products)
        self.assertTrue(any(r['name'] == "DestCompatible" for r in results_partial))

if __name__ == '__main__':
    unittest.main()
