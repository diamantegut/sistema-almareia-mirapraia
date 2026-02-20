print("SCRIPT STARTING")
import sqlite3
import os
import sys

try:
    LOGS_DB = os.path.join(os.getcwd(), 'data', 'department_logs.db')
    print(f"DB Path: {LOGS_DB}")

    conn = sqlite3.connect(LOGS_DB)
    cursor = conn.cursor()
    cursor.execute("SELECT count(*) FROM logs_acoes_departamento")
    count = cursor.fetchone()[0]
    print(f"Total rows in DB: {count}")
    
    cursor.execute("SELECT * FROM logs_acoes_departamento WHERE detalhes LIKE '%100,54%'")
    rows = cursor.fetchall()
    print(f"Total Logs with 100,54: {len(rows)}")
    for row in rows:
        print(row)
        
except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()
finally:
    print("SCRIPT FINISHED")

