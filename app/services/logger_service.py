from app.models.database import db
from app.models.models import LogAcaoDepartamento
from flask import session, current_app
import json
import traceback
import random
from datetime import datetime, timedelta

class LoggerService:
    _app = None

    @staticmethod
    def init_app(app):
        LoggerService._app = app

    @staticmethod
    def log_acao(acao, entidade, detalhes=None, nivel_severidade='INFO', departamento_id=None, colaborador_id=None):
        """
        Registra uma ação no sistema de logs departamental.
        """
        # Ensure we are in an application context
        try:
            # Check if we are in a valid context by accessing current_app.name
            _ = current_app.name
            return LoggerService._log_internal(acao, entidade, detalhes, nivel_severidade, departamento_id, colaborador_id)
        except (RuntimeError, KeyError):
            # We are outside of application context
            if LoggerService._app:
                with LoggerService._app.app_context():
                    return LoggerService._log_internal(acao, entidade, detalhes, nivel_severidade, departamento_id, colaborador_id)
            else:
                print("LoggerService: No application context and no app instance initialized.")
                return False

    @staticmethod
    def _log_internal(acao, entidade, detalhes=None, nivel_severidade='INFO', departamento_id=None, colaborador_id=None):
        try:
            # Contexto automático da sessão se não fornecido
            if not departamento_id:
                try:
                    if session:
                        departamento_id = session.get('department', 'Geral')
                    else:
                        departamento_id = 'Sistema'
                except (RuntimeError, KeyError): 
                    departamento_id = 'Sistema'
            
            if not colaborador_id:
                try:
                    if session:
                        colaborador_id = session.get('user', 'Sistema')
                    else:
                        colaborador_id = 'Sistema'
                except (RuntimeError, KeyError):
                    colaborador_id = 'Sistema'
                
            # Serializa detalhes
            detalhes_str = None
            if detalhes:
                if isinstance(detalhes, (dict, list)):
                    try:
                        detalhes_str = json.dumps(detalhes, ensure_ascii=False, default=str)
                    except:
                        detalhes_str = str(detalhes)
                else:
                    detalhes_str = str(detalhes)
            
            new_log = LogAcaoDepartamento(
                departamento_id=str(departamento_id),
                colaborador_id=str(colaborador_id),
                acao=acao,
                entidade=entidade,
                detalhes=detalhes_str,
                nivel_severidade=nivel_severidade
            )
            
            db.session.add(new_log)
            db.session.commit()
            
            # Executa limpeza de logs antigos ocasionalmente (1% das vezes)
            if random.random() < 0.01:
                LoggerService.cleanup_logs()
                
            return True
        except Exception as e:
            print(f"ERRO CRÍTICO AO SALVAR LOG: {e}")
            traceback.print_exc()
            return False

    @staticmethod
    def cleanup_logs(retention_days=45):
        """
        Remove logs mais antigos que o período de retenção (padrão 45 dias).
        """
        try:
            cutoff_date = datetime.now() - timedelta(days=retention_days)
            deleted_count = LogAcaoDepartamento.query.filter(LogAcaoDepartamento.timestamp < cutoff_date).delete()
            db.session.commit()
            if deleted_count > 0:
                print(f"LoggerService: Cleaned up {deleted_count} old logs.")
            return True
        except Exception as e:
            print(f"LoggerService Error cleaning up logs: {e}")
            return False

    @staticmethod
    def get_logs(departamento_id=None, start_date=None, end_date=None, page=1, per_page=50, colaborador_id=None, acao=None, search_query=None, nivel_severidade=None):
        """
        Recupera logs com filtros e paginação.
        """
        query = LogAcaoDepartamento.query
        
        if departamento_id:
            query = query.filter_by(departamento_id=departamento_id)
            
        if colaborador_id:
            query = query.filter_by(colaborador_id=colaborador_id)
            
        if acao:
            query = query.filter(LogAcaoDepartamento.acao.ilike(f"%{acao}%"))

        if nivel_severidade:
            query = query.filter_by(nivel_severidade=nivel_severidade)

        if search_query:
            query = query.filter(LogAcaoDepartamento.detalhes.ilike(f"%{search_query}%"))
            
        if start_date:
            if isinstance(start_date, str):
                try:
                    start_date = datetime.strptime(start_date, '%Y-%m-%d')
                except: pass
            query = query.filter(LogAcaoDepartamento.timestamp >= start_date)
            
        if end_date:
            if isinstance(end_date, str):
                try:
                    end_date = datetime.strptime(end_date, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
                except: pass
            query = query.filter(LogAcaoDepartamento.timestamp <= end_date)
            
        # Ordenação: mais recente primeiro
        pagination = query.order_by(LogAcaoDepartamento.timestamp.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )
        
        return {
            'items': [log.to_dict() for log in pagination.items],
            'total': pagination.total,
            'pages': pagination.pages,
            'current_page': page,
            'has_next': pagination.has_next,
            'has_prev': pagination.has_prev
        }

def log_system_action(action, details, user='Sistema', category='Geral', **kwargs):
    """
    Helper function to maintain compatibility with legacy calls.
    Maps to LoggerService.log_acao.
    """
    if 'department' in kwargs:
        category = kwargs['department']

    return LoggerService.log_acao(
        acao=action,
        entidade=category,
        detalhes=details,
        colaborador_id=user
    )
