
from logger_service import LoggerService

def log_action(action_type, details, user=None, department=None):
    """
    Logs an action using the centralized LoggerService.
    Maintained for backward compatibility.
    """
    if user is None:
        user = 'Sistema' # Default if not provided
    
    if department is None:
        department = 'Geral' # Default
        
    try:
        LoggerService.log_acao(
            acao=action_type,
            entidade='Audit Action',
            detalhes=details,
            departamento_id=department,
            colaborador_id=user
        )
        return True
    except Exception as e:
        print(f"Error logging action via LoggerService: {e}")
        return False

