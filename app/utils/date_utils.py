from datetime import datetime

def get_reference_period(date_obj):
    """
    Calcula o período de referência (ciclo) da conferência.
    Ciclo: Dia 16 do mês anterior até dia 15 do mês atual (ou corrente).
    Regra:
    - Se dia >= 16: Início = 16/MêsAtual, Fim = 15/PróximoMês
    - Se dia < 16: Início = 16/MêsAnterior, Fim = 15/MêsAtual
    """
    if date_obj.day >= 16:
        start_date = date_obj.replace(day=16)
        if date_obj.month == 12:
            end_date = date_obj.replace(year=date_obj.year + 1, month=1, day=15)
        else:
            end_date = date_obj.replace(month=date_obj.month + 1, day=15)
    else:
        end_date = date_obj.replace(day=15)
        if date_obj.month == 1:
            start_date = date_obj.replace(year=date_obj.year - 1, month=12, day=16)
        else:
            start_date = date_obj.replace(month=date_obj.month - 1, day=16)
            
    return f"{start_date.strftime('%d/%m/%Y')} a {end_date.strftime('%d/%m/%Y')}"
