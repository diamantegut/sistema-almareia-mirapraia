import os
import json
import hashlib
import unicodedata
import base64
import uuid
from datetime import datetime
from werkzeug.utils import secure_filename
from app.services.system_config_manager import TIME_TRACKING_FILE, TIME_TRACKING_DIR
from app.services.user_service import load_users, save_users

def _safe_time_tracking_filename(username):
    username_str = str(username or '')
    safe_part = secure_filename(username_str)
    digest = hashlib.sha256(username_str.encode('utf-8')).hexdigest()[:10]
    if safe_part:
        return f"{safe_part}-{digest}.json"
    return f"user-{digest}.json"

def _time_tracking_path_for_user(username):
    return os.path.join(TIME_TRACKING_DIR, _safe_time_tracking_filename(username))

def load_time_tracking_legacy():
    if not os.path.exists(TIME_TRACKING_FILE):
        return {}
    try:
        with open(TIME_TRACKING_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError:
        return {}

def save_time_tracking_legacy(data):
    with open(TIME_TRACKING_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def save_time_tracking_for_user(username, data):
    path = _time_tracking_path_for_user(username)
    os.makedirs(TIME_TRACKING_DIR, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def load_time_tracking_for_user(username):
    path = _time_tracking_path_for_user(username)
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, dict) and isinstance(data.get('days'), dict):
                return data
        except json.JSONDecodeError:
            pass
    legacy = load_time_tracking_legacy()
    if isinstance(legacy, dict) and username in legacy and isinstance(legacy[username], dict):
        migrated = {'username': username, 'days': legacy[username]}
        save_time_tracking_for_user(username, migrated)
        return migrated
    return {'username': username, 'days': {}}

def _parse_weekly_day_off(value):
    if value is None:
        return 6
    if isinstance(value, int):
        return value if 0 <= value <= 6 else 6
    s = str(value).strip().lower()
    if s.isdigit():
        n = int(s)
        return n if 0 <= n <= 6 else 6
    s = unicodedata.normalize('NFKD', s).encode('ASCII', 'ignore').decode('utf-8')
    s = s.replace('-feira', '').replace('feira', '').strip()
    mapping = {
        'segunda': 0,
        'terca': 1,
        'quarta': 2,
        'quinta': 3,
        'sexta': 4,
        'sabado': 5,
        'domingo': 6
    }
    return mapping.get(s, 6)

def _get_user_target_seconds(username, date_obj):
    users = load_users()
    user = users.get(username, {}) if isinstance(users, dict) else {}
    
    # Logic: 44 hours per week (excluding day off)
    # Assuming 1 day off per week (6 working days)
    # 44h / 6 days = 7.3333h = 7h 20m = 26400 seconds
    
    weekday = date_obj.weekday()
    day_off = _parse_weekly_day_off(user.get('weekly_day_off', 6))
    is_day_off = weekday == day_off
    
    if is_day_off:
        target_seconds = 0
    else:
        target_seconds = 26400 # 7h 20m
        
    return target_seconds, day_off, is_day_off

def _format_seconds_hms(total_seconds):
    try:
        total = int(total_seconds)
    except (TypeError, ValueError):
        total = 0
    
    sign = ""
    if total < 0:
        sign = "-"
        total = abs(total)
        
    hours = total // 3600
    minutes = (total % 3600) // 60
    seconds = total % 60
    return f"{sign}{hours:02}:{minutes:02}:{seconds:02}"

def ensure_qr_token(username):
    """Ensures the user has a QR token. Generates one if missing."""
    users = load_users()
    if username in users:
        # Check if users[username] is a dict (new format)
        if isinstance(users[username], dict):
            if 'qr_token' not in users[username]:
                users[username]['qr_token'] = str(uuid.uuid4())
                save_users(users)
            return users[username]['qr_token']
        else:
            # Legacy format (str password)
            # Must migrate to dict
            # For now return None or migrate?
            # Let's assume user service handles migration or we skip legacy users for kiosk
            pass
    return None

def get_user_by_qr_token(token):
    """Finds a user by their QR token."""
    users = load_users()
    for username, data in users.items():
        if isinstance(data, dict) and data.get('qr_token') == token:
            return username, data
    return None, None

def perform_time_tracking_action(username, action, photo_data=None, lat=None, lon=None):
    """Shared logic for time tracking actions (Web + Kiosk)"""
    today = datetime.now().strftime('%Y-%m-%d')
    now_iso = datetime.now().isoformat()
    
    user_data = load_time_tracking_for_user(username)
    if not isinstance(user_data, dict):
        user_data = {'username': username, 'days': {}}
    if not isinstance(user_data.get('days'), dict):
        user_data['days'] = {}
    if today not in user_data['days']:
        target_seconds, day_off, is_day_off = _get_user_target_seconds(username, datetime.now())
        user_data['days'][today] = {
            'events': [],
            'status': 'Não iniciado',
            'accumulated_seconds': 0,
            'last_start_time': None,
            'target_seconds': target_seconds,
            'day_off_weekday': day_off,
            'is_day_off': is_day_off
        }
        
    day_record = user_data['days'][today]
    
    if action == 'start':
        if day_record['status'] == 'Não iniciado':
            # Handle Verification Data (Photo + Location)
            if photo_data:
                try:
                    # Save Photo
                    if "," in photo_data:
                        header, encoded = photo_data.split(",", 1)
                    else:
                        encoded = photo_data
                        
                    data = base64.b64decode(encoded)
                    
                    filename = f"{username}_{today}_start.jpg"
                    # Use app/static path relative to current working directory
                    upload_dir = os.path.join('app', 'static', 'uploads', 'time_tracking')
                    if not os.path.exists(upload_dir):
                        os.makedirs(upload_dir)
                        
                    filepath = os.path.join(upload_dir, filename)
                    with open(filepath, "wb") as f:
                        f.write(data)
                        
                    day_record['start_photo'] = filename
                    day_record['start_location'] = {'lat': lat, 'lon': lon}
                except Exception as e:
                    print(f"Error saving start verification: {e}")

            day_record['status'] = 'Trabalhando'
            day_record['last_start_time'] = now_iso
            day_record['events'].append({'type': 'start', 'time': now_iso})
            if day_record.get('target_seconds') is None or day_record.get('day_off_weekday') is None:
                target_seconds, day_off, is_day_off = _get_user_target_seconds(username, datetime.now())
                day_record['target_seconds'] = target_seconds
                day_record['day_off_weekday'] = day_off
                day_record['is_day_off'] = is_day_off
            
    elif action == 'pause':
        if day_record['status'] == 'Trabalhando':
            if day_record['last_start_time']:
                start_time = datetime.fromisoformat(day_record['last_start_time'])
                current_time = datetime.now()
                delta = (current_time - start_time).total_seconds()
                day_record['accumulated_seconds'] += delta
                
            day_record['status'] = 'Pausa'
            day_record['last_start_time'] = None
            day_record['events'].append({'type': 'pause', 'time': now_iso})
            
    elif action == 'resume':
        if day_record['status'] == 'Pausa':
            day_record['status'] = 'Trabalhando'
            day_record['last_start_time'] = now_iso
            day_record['events'].append({'type': 'resume', 'time': now_iso})
            
    elif action == 'end':
        if day_record['status'] == 'Trabalhando':
            # Handle Verification Data (Photo + Location)
            if photo_data:
                try:
                    # Save Photo
                    if "," in photo_data:
                        header, encoded = photo_data.split(",", 1)
                    else:
                        encoded = photo_data
                        
                    data = base64.b64decode(encoded)
                    
                    filename = f"{username}_{today}_end.jpg"
                    upload_dir = os.path.join('app', 'static', 'uploads', 'time_tracking')
                    if not os.path.exists(upload_dir):
                        os.makedirs(upload_dir)
                        
                    filepath = os.path.join(upload_dir, filename)
                    with open(filepath, "wb") as f:
                        f.write(data)
                        
                    day_record['end_photo'] = filename
                    day_record['end_location'] = {'lat': lat, 'lon': lon}
                except Exception as e:
                    print(f"Error saving end verification: {e}")

            if day_record['last_start_time']:
                start_time = datetime.fromisoformat(day_record['last_start_time'])
                current_time = datetime.now()
                delta = (current_time - start_time).total_seconds()
                day_record['accumulated_seconds'] += delta
            
        day_record['status'] = 'Finalizado'
        day_record['last_start_time'] = None
        day_record['events'].append({'type': 'end', 'time': now_iso})
        
    save_time_tracking_for_user(username, user_data)
    return day_record
