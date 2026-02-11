from flask import render_template, request, redirect, url_for, flash, jsonify, session
import json
import re
from datetime import datetime, timedelta
from . import reports_bp
from app.utils.decorators import login_required
from app.services.data_service import (
    load_products, load_stock_requests, load_stock_entries, load_stock_logs,
    load_maintenance_requests, load_table_orders, load_room_charges,
    load_cleaning_status, load_quality_audits
)
from app.services.system_config_manager import DEPARTMENTS

@reports_bp.route('/reports', methods=['GET', 'POST'])
@login_required
def reports():
    if session.get('role') != 'gerente' and session.get('role') != 'admin':
        flash('Acesso não autorizado. Apenas gerentes podem acessar relatórios.')
        return redirect(url_for('main.index'))
        
    department = session.get('department')
    
    # Se for admin, usa o departamento selecionado no filtro (se houver) ou default
    if session.get('role') == 'admin':
        if request.method == 'POST' and request.form.get('department'):
            department = request.form.get('department')
        elif not department or department == 'Diretoria':
            department = 'Cozinha' # Default para visualização
            
    report_data = []
    stock_logs = []
    purchase_summary = None
    consumption_summary = None
    stock_alerts = None
    
    start_date = None
    end_date = None
    
    if request.method == 'POST':
        start_date = request.form['start_date']
        end_date = request.form['end_date']
        
        try:
            d_start = datetime.strptime(start_date, '%d/%m/%Y')
            d_end = datetime.strptime(end_date, '%d/%m/%Y')
            # Ensure end date includes the full day
            d_end = d_end.replace(hour=23, minute=59, second=59)
            
            period_days = (d_end - d_start).days + 1
            weeks_in_period = max(period_days / 7, 1) # Avoid division by zero
            
            # Load and Filter Stock Logs
            try:
                 all_logs = load_stock_logs()
                 for log in all_logs:
                     try:
                         # Attempt to parse date from log
                         log_date_str = log.get('date', '')
                         log_date = None
                         try:
                             log_date = datetime.strptime(log_date_str, '%d/%m/%Y %H:%M')
                         except ValueError:
                             try:
                                 log_date = datetime.strptime(log_date_str, '%d/%m/%Y')
                             except ValueError: pass
                         
                         if log_date and d_start <= log_date <= d_end:
                             stock_logs.append(log)
                     except Exception: pass
                 
                 # Sort Logs (Newest First)
                 def parse_log_date(d):
                     try: return datetime.strptime(d, '%d/%m/%Y %H:%M')
                     except: return datetime.min
                 stock_logs.sort(key=lambda x: parse_log_date(x.get('date', '')), reverse=True)
            except Exception as e:
                 print(f"Error loading logs: {e}")

        except ValueError:
            flash('Data inválida.')
            return redirect(url_for('reports.reports'))

        # Carrega dados comuns se necessário
        all_stock_requests = load_stock_requests()
        all_stock_entries = load_stock_entries()
        products = load_products()

        # 1. Dados de Manutenção (Se Todos ou Manutenção)
        if department == 'Todos' or department == 'Manutenção':
            try:
                all_maint_requests = load_maintenance_requests()
                for req in all_maint_requests:
                    try:
                        req_date = datetime.strptime(req['date'], '%d/%m/%Y')
                        if d_start <= req_date <= d_end:
                            report_data.append({
                                'date': f"{req['date']} {req['time']}",
                                'user': req['user'],
                                'action': 'Solicitação de Manutenção',
                                'details': f"Local: {req['location']} - {req['description']} (Status: {req['status']})"
                            })
                    except ValueError: pass
            except Exception: pass

        # 2. Estoque (Pedidos e Consumo)
        requests_to_process = []
        if department == 'Todos' or department == 'Almoxarifado':
            requests_to_process = all_stock_requests
        elif department != 'Manutenção': # Departamentos específicos (Cozinha, etc)
            requests_to_process = [r for r in all_stock_requests if r.get('department') == department]

        # Processa pedidos para o Log e Consumo
        consumption_stats = {} # { product_name: total_qty }
        
        for req in requests_to_process:
            try:
                req_date = datetime.strptime(req['date'], '%d/%m/%Y')
                if d_start <= req_date <= d_end:
                    # Adiciona ao Log
                    penalty_text = " (COM MULTA)" if req.get('penalty') else ""
                    report_data.append({
                        'date': f"{req['date']} {req['time']}",
                        'user': f"{req['user']} ({req['department']})",
                        'action': f"Requisição {req['type']}",
                        'details': f"Itens: {req['items']}{penalty_text}"
                    })
                    
                    # Contabiliza Consumo
                    items_str = req['items']
                    # Formato esperado: "Item A (2), Item B (1)"
                    parts = items_str.split(',')
                    for part in parts:
                        part = part.strip()
                        if not part: continue
                        # Regex to capture "Name (Qty)"
                        match = re.match(r'(.+)\s+\((\d+(\.\d+)?)\)', part)
                        if match:
                            p_name = match.group(1).strip()
                            p_qty = float(match.group(2))
                            if p_name in consumption_stats:
                                consumption_stats[p_name] += p_qty
                            else:
                                consumption_stats[p_name] = p_qty
            except ValueError: pass

        # Analise de Consumo (Compara com Frequência Estimada)
        if consumption_stats:
             consumption_summary = []
             for p_name, total_qty in consumption_stats.items():
                 # Find product info
                 prod = next((p for p in products if p['name'] == p_name), None)
                 
                 avg_weekly = 0
                 alert = None
                 
                 if prod:
                     freq = prod.get('frequency', 'Semanal') # Default assumes usage is relevant
                     # Estimate average weekly usage based on frequency (Rough approximation)
                     # Na verdade, o sistema não tem 'consumo esperado' cadastrado, apenas 'frequencia de compra'.
                     # Então vamos apenas mostrar o total consumido no período.
                     pass
                 
                 # Calculate weekly average in this period
                 period_weekly_avg = total_qty / weeks_in_period
                 
                 consumption_summary.append({
                     'product': p_name,
                     'total': total_qty,
                     'weekly_avg': round(period_weekly_avg, 2),
                     'unit': prod.get('unit', '') if prod else ''
                 })
                 
             consumption_summary.sort(key=lambda x: x['total'], reverse=True)

        # 3. Compras (Entradas de Estoque)
        if department == 'Todos' or department == 'Almoxarifado' or department == 'Estoque':
             purchase_stats = {}
             total_spent = 0.0
             
             for entry in all_stock_entries:
                 try:
                     # Entry date format often 'DD/MM/YYYY' or 'DD/MM/YYYY HH:MM'
                     d_str = entry.get('date', '')
                     if len(d_str) > 10: d_str = d_str[:10]
                     entry_date = datetime.strptime(d_str, '%d/%m/%Y')
                     
                     if d_start <= entry_date <= d_end:
                         # Log
                         report_data.append({
                            'date': entry.get('date'),
                            'user': entry.get('user'),
                            'action': 'Entrada de Estoque',
                            'details': f"{entry.get('product')} (+{entry.get('qty')}) - {entry.get('supplier')} - R$ {entry.get('price')}"
                         })
                         
                         # Stats
                         p_name = entry.get('product')
                         cost = float(entry.get('price', 0)) * float(entry.get('qty', 0))
                         
                         if p_name in purchase_stats:
                             purchase_stats[p_name]['qty'] += float(entry.get('qty', 0))
                             purchase_stats[p_name]['cost'] += cost
                         else:
                             purchase_stats[p_name] = {
                                 'qty': float(entry.get('qty', 0)),
                                 'cost': cost
                             }
                         total_spent += cost
                 except ValueError: pass
                 
             if purchase_stats:
                 purchase_summary = []
                 for p, data in purchase_stats.items():
                     purchase_summary.append({
                         'product': p,
                         'qty': data['qty'],
                         'cost': data['cost']
                     })
                 purchase_summary.sort(key=lambda x: x['cost'], reverse=True)
                 purchase_summary = {'items': purchase_summary, 'total': total_spent}

    # Ordena relatório geral por data
    def parse_report_date(item):
        try:
            return datetime.strptime(item['date'], '%d/%m/%Y %H:%M')
        except:
            try:
                return datetime.strptime(item['date'], '%d/%m/%Y')
            except:
                return datetime.min
                
    report_data.sort(key=parse_report_date, reverse=True)
    
    return render_template('reports.html', 
                           report_data=report_data, 
                           stock_logs=stock_logs,
                           department=department, 
                           departments=DEPARTMENTS,
                           purchase_summary=purchase_summary,
                           consumption_summary=consumption_summary,
                           start_date=start_date,
                           end_date=end_date)

