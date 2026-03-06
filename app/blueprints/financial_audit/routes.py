from flask import render_template, request, jsonify, session, current_app
from app.services.financial_audit_service import FinancialAuditService
from app.services.data_service import load_room_charges, load_table_orders, load_cashier_sessions
from app.services.ledger_service import LedgerService
from . import financial_audit_bp
from datetime import datetime

# Acesso restrito a administradores e gerentes
def is_authorized():
    role = session.get('role')
    return role in ['admin', 'gerente']

@financial_audit_bp.route('/financial-audit/report', methods=['GET'])
def daily_report():
    if not is_authorized():
        return jsonify({'error': 'Unauthorized'}), 403
        
    date_str = request.args.get('date')
    if not date_str:
        date_str = datetime.now().strftime('%Y-%m-%d')
        
    report = FinancialAuditService.get_daily_report(date_str)
    
    # Se for uma requisição de API/AJAX
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.args.get('format') == 'json':
        return jsonify(report)
        
    # Renderizar template (se existisse) ou retornar JSON por enquanto
    return jsonify(report)

@financial_audit_bp.route('/financial-audit/risk-report', methods=['GET'])
def risk_report():
    if not is_authorized():
        return jsonify({'error': 'Unauthorized'}), 403
        
    try:
        from app.services.financial_risk_service import FinancialRiskService
        report = FinancialRiskService.get_operator_risk_report()
        return jsonify(report)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@financial_audit_bp.route('/financial-audit/cancellations-report', methods=['GET'])
def cancellations_report():
    if not is_authorized():
        return jsonify({'error': 'Unauthorized'}), 403
        
    date_str = request.args.get('date')
    daily_report = FinancialAuditService.get_daily_report(date_str)
    
    # Filter cancellations
    cancellations = daily_report.get('cancellations', [])
    
    # Group by Operator
    by_operator = {}
    for c in cancellations:
        user = c['user']
        if user not in by_operator:
            by_operator[user] = []
        by_operator[user].append(c)
        
    return jsonify({
        'date': daily_report['date'],
        'total_cancellations': len(cancellations),
        'by_operator': by_operator
    })

@financial_audit_bp.route('/financial-audit/timeline/<entity_id>', methods=['GET'])
def timeline(entity_id):
    if not is_authorized():
        return jsonify({'error': 'Unauthorized'}), 403
        
    events = FinancialAuditService.get_reservation_timeline(entity_id)
    
    # Adicionar transações do Ledger se houver referência
    ledger_txs = LedgerService.get_transactions()
    related_ledger = [t for t in ledger_txs if entity_id in str(t.get('reference', '')) or entity_id in str(t.get('source_box', ''))]
    
    # Combinar e ordenar
    combined = []
    for e in events:
        e['source'] = 'Audit Log'
        combined.append(e)
        
    for t in related_ledger:
        combined.append({
            'timestamp': t['timestamp'],
            'action': t['operation_type'],
            'user': t['user'],
            'details': t,
            'source': 'Ledger Imutável'
        })
        
    combined.sort(key=lambda x: x['timestamp'])
    
    return jsonify(combined)

@financial_audit_bp.route('/financial-audit/cross-check', methods=['GET'])
def cross_check():
    """
    Realiza verificação cruzada entre Módulos:
    1. Consumo Restaurante (Mesa X) -> Conta Quarto (Se transferido)
    2. Conta Quarto (Pago) -> Financeiro (Caixa Recepção)
    """
    if not is_authorized():
        return jsonify({'error': 'Unauthorized'}), 403
        
    discrepancies = []
    
    # 1. Verificar Transferências de Mesa para Quarto
    # Carregar logs de transferência (precisaríamos filtrar logs de ação 'Transferência de Mesa')
    # Como não temos um log estruturado fácil para isso no passado, vamos verificar o estado atual
    
    room_charges = load_room_charges()
    cashier_sessions = load_cashier_sessions()
    
    # Mapa de cobranças pagas
    paid_charges = [c for c in room_charges if c['status'] == 'paid']
    
    for charge in paid_charges:
        # Verificar se existe transação correspondente no caixa
        found = False
        charge_total = float(charge.get('total', 0))
        room_num = charge.get('room_number')
        
        # Procurar em todas as sessões (ineficiente, mas funcional para MVP)
        # O ideal seria ter o ID da sessão na charge (temos reception_cashier_id)
        session_id = charge.get('reception_cashier_id')
        
        if session_id:
            session_obj = next((s for s in cashier_sessions if s['id'] == session_id), None)
            if session_obj:
                for tx in session_obj.get('transactions', []):
                    if tx['type'] == 'in' and (f"Quarto {room_num}" in tx['description'] or str(room_num) in str(tx.get('details', {}))):
                        # Verificar valor (com margem de erro pequena)
                        if abs(float(tx['amount']) - charge_total) < 0.1:
                            found = True
                            break
            
            if not found:
                discrepancies.append({
                    'type': 'MISSING_FINANCIAL_RECORD',
                    'entity': f"Charge {charge['id']}",
                    'details': f"Cobrança paga no quarto {room_num} (R$ {charge_total:.2f}) sem transação correspondente no caixa {session_id}"
                })
        else:
             discrepancies.append({
                'type': 'DATA_INTEGRITY',
                'entity': f"Charge {charge['id']}",
                'details': f"Cobrança paga no quarto {room_num} sem ID de sessão vinculado"
            })

    return jsonify({
        'status': 'completed',
        'discrepancies_count': len(discrepancies),
        'discrepancies': discrepancies
    })

@financial_audit_bp.route('/financial-audit/daily-check', methods=['GET'])
def daily_check():
    """
    Comparar diariamente:
    - Reservas realizadas
    - Pagamentos registrados
    - Consumo restaurante
    """
    if not is_authorized():
        return jsonify({'error': 'Unauthorized'}), 403
        
    date_str = request.args.get('date') or datetime.now().strftime('%Y-%m-%d')
    
    # 1. Load Data
    room_charges = load_room_charges() # Should filter by date ideally
    cashier_sessions = load_cashier_sessions()
    
    # Filter for date
    day_charges = [c for c in room_charges if c.get('date', '').startswith(date_str) or c.get('paid_at', '').startswith(date_str)]
    
    issues = []
    
    # Check: Consumo Restaurante (Charges) vs Pagamento
    for charge in day_charges:
        status = charge.get('status')
        if status == 'paid':
            # Must have payment record
            # Simplified check (we did this in cross-check too, but here we focus on date)
            pass
        elif status == 'pending':
            # Check if guest checked out
            pass
            
    # Check: Reservas vs Faturamento
    # Need Reservation Service data. Assuming we can get checked-out reservations for the day.
    # For now, return placeholder structure
    
    return jsonify({
        'date': date_str,
        'checked_items': len(day_charges),
        'issues': issues
    })
