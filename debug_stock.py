import sys
import os
import traceback

sys.path.append(os.getcwd())
from app import create_app
from app.services.data_service import (
    load_sales_history, load_table_orders, load_stock_entries, load_printers
)

app = create_app()

with open('debug_log_direct.txt', 'w') as f:
    def log(msg):
        print(msg)
        f.write(str(msg) + '\n')
        f.flush()

    with app.app_context():
        log("Testing data loaders...")
        
        try:
            log("Loading table orders...")
            orders = load_table_orders()
            log(f"OK. Loaded {len(orders)} orders.")
        except Exception:
            log("FAIL: load_table_orders")
            f.write(traceback.format_exc() + '\n')

        try:
            log("Loading sales history...")
            history = load_sales_history()
            log(f"OK. Loaded {len(history) if isinstance(history, list) else 'Unknown'} sales.")
        except Exception:
            log("FAIL: load_sales_history")
            f.write(traceback.format_exc() + '\n')

        try:
            log("Loading stock entries...")
            entries = load_stock_entries()
            log(f"OK. Loaded {len(entries)} entries.")
        except Exception:
            log("FAIL: load_stock_entries")
            f.write(traceback.format_exc() + '\n')

        try:
            log("Loading printers...")
            printers = load_printers()
            log(f"OK. Loaded {len(printers)} printers.")
        except Exception:
            log("FAIL: load_printers")
            f.write(traceback.format_exc() + '\n')
