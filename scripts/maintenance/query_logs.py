import sqlite3
import os

with open('db_log_output.txt', 'w') as f:
    def log(msg):
        print(msg)
        f.write(str(msg) + '\n')
    
    db_path = os.path.join('data', 'department_logs.db')
    log(f"Checking DB at {db_path}")

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Check table existence
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='logs_acoes_departamento';")
        if not cursor.fetchone():
            log("Table 'logs_acoes_departamento' not found!")
        else:
            # Get recent errors
            cursor.execute("SELECT timestamp, acao, detalhes FROM logs_acoes_departamento WHERE nivel_severidade IN ('ERROR', 'CRITICAL') ORDER BY timestamp DESC LIMIT 5")
            rows = cursor.fetchall()

            log("\nRecent Errors/Criticals:")
            if not rows:
                log("No recent errors found.")
            for row in rows:
                log(f"Time: {row[0]}")
                log(f"Action: {row[1]}")
                log(f"Details: {row[2]}")
                log("-" * 40)
                
        conn.close()
    except Exception as e:
        log(f"Error querying DB: {e}")
