import unittest
from unittest.mock import MagicMock
import sys
import os

# Add project root to path
sys.path.append(os.getcwd())

from printing_service import format_ticket

class TestFixValidation(unittest.TestCase):
    def test_format_ticket_complements_dict(self):
        """
        Validates that format_ticket correctly handles complements as dictionaries.
        """
        table_id = "10"
        waiter_name = "Test Waiter"
        
        # Scenario: Item with dict complements
        items = [
            {
                'name': 'Gin Tonica',
                'qty': 1,
                'complements': [
                    {'name': 'Gelo', 'price': 0},
                    {'name': 'Limao', 'price': 0}
                ],
                'observations': ['Sem canudo']
            }
        ]
        
        # Execute
        cmd_bytes = format_ticket(table_id, waiter_name, items, "Test Printer")
        cmd_str = cmd_bytes.decode('cp850')
        
        # Verify
        self.assertIn("Gelo", cmd_str)
        self.assertIn("Limao", cmd_str)
        self.assertNotIn("{'name': 'Gelo'", cmd_str)

    def test_format_ticket_complements_string(self):
        """
        Validates that format_ticket correctly handles complements as strings.
        This matches the actual behavior of app.py (restaurant_table_order).
        """
        table_id = "10"
        waiter_name = "Test Waiter"
        
        # Scenario: Item with string complements
        items = [
            {
                'name': 'Gin Tonica',
                'qty': 1,
                'complements': ['Gelo', 'Limao'],
                'observations': ['Sem canudo']
            }
        ]
        
        # Execute
        cmd_bytes = format_ticket(table_id, waiter_name, items, "Test Printer")
        cmd_str = cmd_bytes.decode('cp850')
        
        # Verify
        print("\n=== Output Ticket (String Complements) ===")
        print(cmd_str)
        print("==========================================")
        
        self.assertIn("Gelo", cmd_str)
        self.assertIn("Limao", cmd_str)
        self.assertNotIn("['Gelo'", cmd_str) # Should not print list repr

    def test_grouped_order_items_logic(self):
        """
        Validates the logic used in app.py to group items.
        Simulates the code added to restaurant_table_order route.
        """
        # Mock Orders Structure
        orders = {
            "10": {
                "items": [
                    {
                        "id": "1",
                        "name": "Cerveja",
                        "qty": 1,
                        "price": 10.0,
                        "complements": [],
                        "print_status": "printed",
                        "printed": True
                    },
                    {
                        "id": "2",
                        "name": "Cerveja",
                        "qty": 2,
                        "price": 10.0,
                        "complements": [],
                        "print_status": "printed",
                        "printed": True
                    },
                    {
                        "id": "3",
                        "name": "Gin",
                        "qty": 1,
                        "price": 25.0,
                        "complements": [{'name': 'Gelo', 'price': 0}],
                        "print_status": "pending",
                        "printed": False
                    },
                    {
                        "id": "4",
                        "name": "Caipirinha",
                        "qty": 1,
                        "price": 20.0,
                        "complements": ["Sem Acucar"],
                        "print_status": "pending",
                        "printed": False
                    }
                ]
            }
        }
        
        str_table_id = "10"
        
        # --- Logic Copied from app.py ---
        grouped_order_items = []
        if str_table_id in orders:
            items = orders[str_table_id].get('items', [])
            groups = {}
            
            for item in items:
                # Create a unique key for grouping
                comps_list = item.get('complements', [])
                if comps_list and isinstance(comps_list[0], dict):
                    comps_key = tuple(sorted([(c.get('name', ''), float(c.get('price', 0))) for c in comps_list]))
                else:
                    comps_key = tuple()

                obs_list = item.get('observations', [])
                obs_key = tuple(sorted(obs_list)) if obs_list else tuple()
                
                key = (
                    item.get('name'),
                    item.get('flavor'),
                    comps_key,
                    obs_key,
                    float(item.get('price', 0)),
                    item.get('print_status', 'pending' if not item.get('printed') else 'printed'),
                    item.get('printed', False)
                )
                
                if key not in groups:
                    groups[key] = {
                        'name': item.get('name'),
                        'flavor': item.get('flavor'),
                        'complements': item.get('complements', []),
                        'observations': item.get('observations', []),
                        'price': float(item.get('price', 0)),
                        'qty': 0.0,
                        'total': 0.0,
                        'ids': [],
                        'print_status': item.get('print_status', 'pending' if not item.get('printed') else 'printed'),
                        'printed': item.get('printed', False),
                        'last_item_qty': 0.0
                    }
                
                qty = float(item.get('qty', 0))
                groups[key]['qty'] += qty
                
                # THIS IS THE POTENTIAL BUG: c.get on string
                comp_total = 0.0
                for c in item.get('complements', []):
                    if isinstance(c, dict):
                        comp_total += float(c.get('price', 0))
                
                item_total = qty * (float(item.get('price', 0)) + comp_total)
                groups[key]['total'] += item_total
                
                groups[key]['ids'].append(item.get('id'))
                groups[key]['last_item_qty'] = qty
                
            grouped_order_items = list(groups.values())
        # --------------------------------
        
        # Verify Grouping
        print(f"\nGrouped Items: {len(grouped_order_items)}")
        for g in grouped_order_items:
            print(f"- {g['qty']}x {g['name']} (Total: {g['total']})")
            
        self.assertEqual(len(grouped_order_items), 3, "Should have Cerveja, Gin, Caipirinha")

if __name__ == '__main__':
    unittest.main()
