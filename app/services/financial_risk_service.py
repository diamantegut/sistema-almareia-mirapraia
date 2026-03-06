import json
import os
import uuid
import logging
from datetime import datetime, timedelta
from app.services.system_config_manager import FINANCIAL_RISK_EVENTS_FILE
from app.services.financial_audit_service import FinancialAuditService
from app.services.logger_service import LoggerService

# Configure logging
logger = logging.getLogger(__name__)

class FinancialRiskService:
    FILE_PATH = FINANCIAL_RISK_EVENTS_FILE

    # Pontuação de Risco
    SCORE_CANCEL = 1
    SCORE_REVERSAL = 2
    SCORE_HIGH_DISCOUNT = 3
    SCORE_CASH_DIFF = 5

    # Limites
    LIMIT_SCORE_HIGH_RISK = 10
    LIMIT_DISCOUNT_PERCENT = 20.0

    @staticmethod
    def _load_risk_events():
        if not os.path.exists(FinancialRiskService.FILE_PATH):
            return []
        try:
            with open(FinancialRiskService.FILE_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return []

    @staticmethod
    def _save_risk_events(events):
        temp_path = FinancialRiskService.FILE_PATH + '.tmp'
        try:
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(events, f, indent=4, ensure_ascii=False)
            
            if os.path.exists(FinancialRiskService.FILE_PATH):
                os.replace(temp_path, FinancialRiskService.FILE_PATH)
            else:
                os.rename(temp_path, FinancialRiskService.FILE_PATH)
        except Exception as e:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            logger.error(f"Error saving financial risk events: {e}")

    @classmethod
    def record_risk_event(cls, user, event_type, score, details):
        """
        Registra um evento de risco financeiro.
        """
        try:
            timestamp = datetime.now().isoformat()
            
            event = {
                'id': str(uuid.uuid4()),
                'timestamp': timestamp,
                'user': user,
                'event_type': event_type,
                'score': score,
                'details': details or {}
            }

            events = cls._load_risk_events()
            events.append(event)
            cls._save_risk_events(events)

            # Verificar se o usuário ultrapassou o limite de risco no turno (últimas 12h)
            cls._check_operator_risk(user, events)

            return event
        except Exception as e:
            logger.error(f"Failed to record risk event: {e}")
            return None

    @classmethod
    def _check_operator_risk(cls, user, all_events):
        """
        Verifica a pontuação acumulada do operador nas últimas 12 horas.
        """
        now = datetime.now()
        shift_start = now - timedelta(hours=12)
        
        total_score = 0
        current_shift_events = []
        
        for event in all_events:
            if event['user'] == user:
                event_dt = datetime.fromisoformat(event['timestamp'])
                if event_dt >= shift_start:
                    total_score += event['score']
                    current_shift_events.append(event)
        
        if total_score > cls.LIMIT_SCORE_HIGH_RISK:
            # Check if already alerted recently (to avoid spam)
            # We can check LoggerService logs or just log it.
            # For MVP, we just log.
            alert_msg = f"ALTO RISCO: Operador {user} atingiu score {total_score} no turno."
            logger.critical(alert_msg)
            
            LoggerService.log_acao(
                acao="HIGH_RISK_OPERATOR",
                entidade="Monitoramento de Risco",
                detalhes={
                    'user': user,
                    'score': total_score,
                    'events_count': len(current_shift_events)
                },
                nivel_severidade="CRITICAL",
                colaborador_id="SYSTEM"
            )

    @classmethod
    def analyze_audit_log(cls):
        """
        Analisa o log de auditoria recente para identificar padrões de risco
        que não foram capturados em tempo real.
        Deve ser rodado periodicamente (ex: a cada 15 min).
        """
        # Carregar logs de auditoria do dia
        audit_logs = FinancialAuditService.get_daily_report()['cancellations'] # + reversals etc.
        # Mas get_daily_report retorna dict processado. Melhor ler raw logs.
        # Para evitar ler tudo, vamos focar no que FinancialAuditService já tem.
        
        # Na verdade, a melhor abordagem é processar os logs brutos recentes.
        # Como o FinancialAuditService já tem _load_logs, podemos usar helper.
        
        # Vamos implementar regras específicas aqui:
        # 1. Mais de 3 mudanças de forma de pagamento na mesma conta
        # 2. Descontos acima de 20%
        # 3. Fechamento seguido de cancelamento
        pass 
        # (Implementação real será feita via integração direta no FinancialAuditService
        # ou scanning periódico. Scanning é melhor para regras complexas temporais).

    @classmethod
    def perform_periodic_scan(cls):
        """
        Executa a verificação automática de regras complexas.
        """
        try:
            logs = FinancialAuditService._load_logs()
            if not logs:
                return

            now = datetime.now()
            scan_window = now - timedelta(minutes=20) # Scan last 20 mins (overlapping 15 min job)
            
            recent_logs = [l for l in logs if datetime.fromisoformat(l['timestamp']) >= scan_window]
            
            # Agrupar por entidade (ex: Table ID, Charge ID) para análise de sequência
            events_by_entity = {}
            for log in recent_logs:
                entity = log.get('entity')
                if not entity: continue
                if entity not in events_by_entity:
                    events_by_entity[entity] = []
                events_by_entity[entity].append(log)
                
            # Regra: Fechamento seguido de Cancelamento
            # Precisamos identificar eventos de "Pagamento/Fechamento" (não estão explícitos no AuditLog ainda, 
            # mas podemos inferir ou adicionar).
            # Por enquanto, focamos no que temos: Cancelamentos.
            
            # Regra: Mais de 3 mudanças de pagamento (EVENT_PAYMENT_CHANGE)
            for entity, events in events_by_entity.items():
                payment_changes = [e for e in events if e['action'] == FinancialAuditService.EVENT_PAYMENT_CHANGE]
                if len(payment_changes) > 3:
                    user = payment_changes[0]['user']
                    # Check if already recorded risk for this entity/rule to avoid dupes?
                    # For MVP, we record.
                    cls.record_risk_event(
                        user=user,
                        event_type="EXCESSIVE_PAYMENT_CHANGES",
                        score=2, # Arbitrary score for this rule
                        details={'entity': entity, 'count': len(payment_changes)}
                    )

            # Regra: Descontos acima de 20%
            # Precisamos capturar EVENT_DISCOUNT (adicionado ao AuditService)
            # Vamos assumir que FinancialAuditService loga isso.
            
        except Exception as e:
            logger.error(f"Error in periodic risk scan: {e}")

    @classmethod
    def get_operator_risk_report(cls):
        """
        Gera relatório consolidado de risco por operador.
        """
        events = cls._load_risk_events()
        report = {}
        
        for e in events:
            user = e['user']
            if user not in report:
                report[user] = {'score': 0, 'events': []}
            
            report[user]['score'] += e['score']
            report[user]['events'].append(e)
            
        # Sort by score desc
        sorted_report = dict(sorted(report.items(), key=lambda item: item[1]['score'], reverse=True))
        return sorted_report
