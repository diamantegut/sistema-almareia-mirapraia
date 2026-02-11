import os
import shutil
import time
import threading
import glob
from datetime import datetime, timedelta
import logging

from app.services.transfer_service import file_lock
from app.services.system_config_manager import (
    get_data_path, get_backup_path, BASE_DIR, 
    BACKUP_CONFIG_FILE, CASHIER_SESSIONS_FILE
)

# Configure logging
logger = logging.getLogger(__name__)

import json

# Base paths
DATA_DIR = get_data_path('')
BACKUPS_DIR = get_backup_path('')
# BACKUP_CONFIG_FILE imported from system_config_manager

SCHEDULED_BACKUP_TYPES = {'full_system'}

# Configuration for each backup type
DEFAULT_BACKUP_CONFIGS = {
    'products': {
        'source_files': ['menu_items.json', 'products.json', 'product_changes.json'],
        'dest_dir': os.path.join(BACKUPS_DIR, 'Produtos'),
        'interval_seconds': 3600,  # 1 hour
        'retention_hours': 24,
        'description': 'Backup de Produtos (Menu/Estoque)'
    },
    'cashiers_open': {
        'dest_dir': os.path.join(BACKUPS_DIR, 'Caixas Abertos'),
        'interval_seconds': 1200,
        'retention_hours': 30,
        'description': 'Backup de Caixas Abertos'
    },
    'insumos': {
        'source_files': [
            'products.json',
            'suppliers.json',
            'stock_entries.json',
            'stock_transfers.json',
            'stock_logs.json',
            'stock_requests.json'
        ],
        'dest_dir': os.path.join(BACKUPS_DIR, 'Insumos'),
        'interval_seconds': 10800,
        'retention_count': 9,
        'description': 'Backup de Insumos (Cadastro e Estoques)'
    },
    'tables': {
        'source_files': ['table_orders.json'],
        'dest_dir': os.path.join(BACKUPS_DIR, 'Mesas Restaurante'),
        'interval_seconds': 60,  # 1 minute
        'retention_minutes': 120,
        'description': 'Backup de Mesas do Restaurante'
    },
    'reception': {
        'source_files': ['room_occupancy.json', 'room_charges.json', 'cleaning_status.json', 'guest_notifications.json'],
        'dest_dir': os.path.join(BACKUPS_DIR, 'Recepcao'),
        'interval_seconds': 1200,  # 20 minutes
        'retention_hours': 72,
        'description': 'Backup da Recepção e Hóspedes'
    },
    'logs': {
        'source_dir': os.path.join(BASE_DIR, 'logs'),
        'dest_dir': os.path.join(BACKUPS_DIR, 'Logs'),
        'interval_seconds': 86400,  # 24 hours
        'retention_hours': 240,     # 240 hours
        'description': 'Backup de Logs do Sistema'
    },
    'full_system': {
        'source_dir': DATA_DIR,
        'dest_dir': os.path.join(BACKUPS_DIR, 'Sistema_Completo'),
        'interval_seconds': 3600,
        'retention_hours': 0,
        'retention_minutes': 0,
        'retention_count': 0,
        'rotation_slots': 24,
        'base_name': 'Servidor Teste',
        'description': 'Backup Completo do Sistema'
    }
}

# Active Config (starts with defaults, updated from file)
BACKUP_CONFIGS = {} # Disabled auto-backups for migration

# Status tracking
BACKUP_STATUS = {}

def _init_backup_status():
    global BACKUP_STATUS
    BACKUP_STATUS = {
        backup_type: {
            'last_run': None,
            'status': 'pending' if backup_type in SCHEDULED_BACKUP_TYPES else 'disabled',
            'message': ''
        }
        for backup_type in BACKUP_CONFIGS.keys()
    }

_init_backup_status()

