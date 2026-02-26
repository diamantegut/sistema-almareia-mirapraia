import sys
import os
from flask import Flask, render_template, session

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app

app = create_app()
app.secret_key = 'test_key'  # Needed for session

def verify_template(template_name, context={}):
    print(f"Testing {template_name}...", end=' ')
    with app.test_request_context():
        # Mock session if needed
        session['user'] = 'TestUser'
        session['role'] = 'admin'
        session['department'] = 'TI'
        
        try:
            render_template(template_name, **context)
            print("OK")
            return True
        except Exception as e:
            print(f"FAIL")
            print(f"  Error: {e}")
            return False

if __name__ == "__main__":
    print("=== TEMPLATE RENDERING VERIFICATION ===\n")
    
    # Define templates to test and their required context variables (if any)
    tests = [
        ('admin_dashboard.html', {}),
        ('reception_dashboard.html', {}),
        ('reception_surveys.html', {'stats_by_audience': {'hotel': {'sent':0, 'responded':0}, 'restaurant': {'sent':0, 'responded':0}, 'colaboradores': {'sent':0, 'responded':0}, 'candidatos': {'sent':0, 'responded':0}}, 'items': []}),
        ('stock_products.html', {'products': [], 'categories': [], 'suppliers': []}), # stock_products might need variables
        ('service.html', {'service': {'id': 'test', 'name': 'Test Service', 'icon': 'bi-gear', 'actions': []}, 'purchase_alerts': []})
    ]
    
    passed = 0
    failed = 0
    
    for tmpl, ctx in tests:
        if verify_template(tmpl, ctx):
            passed += 1
        else:
            failed += 1
            
    print(f"\nSummary: {passed} Passed, {failed} Failed")
