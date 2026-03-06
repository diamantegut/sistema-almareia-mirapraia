import json
import os
import uuid
import logging
from datetime import datetime
from flask import request
from app.services.system_config_manager import FINANCIAL_AUDIT_LOGS_FILE
from app.services.logger_service import LoggerService

# Configure logging
logger = logging.getLogger(__name__)

class FinancialAuditService:
    FILE_PATH = FINANCIAL_AUDIT_LOGS_FILE

    # Tipos de Eventos Auditados
    EVENT_CANCEL = 'CANCELAMENTO'
    EVENT_REVERSAL = 'ESTORNO'
    EVENT_BLEEDING = 'SANGRIA'
    EVENT_SUPPLY = 'SUPRIMENTO'
    EVENT_TRANSFER = 'TRANSFERENCIA'
    EVENT_PAYMENT_CHANGE = 'ALTERACAO_PAGAMENTO'
    EVENT_DISCOUNT = 'DESCONTO'
    EVENT_VOID_ITEM = 'ITEM_CANCELADO'

    # Limites para Alertas (Hardcoded por enquanto, idealmente configurável)
    ALERT_THRESHOLDS = {
        'max_daily_cancellations': 5,
        'max_daily_reversals': 3,
        'max_transfer_amount': 5000.0,
        'suspicious_hours_start': 0, # 00:00
        'suspicious_hours_end': 6    # 06:00
    }

    @staticmethod
    def _load_logs():
        if not os.path.exists(FinancialAuditService.FILE_PATH):
            return []
        try:
            with open(FinancialAuditService.FILE_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return []

    @staticmethod
    def _save_logs(logs):
        # Atomic write
        temp_path = FinancialAuditService.FILE_PATH + '.tmp'
        try:
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(logs, f, indent=4, ensure_ascii=False)
            
            if os.path.exists(FinancialAuditService.FILE_PATH):
                os.replace(temp_path, FinancialAuditService.FILE_PATH)
            else:
                os.rename(temp_path, FinancialAuditService.FILE_PATH)
        except Exception as e:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            logger.error(f"Error saving financial audit logs: {e}")

    @classmethod
    def log_event(cls, user, action, entity, old_data=None, new_data=None, details=None):
        """
        Registra um evento de auditoria financeira.
        """
        try:
            # Capturar IP
            ip_address = 'Unknown'
            try:
                if request:
                    ip_address = request.remote_addr or request.headers.get('X-Forwarded-For', 'Unknown')
            except RuntimeError:
                pass # Fora do contexto da request (CLI, script)

            timestamp = datetime.now().isoformat()
            
            log_entry = {
                'id': str(uuid.uuid4()),
                'timestamp': timestamp,
                'user': user,
                'action': action,
                'entity': entity, # ex: 'Table 10', 'Transaction 123'
                'ip_address': ip_address,
                'old_data': old_data,
                'new_data': new_data,
                'details': details or {}
            }

            logs = cls._load_logs()
            logs.append(log_entry)
            cls._save_logs(logs)

            # Verificar Alertas
            cls._check_alerts(log_entry, logs)

            # Log também no LoggerService genérico para redundância
            LoggerService.log_acao(
                acao=f"AUDIT_{action}",
                entidade='Auditoria Financeira',
                detalhes=log_entry,
                colaborador_id=user,
                nivel_severidade='WARNING' if action in [cls.EVENT_CANCEL, cls.EVENT_REVERSAL] else 'INFO'
            )

            return log_entry
        except Exception as e:
            logger.error(f"Failed to log financial audit event: {e}")
            return None

    @classmethod
    def _check_alerts(cls, current_entry, all_logs):
        """
        Analisa o evento atual contra o histórico para detectar padrões suspeitos.
        """
        alerts = []
        user = current_entry['user']
        action = current_entry['action']
        timestamp_dt = datetime.fromisoformat(current_entry['timestamp'])
        today_str = timestamp_dt.strftime('%Y-%m-%d')

        # 1. Operações fora do horário (00:00 - 06:00)
        hour = timestamp_dt.hour
        if cls.ALERT_THRESHOLDS['suspicious_hours_start'] <= hour < cls.ALERT_THRESHOLDS['suspicious_hours_end']:
            alerts.append(f"Operação fora do horário comercial ({hour}h)")

        # 2. Muitos cancelamentos/estornos no dia pelo mesmo usuário
        if action in [cls.EVENT_CANCEL, cls.EVENT_REVERSAL]:
            daily_count = 0
            for log in all_logs:
                if log['user'] == user and log['action'] == action:
                    log_dt = datetime.fromisoformat(log['timestamp'])
                    if log_dt.strftime('%Y-%m-%d') == today_str:
                        daily_count += 1
            
            limit = cls.ALERT_THRESHOLDS['max_daily_cancellations'] if action == cls.EVENT_CANCEL else cls.ALERT_THRESHOLDS['max_daily_reversals']
            
            if daily_count > limit:
                msg = f"Excesso de {action} diários para o usuário {user} ({daily_count}/{limit})"
                alerts.append(msg)
                
                # --- RISK INTEGRATION ---
                try:
                    from app.services.financial_risk_service import FinancialRiskService
                    score = FinancialRiskService.SCORE_CANCEL if action == cls.EVENT_CANCEL else FinancialRiskService.SCORE_REVERSAL
                    FinancialRiskService.record_risk_event(
                        user=user,
                        event_type=f"EXCESSIVE_{action}",
                        score=score,
                        details={'count': daily_count, 'limit': limit}
                    )
                except Exception as e:
                    logger.error(f"Failed to record risk event: {e}")

        # 3. Transferências de alto valor
        if action == cls.EVENT_TRANSFER:
            try:
                amount = 0
                if current_entry.get('new_data') and 'amount' in current_entry['new_data']:
                    amount = float(current_entry['new_data']['amount'])
                elif current_entry.get('details') and 'amount' in current_entry['details']:
                    amount = float(current_entry['details']['amount'])
                
                if amount > cls.ALERT_THRESHOLDS['max_transfer_amount']:
                    alerts.append(f"Transferência de alto valor detectada: R$ {amount:.2f}")
            except:
                pass

        # Disparar Alertas
        if alerts:
            for alert in alerts:
                logger.warning(f"SECURITY ALERT: {alert} | Event ID: {current_entry['id']}")
                # Aqui poderia enviar email/notificação
                LoggerService.log_acao(
                    acao="SECURITY_ALERT",
                    entidade="Sistema de Alerta",
                    detalhes={'alert': alert, 'trigger_event': current_entry['id']},
                    nivel_severidade="CRITICAL",
                    colaborador_id="SYSTEM"
                )

    @classmethod
    def get_daily_report(cls, date_str=None):
        """
        Gera relatório consolidado para uma data (YYYY-MM-DD).
        Se date_str for None, usa hoje.
        """
        if not date_str:
            date_str = datetime.now().strftime('%Y-%m-%d')
            
        logs = cls._load_logs()
        daily_logs = [l for l in logs if l['timestamp'].startswith(date_str)]
        
        report = {
            'date': date_str,
            'total_events': len(daily_logs),
            'by_action': {},
            'by_user': {},
            'alerts_triggered': [],
            'cancellations': [],
            'reversals': [],
            'transfers': []
        }
        
        for log in daily_logs:
            # Contagem por Ação
            action = log['action']
            report['by_action'][action] = report['by_action'].get(action, 0) + 1
            
            # Contagem por Usuário
            user = log['user']
            report['by_user'][user] = report['by_user'].get(user, 0) + 1
            
            # Detalhes específicos
            if action == cls.EVENT_CANCEL:
                report['cancellations'].append(log)
            elif action == cls.EVENT_REVERSAL:
                report['reversals'].append(log)
            elif action == cls.EVENT_TRANSFER:
                report['transfers'].append(log)
                
        return report

    @classmethod
    def get_reservation_timeline(cls, reservation_id_or_room):
        """
        Busca eventos relacionados a uma reserva ou quarto.
        """
        logs = cls._load_logs()
        timeline = []
        
        search_term = str(reservation_id_or_room)
        
        for log in logs:
            match = False
            # Check entity
            if search_term in str(log.get('entity', '')):
                match = True
            # Check details
            elif search_term in str(log.get('details', '')):
                match = True
            
            if match:
                timeline.append(log)
                
        return sorted(timeline, key=lambda x: x['timestamp'])
