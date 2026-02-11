
import os
import json
from datetime import datetime
from system_config_manager import get_log_path

def log_action(action_type, details, user=None, department=None):
    """
    Logs an action to a daily JSON file in the logs/actions directory.
    Replicates logic from app.py to decouple services.
    """
    if user is None:
        user = 'Sistema' # Default if not provided
    
    if department is None:
        department = 'Geral' # Default
    
    # Write to today's file and enforce 90-day retention
    today_str = datetime.now().strftime('%Y-%m-%d')
    # get_log_path returns logs/filename. We want logs/actions/filename
    log_file_path = get_log_path(os.path.join('actions', f"{today_str}.json"))
    
    # Ensure actions subdir exists (get_log_path ensures logs dir, but not subdirs)
    os.makedirs(os.path.dirname(log_file_path), exist_ok=True)
    
    # Load today's logs
    day_logs = []
    if os.path.exists(log_file_path):
        try:
            with open(log_file_path, 'r', encoding='utf-8') as f:
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
        with open(log_file_path, 'w', encoding='utf-8') as f:
            json.dump(day_logs, f, indent=4, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"Error logging action: {e}")
        return False
