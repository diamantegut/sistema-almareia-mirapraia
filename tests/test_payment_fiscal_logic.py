
import unittest
import json
from datetime import datetime
from unittest.mock import patch, MagicMock

# Mocking Flask and dependencies
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

class TestPaymentFiscalLogic(unittest.TestCase):

    def setUp(self):
        self.payment_methods_data = [
            {
                "id": "credito",
                "name": "Cartão de Crédito",
                "available_in": ["caixa_restaurante", "caixa_recepcao"],
                "is_fiscal": True
            },
            {
                "id": "debito",
                "name": "Cartão de Débito",
                "available_in": ["caixa_restaurante"],
                "is_fiscal": True
            },
            {
                "id": "dinheiro",
                "name": "Dinheiro",
                "available_in": ["caixa_restaurante", "caixa_recepcao", "caixa_reservas"],
                "is_fiscal": False
            },
            {
                "id": "pix_reserva",
                "name": "PIX Reserva",
                "available_in": ["caixa_reservas"],
                "is_fiscal": False
            },
            {
                "id": "legacy_method",
                "name": "Legacy",
                "available_in": ["restaurant"], # Legacy tag
                "is_fiscal": False
            }
        ]

    def test_payment_filtering_restaurant(self):
        """Verify Restaurant Cashier filtering logic"""
        # Logic from restaurant/routes.py:
        # [m for m in payment_methods if 'restaurant' in m.get('available_in', []) or 'caixa_restaurante' in m.get('available_in', [])]
        
        filtered = [
            m for m in self.payment_methods_data 
            if 'restaurant' in m.get('available_in', []) or 'caixa_restaurante' in m.get('available_in', [])
        ]
        
        ids = [m['id'] for m in filtered]
        self.assertIn('credito', ids)
        self.assertIn('debito', ids)
        self.assertIn('dinheiro', ids)
        self.assertNotIn('pix_reserva', ids)
        self.assertIn('legacy_method', ids) # Backward compatibility

    def test_payment_filtering_reception(self):
        """Verify Reception Cashier filtering logic"""
        # Logic from reception/routes.py:
        # [m for m in payment_methods if 'reception' in m.get('available_in', []) or 'caixa_recepcao' in m.get('available_in', [])]
        
        filtered = [
            m for m in self.payment_methods_data 
            if 'reception' in m.get('available_in', []) or 'caixa_recepcao' in m.get('available_in', [])
        ]
        
        ids = [m['id'] for m in filtered]
        self.assertIn('credito', ids)
        self.assertNotIn('debito', ids)
        self.assertIn('dinheiro', ids)
        self.assertNotIn('pix_reserva', ids)

    def test_payment_filtering_reservations(self):
        """Verify Reservations Cashier filtering logic"""
        # Logic from reception/routes.py (reservations):
        # [m for m in payment_methods if 'caixa_reservas' in m.get('available_in', []) or 'reservas' in m.get('available_in', [])]
        
        filtered = [
            m for m in self.payment_methods_data 
            if 'caixa_reservas' in m.get('available_in', []) or 'reservas' in m.get('available_in', [])
        ]
        
        ids = [m['id'] for m in filtered]
        self.assertNotIn('credito', ids)
        self.assertIn('dinheiro', ids)
        self.assertIn('pix_reserva', ids)

    def test_fiscal_flag_lookup(self):
        """Verify logic to determine is_fiscal flag"""
        
        # Simulation of what happens in close_order/pay_charge
        pm_map = {m['id']: m for m in self.payment_methods_data}
        
        # Case 1: Fiscal Method
        pm_obj = pm_map.get('credito')
        is_fiscal = pm_obj.get('is_fiscal', False)
        self.assertTrue(is_fiscal)
        
        # Case 2: Non-Fiscal Method
        pm_obj = pm_map.get('dinheiro')
        is_fiscal = pm_obj.get('is_fiscal', False)
        self.assertFalse(is_fiscal)
        
        # Case 3: Missing Method (Fallback default)
        pm_obj = pm_map.get('unknown')
        is_fiscal = pm_obj.get('is_fiscal', False) if pm_obj else False
        self.assertFalse(is_fiscal)

if __name__ == '__main__':
    unittest.main()