@reports_bp.route('/admin/invoice-report', methods=['GET'])
@login_required
def invoice_report():
    if session.get('role') not in ['admin', 'gerente', 'financeiro']:
        return "Acesso Negado", 403
        
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')
    
    if not start_date_str or not end_date_str:
        return "Datas obrigatórias", 400
        
    try:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
    except ValueError:
        return "Datas inválidas", 400
        
    # Collect Data
    entries = load_stock_entries()
    
    filtered = []
    total_value = 0.0
    
    for e in entries:
        try:
            d_str = e.get('date')
            if len(d_str) > 10: d_str = d_str[:10]
            d = datetime.strptime(d_str, '%d/%m/%Y')
            
            if start_date <= d <= end_date:
                total = float(e.get('price', 0)) * float(e.get('qty', 0))
                filtered.append({
                    'date': d_str,
                    'supplier': e.get('supplier'),
                    'invoice': e.get('invoice'),
                    'product': e.get('product'),
                    'qty': e.get('qty'),
                    'total': total
                })
                total_value += total
        except: pass
        
    filtered.sort(key=lambda x: datetime.strptime(x['date'], '%d/%m/%Y'))
    
    return render_template('invoice_report_print.html', 
                           entries=filtered, 
                           start_date=start_date.strftime('%d/%m/%Y'),
                           end_date=end_date.strftime('%d/%m/%Y'),
                           total_value=total_value)