def load_backup_config():
    global BACKUP_CONFIGS
    if not os.path.exists(BACKUP_CONFIG_FILE):
        return

    try:
        with open(BACKUP_CONFIG_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f) or {}
    except Exception as e:
        logger.warning(f"Failed to load backup config: {e}")
        return

    if not isinstance(data, dict):
        return

    allowed_fields = {'interval_seconds', 'retention_hours', 'retention_minutes', 'retention_count'}

    for backup_type, overrides in data.items():
        if backup_type not in BACKUP_CONFIGS:
            continue
        if not isinstance(overrides, dict):
            continue

        config = BACKUP_CONFIGS[backup_type]
        for field in allowed_fields:
            if field in overrides:
                config[field] = overrides[field]


def save_backup_config():
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
    except Exception:
        pass

    data = {}
    for backup_type, config in BACKUP_CONFIGS.items():
        data[backup_type] = {
            'interval_seconds': config.get('interval_seconds'),
            'retention_hours': config.get('retention_hours', 0),
            'retention_minutes': config.get('retention_minutes', 0),
            'retention_count': config.get('retention_count', 0)
        }

    try:
        with open(BACKUP_CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"Failed to save backup config: {e}")


class BackupService:
    def __init__(self):
        self.running = False
        self.threads = []
        self._ensure_directories()

    def _ensure_directories(self):
        """Create necessary backup directories if they don't exist."""
        for config in BACKUP_CONFIGS.values():
            try:
                os.makedirs(config['dest_dir'], exist_ok=True)
            except Exception as e:
                logger.error(f"Failed to create backup directory {config['dest_dir']}: {e}")

    def start(self):
        if self.running:
            return
        self.running = True
        logger.info("Starting Backup Service...")
        print("Backup Service Started.")
        
        for job_name, config in BACKUP_CONFIGS.items():
            if job_name not in SCHEDULED_BACKUP_TYPES:
                continue
            t = threading.Thread(target=self._run_job, args=(job_name, config), daemon=True)
            t.start()
            self.threads.append(t)

    def stop(self):
        self.running = False
        logger.info("Stopping Backup Service...")
        print("Backup Service Stopped.")

    def trigger_backup(self, backup_type):
        """Manually trigger a backup job."""
        if backup_type not in BACKUP_CONFIGS:
            return False, "Invalid backup type"
            
        try:
            logger.info(f"Manual trigger for backup '{backup_type}'")
            self._perform_backup(backup_type, BACKUP_CONFIGS[backup_type])
            # Run cleanup too
            self._cleanup_old_backups(backup_type, BACKUP_CONFIGS[backup_type])
            return True, f"Backup '{backup_type}' triggered successfully."
        except Exception as e:
            logger.error(f"Manual backup '{backup_type}' failed: {e}")
            return False, str(e)

    def _run_job(self, job_name, config):
        logger.info(f"Backup Job '{job_name}' started. Interval: {config['interval_seconds']}s")
        
        # Initial wait to stagger backups slightly on startup (optional, but good for load)
        time.sleep(5) 
        
        while self.running:
            try:
                self._perform_backup(job_name, config)
                self._cleanup_old_backups(job_name, config)
            except Exception as e:
                msg = f"Error in backup job '{job_name}': {e}"
                logger.error(msg)
                print(msg)
                BACKUP_STATUS[job_name] = {
                    'last_run': datetime.now().isoformat(),
                    'status': 'error',
                    'message': str(e)
                }
            
            # Wait for interval, checking running status every second
            for _ in range(config['interval_seconds']):
                if not self.running:
                    return
                time.sleep(1)

    def _perform_backup(self, job_name, config):
        # Import LoggerService here to avoid circular imports
        try:
            from logger_service import LoggerService
        except ImportError:
            LoggerService = None

        dest_dir = config['dest_dir']
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        
        try:
            os.makedirs(dest_dir, exist_ok=True)

            if job_name == 'cashiers_open':
                src_path = CASHIER_SESSIONS_FILE
                open_sessions = []
                if os.path.exists(src_path):
                    try:
                        with open(src_path, 'r', encoding='utf-8') as f:
                            sessions = json.load(f) or []
                        if isinstance(sessions, list):
                            open_sessions = [s for s in sessions if isinstance(s, dict) and s.get('status') == 'open']
                    except Exception:
                        open_sessions = []

                dest_fname = f"cashiers_open_{timestamp}.json"
                dest_path = os.path.join(dest_dir, dest_fname)
                with open(dest_path, 'w', encoding='utf-8') as f:
                    json.dump(
                        {
                            'timestamp': datetime.now().isoformat(),
                            'open_sessions': open_sessions
                        },
                        f,
                        indent=2,
                        ensure_ascii=False
                    )

                msg = f"Backup '{job_name}' completed. {len(open_sessions)} open sessions saved to {dest_dir}"
                logger.info(msg)
                BACKUP_STATUS[job_name] = {
                    'last_run': datetime.now().isoformat(),
                    'status': 'success',
                    'message': msg
                }
                return

            if 'source_dir' in config:
                # Directory Backup (Zip)
                source_dir = config['source_dir']
                
                if job_name == 'full_system':
                    drive, _ = os.path.splitdrive(dest_dir)
                    if drive and not os.path.exists(drive + os.sep):
                        msg = f"Backup drive for '{job_name}' not found: {dest_dir}"
                        logger.warning(msg)
                        BACKUP_STATUS[job_name] = {
                            'last_run': datetime.now().isoformat(),
                            'status': 'error',
                            'message': msg
                        }
                        if LoggerService:
                            LoggerService.log_acao(
                                acao=f"Falha no Backup Automático ({job_name})",
                                entidade="Backup",
                                detalhes={'msg': msg},
                                nivel_severidade='ALERTA',
                                departamento_id='TI'
                            )
                        return
                
                if not os.path.exists(source_dir):
                     # If source doesn't exist (e.g. no logs yet), just warn
                     msg = f"Source directory not found: {source_dir}"
                     logger.warning(msg)
                     BACKUP_STATUS[job_name] = {
                        'last_run': datetime.now().isoformat(),
                        'status': 'warning',
                        'message': msg
                     }
                     return

                # Zip the entire directory
                if job_name == 'full_system':
                    base_name = str(config.get('base_name') or 'Servidor Teste')
                    rotation_slots = int(config.get('rotation_slots') or 0)
                    if rotation_slots > 0:
                        slot = int(time.time() // 3600) % rotation_slots
                        backup_name = f"{base_name}_{slot:02d}"
                    else:
                        backup_name = base_name
                else:
                    backup_name = f"{job_name}_{timestamp}"

                dest_path_base = os.path.join(dest_dir, backup_name)
                dest_zip_path = dest_path_base + '.zip'
                if os.path.exists(dest_zip_path):
                    try:
                        os.remove(dest_zip_path)
                    except Exception:
                        pass
                
                shutil.make_archive(dest_path_base, 'zip', source_dir)
                logger.info(f"Directory backup '{job_name}' created: {dest_path_base}.zip")
                
                BACKUP_STATUS[job_name] = {
                    'last_run': datetime.now().isoformat(),
                    'status': 'success',
                    'message': f"Backup saved to {dest_path_base}.zip"
                }
                
                # Log success for full_system only to reduce noise, or all?
                # Let's log full_system and reception as they are critical
                if LoggerService and job_name in ['full_system', 'reception', 'products']:
                    LoggerService.log_acao(
                        acao=f"Backup Automático Realizado ({job_name})",
                        entidade="Backup",
                        detalhes={'file': f"{dest_path_base}.zip"},
                        nivel_severidade='INFO',
                        departamento_id='TI'
                    )

            else:
                # Copy specific files
                files_copied = 0
                for fname in config['source_files']:
                    src_path = os.path.join(DATA_DIR, fname)
                    if os.path.exists(src_path):
                        # Destination filename includes timestamp
                        name, ext = os.path.splitext(fname)
                        dest_fname = f"{name}_{timestamp}{ext}"
                        dest_path = os.path.join(dest_dir, dest_fname)
                        
                        shutil.copy2(src_path, dest_path)
                        files_copied += 1
                
                if files_copied > 0:
                    msg = f"Backup '{job_name}' completed. {files_copied} files copied to {dest_dir}"
                    logger.info(msg)
                    BACKUP_STATUS[job_name] = {
                        'last_run': datetime.now().isoformat(),
                        'status': 'success',
                        'message': msg
                    }
                    if LoggerService and job_name in ['reception', 'products']:
                         LoggerService.log_acao(
                            acao=f"Backup Automático Realizado ({job_name})",
                            entidade="Backup",
                            detalhes={'files_count': files_copied},
                            nivel_severidade='INFO',
                            departamento_id='TI'
                        )
                else:
                    msg = f"No source files found for backup '{job_name}'"
                    logger.warning(msg)
                    BACKUP_STATUS[job_name] = {
                        'last_run': datetime.now().isoformat(),
                        'status': 'warning',
                        'message': msg
                    }
                    
        except Exception as e:
            # Re-raise to be caught by _run_job
            if LoggerService:
                 LoggerService.log_acao(
                    acao=f"Erro no Backup Automático ({job_name})",
                    entidade="Backup",
                    detalhes={'error': str(e)},
                    nivel_severidade='ERRO',
                    departamento_id='TI'
                )
            raise e

    def restore_backup(self, backup_type, filename):
        """
        Restores a specific backup file to the data directory.
        Only works for non-full backups (single files).
        """
        if backup_type not in BACKUP_CONFIGS or backup_type == 'full_system':
            return False, "Invalid backup type or full system restore not supported via this method."

        config = BACKUP_CONFIGS[backup_type]
        backup_path = os.path.join(config['dest_dir'], filename)
        
        if not os.path.exists(backup_path):
            return False, "Backup file not found."

        # Determine original filename from backup filename (remove timestamp)
        # Pattern: name_TIMESTAMP.ext
        # We need to find which source file matches
        target_file = None
        for src_file in config['source_files']:
            name, ext = os.path.splitext(src_file)
            # Check if filename starts with name and ends with ext
            if filename.startswith(name) and filename.endswith(ext):
                target_file = src_file
                break
        
        if not target_file:
            return False, "Could not determine target file from backup name."

        dest_path = os.path.join(DATA_DIR, target_file)
        
        try:
            # Use file_lock if available to ensure atomic overwrite
            # Note: We lock the destination file
            try:
                with file_lock(dest_path):
                     shutil.copy2(backup_path, dest_path)
            except NameError:
                 # Fallback if file_lock not imported
                 shutil.copy2(backup_path, dest_path)
                 
            logger.info(f"Restored {target_file} from {filename}")
            return True, f"Successfully restored {target_file}"
        except Exception as e:
            logger.error(f"Failed to restore {filename}: {e}")
            return False, str(e)

    def get_status(self):
        """Returns the current status of all backup jobs."""
        return BACKUP_STATUS


    def _cleanup_old_backups(self, job_name, config):
        if job_name == 'full_system' and int(config.get('rotation_slots') or 0) > 0:
            return
        dest_dir = config['dest_dir']
        if not os.path.exists(dest_dir):
            return

        retention_count = config.get('retention_count', 0)
        if retention_count and int(retention_count) > 0:
            retention_count = int(retention_count)
            try:
                if 'source_files' in config:
                    for src_file in config['source_files']:
                        name, ext = os.path.splitext(src_file)
                        pattern = os.path.join(dest_dir, f"{name}_*{ext}")
                        files = glob.glob(pattern)
                        files.sort(key=os.path.getmtime, reverse=True)
                        for fpath in files[retention_count:]:
                            try:
                                if os.path.isfile(fpath):
                                    os.remove(fpath)
                                    logger.debug(f"Removed old backup: {fpath}")
                            except Exception as e:
                                logger.warning(f"Failed to remove old backup {fpath}: {e}")
                else:
                    files = glob.glob(os.path.join(dest_dir, "*"))
                    files.sort(key=os.path.getmtime, reverse=True)
                    for fpath in files[retention_count:]:
                        try:
                            if os.path.isfile(fpath):
                                os.remove(fpath)
                                logger.debug(f"Removed old backup: {fpath}")
                        except Exception as e:
                            logger.warning(f"Failed to remove old backup {fpath}: {e}")
            except Exception as e:
                logger.warning(f"Failed retention cleanup for {job_name}: {e}")
            return

        now = datetime.now()

        retention_minutes = config.get('retention_minutes', 0)
        retention_hours = config.get('retention_hours', 0)
        
        if retention_minutes > 0:
            cutoff_time = now - timedelta(minutes=retention_minutes)
        elif retention_hours > 0:
            cutoff_time = now - timedelta(hours=retention_hours)
        else:
            return # No retention policy

        # List all files in dest_dir
        for fpath in glob.glob(os.path.join(dest_dir, "*")):
            try:
                if os.path.isfile(fpath):
                    mtime = datetime.fromtimestamp(os.path.getmtime(fpath))
                    if mtime < cutoff_time:
                        os.remove(fpath)
                        logger.debug(f"Removed old backup: {fpath}")
            except Exception as e:
                logger.warning(f"Failed to remove old backup {fpath}: {e}")

    def get_backup_path(self, backup_type):
        """Returns the directory path for a specific backup type."""
        if backup_type in BACKUP_CONFIGS:
            return BACKUP_CONFIGS[backup_type]['dest_dir']
        return None

    def list_backups(self, backup_type):
        """Returns a list of available backups for a type."""
        path = self.get_backup_path(backup_type)
        if not path or not os.path.exists(path):
            return []
        
        files = glob.glob(os.path.join(path, "*"))
        files.sort(key=os.path.getmtime, reverse=True)
        return files

    def get_config(self):
        """Returns the current configuration."""
        return BACKUP_CONFIGS

    def update_config(self, backup_type, interval, retention, retention_unit='hours'):
        if backup_type not in BACKUP_CONFIGS:
            return False, "Invalid backup type"
            
        try:
            config = BACKUP_CONFIGS[backup_type]
            
            # Update Interval
            if interval is not None:
                config['interval_seconds'] = int(interval)
                
            # Update Retention
            if retention is not None:
                retention = int(retention)
                if retention_unit == 'count':
                    config['retention_count'] = retention
                    config['retention_hours'] = 0
                    config['retention_minutes'] = 0
                elif retention_unit == 'minutes':
                    config['retention_minutes'] = retention
                    config['retention_hours'] = 0
                    config['retention_count'] = 0
                else:
                    config['retention_hours'] = retention
                    config['retention_minutes'] = 0
                    config['retention_count'] = 0
            
            save_backup_config()
            return True, "Configuration updated successfully."
        except ValueError:
            return False, "Invalid numeric values"
        except Exception as e:
            return False, str(e)

# Global instance
load_backup_config()
if 'full_system' in BACKUP_CONFIGS:
    BACKUP_CONFIGS['full_system']['dest_dir'] = os.path.join(BACKUPS_DIR, 'Sistema_Completo')
    BACKUP_CONFIGS['full_system']['interval_seconds'] = 3600
    BACKUP_CONFIGS['full_system']['rotation_slots'] = 24
    BACKUP_CONFIGS['full_system']['base_name'] = 'Servidor Teste'
    BACKUP_CONFIGS['full_system']['retention_hours'] = 0
    BACKUP_CONFIGS['full_system']['retention_minutes'] = 0
    BACKUP_CONFIGS['full_system']['retention_count'] = 0
_init_backup_status()
backup_service = BackupService()

def start_backup_scheduler():
    backup_service.start()
