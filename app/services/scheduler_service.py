import os
import json
import time
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from import_sales import process_sales_files
from fiscal_service import sync_received_nfes, get_last_nsu
from app.services.system_config_manager import (
    get_data_path, SYSTEM_STATUS_FILE, SETTINGS_FILE, FISCAL_SETTINGS_FILE,
    CLEANING_STATUS_FILE, ROOM_OCCUPANCY_FILE
)
from app.services.stock_security_service import StockSecurityService
from app.services.menu_security_service import MenuSecurityService
STATUS_FILE = SYSTEM_STATUS_FILE
# SETTINGS_FILE already imported

def load_status():
    if os.path.exists(STATUS_FILE):
        try:
            with open(STATUS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_status(status):
    with open(STATUS_FILE, 'w', encoding='utf-8') as f:
        json.dump(status, f, indent=4, ensure_ascii=False)

def get_sync_status():
    status = load_status()
    return status.get("daily_sales_sync", {
        "last_success_date": None,
        "status": "unknown",
        "attempts": 0,
        "error_message": None
    })

def run_nfe_sync_job():
    now = datetime.now()
    if now.hour >= 16 or now.hour < 7:
        print(f"[{now}] Sincronização de NFe pulada (fora da janela 07:00-16:00).")
        return
    print(f"[{now}] Iniciando Sincronização de NFe Recebidas...")
    try:
        settings = {}
        fiscal_settings_file = get_data_path('fiscal_settings.json')
        if os.path.exists(fiscal_settings_file):
            with open(fiscal_settings_file, 'r', encoding='utf-8') as f:
                settings = json.load(f)
        
        if settings.get('provider') == 'nuvem_fiscal':
            result = sync_received_nfes(settings)
            status_data = load_status()
            fiscal_status = status_data.get("fiscal_sync", {})
            fiscal_status["last_attempt_time"] = now.strftime('%d/%m/%Y %H:%M:%S')
            if isinstance(result, dict) and result.get("error"):
                fiscal_status["status"] = "failed"
                fiscal_status["error_message"] = result.get("error")
                fiscal_status["synced_count"] = result.get("synced_count", 0)
            else:
                synced_count = 0
                if isinstance(result, dict):
                    synced_count = result.get("synced_count", 0)
                fiscal_status["status"] = "success"
                fiscal_status["error_message"] = None
                fiscal_status["synced_count"] = synced_count
                fiscal_status["last_success_time"] = now.strftime('%d/%m/%Y %H:%M:%S')
            fiscal_status["last_nsu"] = get_last_nsu()
            status_data["fiscal_sync"] = fiscal_status
            save_status(status_data)
            print(f"[{datetime.now()}] Sincronização de NFe finalizada.")
    except Exception as e:
        print(f"[{datetime.now()}] Erro na Sincronização de NFe: {e}")
        try:
            status_data = load_status()
            fiscal_status = status_data.get("fiscal_sync", {})
            fiscal_status["status"] = "failed"
            fiscal_status["error_message"] = str(e)
            fiscal_status["last_attempt_time"] = now.strftime('%d/%m/%Y %H:%M:%S')
            fiscal_status["last_nsu"] = get_last_nsu()
            status_data["fiscal_sync"] = fiscal_status
            save_status(status_data)
        except Exception:
            pass

def update_daily_cleaning_status():
    """
    Updates room cleaning status based on occupancy:
    - Stay-over: dirty (Daily Cleaning)
    - Checkout today: dirty_checkout
    """
    try:
        now = datetime.now()
        print(f"[{now}] Iniciando atualização diária de status de limpeza...")
        
        cleaning_file = get_data_path('cleaning_status.json')
        occupancy_file = get_data_path('room_occupancy.json')
        
        if not os.path.exists(occupancy_file):
            print(f"[{now}] Arquivo de ocupação não encontrado. Pulando.")
            return

        occupancy = {}
        with open(occupancy_file, 'r', encoding='utf-8') as f:
            occupancy = json.load(f)
            
        cleaning_status = {}
        if os.path.exists(cleaning_file):
            with open(cleaning_file, 'r', encoding='utf-8') as f:
                cleaning_status = json.load(f)
        
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        updates_count = 0
        
        for room_num, data in occupancy.items():
            try:
                # Normalize room key for cleaning_status (ensure 2 digits for <10)
                room_key = str(room_num)
                if room_key.isdigit() and len(room_key) == 1:
                    room_key = f"0{room_key}"

                checkin_str = data.get('checkin')
                checkout_str = data.get('checkout')
                if not checkin_str or not checkout_str:
                    continue
                    
                checkin = datetime.strptime(checkin_str, '%d/%m/%Y')
                checkout = datetime.strptime(checkout_str, '%d/%m/%Y')
                
                # Logic:
                new_status = None
                note = ""
                
                if checkout.date() == today.date():
                    new_status = 'dirty_checkout'
                    note = "Saída Hoje (Automático)"
                elif checkin.date() < today.date() < checkout.date():
                    new_status = 'dirty'
                    note = "Limpeza Diária (Automático)"
                
                if new_status:
                    current = cleaning_status.get(room_key, {})
                    current_status = current.get('status')
                    
                    # Avoid overwriting if already correct or in progress
                    # But we want to reset 'clean'/'inspected' to 'dirty' for a new day
                    if current_status in ['clean', 'inspected'] or (new_status == 'dirty_checkout' and current_status != 'dirty_checkout'):
                        if room_key not in cleaning_status:
                            cleaning_status[room_key] = {}
                        
                        cleaning_status[room_key]['status'] = new_status
                        cleaning_status[room_key]['last_update'] = now.strftime('%d/%m/%Y %H:%M:%S')
                        cleaning_status[room_key]['system_note'] = note
                        updates_count += 1
                        
            except Exception as e:
                print(f"Erro processando quarto {room_num}: {e}")
        
        if updates_count > 0:
            with open(cleaning_file, 'w', encoding='utf-8') as f:
                json.dump(cleaning_status, f, indent=4, ensure_ascii=False)
            print(f"[{datetime.now()}] Atualização concluída. {updates_count} quartos atualizados.")
        else:
            print(f"[{datetime.now()}] Nenhuma atualização necessária.")
            
    except Exception as e:
        print(f"[{datetime.now()}] Erro crítico na atualização de limpeza: {e}")

def start_scheduler():
    scheduler = BackgroundScheduler()
    
    # NFe Sync Job - Every 1 hour and 30 minutes (90 minutes)
    scheduler.add_job(run_nfe_sync_job, 'interval', minutes=90)
    
    # Daily Cleaning Status Update - Runs daily at 06:00 AM
    scheduler.add_job(update_daily_cleaning_status, 'cron', hour=6, minute=0)
    
    # Stock Anti-Overwrite Backup - Every 2 hours
    scheduler.add_job(StockSecurityService.create_stock_backup, 'interval', hours=2)

    # Menu/Sales Anti-Overwrite Backup - Every 2 hours
    scheduler.add_job(MenuSecurityService.create_menu_sales_backup, 'interval', hours=2)
    
    # Backup Jobs are now handled by services/backup_service.py independently
    # scheduler.add_job(create_backup, 'interval', hours=12)
    # scheduler.add_job(backup_table_orders_only, 'interval', minutes=10)
    # scheduler.add_job(backup_reception_data, 'interval', minutes=30)

    # Also run NFe sync and Cleaning Update immediately on startup (threaded to not block)
    import threading
    threading.Thread(target=run_nfe_sync_job).start()
    threading.Thread(target=update_daily_cleaning_status).start()
    
    scheduler.start()
    print("Agendador de tarefas iniciado (06:00 - 23:00).")
    return scheduler
