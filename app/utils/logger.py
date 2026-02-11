import os
import json
from datetime import datetime
from flask import session
from app.services.system_config_manager import ACTION_LOGS_DIR

def log_action(action_type, details, user=None, department=None):
    if user is None:
        user = session.get('user', 'Sistema')
    
    if department is None:
        department = session.get('department', 'Geral')
    
    # Write to today's file and enforce 90-day retention
    os.makedirs(ACTION_LOGS_DIR, exist_ok=True)
    today_str = datetime.now().strftime('%Y-%m-%d')
    today_file = os.path.join(ACTION_LOGS_DIR, f"{today_str}.json")
    
    # Load today's logs
    day_logs = []
    if os.path.exists(today_file):
        try:
            with open(today_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, list):
                    day_logs = data
        except json.JSONDecodeError:
            day_logs = []
    
    new_log = {
        'id': f"LOG_{datetime.now().strftime('%Y%m%d%H%M%S')}_{len(day_logs)}",
        'timestamp': datetime.now().strftime('%d/%m/%Y %H:%M:%S'),
        'user': user,
        'department': department,
        'action': action_type,
        'details': details
    }
    
    day_logs.append(new_log)
    
    try:
        with open(today_file, 'w', encoding='utf-8') as f:
            json.dump(day_logs, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"Error saving log: {e}")
