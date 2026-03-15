import json
import os
from datetime import datetime, timedelta
import uuid

from app.services.system_config_manager import BASE_DIR, get_data_path

# File Paths
DATA_DIR = get_data_path('')
ALERTS_FILE = get_data_path('system_alerts.json')

def load_system_alerts():
    if not os.path.exists(ALERTS_FILE):
        return []
    try:
        with open(ALERTS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return []

def save_system_alerts(alerts):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(ALERTS_FILE, 'w', encoding='utf-8') as f:
            json.dump(alerts, f, indent=4, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"Error saving system alerts: {e}")
        return False

def log_system_alert(alert_type, severity, message, details=None):
    """
    Logs a system alert.
    Severity: 'Critical', 'High', 'Medium', 'Low', 'Info'
    """
    alerts = load_system_alerts()
    
    alert = {
        'id': str(uuid.uuid4()),
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'type': alert_type,
        'severity': severity,
        'message': message,
        'details': details,
        'status': 'New' # New, Acknowledged, Resolved
    }
    
    # Insert at beginning
    alerts.insert(0, alert)
    
    # Prune old alerts (keep last 45 days)
    try:
        cutoff_date = datetime.now() - timedelta(days=45)
        alerts = [
            a for a in alerts 
            if datetime.strptime(a['timestamp'], '%Y-%m-%d %H:%M:%S') > cutoff_date
        ]
    except Exception as e:
        print(f"Error pruning system alerts: {e}")
        # Fallback
        if len(alerts) > 1000:
            alerts = alerts[:1000]
        
    save_system_alerts(alerts)
    return alert

def get_latest_alerts(limit=10):
    alerts = load_system_alerts()
    return alerts[:limit]

def check_backup_health(backup_dir, max_age_minutes=35):
    """
    Checks if the latest backup in the directory is recent enough.
    Returns (status_bool, message)
    """
    if not os.path.exists(backup_dir):
        return False, "Backup directory does not exist."
    
    try:
        # Get all zip files
        files = [os.path.join(backup_dir, f) for f in os.listdir(backup_dir) if f.endswith('.zip')]
        if not files:
            return False, "No backup files found."
            
        # Get latest file
        latest_file = max(files, key=os.path.getmtime)
        latest_time = datetime.fromtimestamp(os.path.getmtime(latest_file))
        
        age = datetime.now() - latest_time
        if age.total_seconds() > (max_age_minutes * 60):
            return False, f"Latest backup is too old ({int(age.total_seconds() / 60)} min ago). Last: {os.path.basename(latest_file)}"
            
        return True, f"Backup healthy. Last: {os.path.basename(latest_file)} ({int(age.total_seconds() / 60)} min ago)"
        
    except Exception as e:
        return False, f"Error checking backup health: {e}"
