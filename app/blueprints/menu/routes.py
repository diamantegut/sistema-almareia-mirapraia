from flask import render_template, request, redirect, url_for, session, flash, jsonify, current_app
from . import menu_bp
from app.services.data_service import (
    load_menu_items, save_menu_items, load_settings, save_settings,
    load_flavor_groups, save_flavor_groups, load_products,
    load_table_orders, load_printers,
    PRODUCT_PHOTOS_DIR
)
from app.services.system_config_manager import get_data_path
from app.services.printing_service import print_system_notification
from app.services.logger_service import LoggerService
from app.services.security_service import check_sensitive_access
from app.utils.formatters import normalize_text, parse_br_currency
from app.utils.files import allowed_file
from app.utils.decorators import login_required
from .utils import rescue_menu_items_fiscal_from_excel
from werkzeug.utils import secure_filename
import os
from datetime import datetime
import traceback
import io
import xlsxwriter
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from app.services.data_service import load_sales_history
from app.services.system_config_manager import ACTION_LOGS_DIR, SALES_HISTORY_FILE
import os
from flask import send_file
import json
import unicodedata

# Simple cache for flattened sales
_SALES_CACHE = {'mtime': None, 'items': []}

def _parse_date_ddmmyyyy(s):
    try:
        return datetime.strptime(s, '%d/%m/%Y')
    except Exception:
        return None

def _format_sale_display_id(item):
    raw_id = str(item.get('sale_id') or '')
    status_str = str(item.get('status') or '').lower()
    if status_str == 'closed':
        prefix = 'VENDA-'
    elif status_str == 'cancelled':
        prefix = 'CANCEL-'
    else:
        prefix = ''
    return prefix + raw_id

def _norm_name(s):
    if not s:
        return ''
    s = s.strip().lower()
    return ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')

def _name_matches(name, norm_filters):
    if not norm_filters:
        return True
    n = _norm_name(name)
    for f in norm_filters:
        if not f:
            continue
        if n == f or n.startswith(f) or f in n:
            return True
    return False

def _get_sales_flat():
    try:
        mtime = os.path.getmtime(SALES_HISTORY_FILE)
    except Exception:
        mtime = None
    if _SALES_CACHE.get('mtime') == mtime and _SALES_CACHE.get('items'):
        return _SALES_CACHE['items']
    data = load_sales_history()
    items = []
    if isinstance(data, dict):
        data = list(data.values())
    for order in data or []:
        closed_at = order.get('closed_at')
        status = order.get('status', 'closed')
        close_id = order.get('close_id') or order.get('id') or ''
        customer = order.get('customer_name') or ''
        try:
            ts = datetime.strptime(closed_at, '%d/%m/%Y %H:%M') if closed_at else None
        except Exception:
            ts = None
        for it in order.get('items', []):
            try:
                qty = float(it.get('qty', 0) or 0)
            except Exception:
                qty = 0.0
            base_price = 0.0
            try:
                base_price = float(it.get('price', 0) or 0)
            except Exception:
                base_price = 0.0
            comps_total = 0.0
            for comp in it.get('complements', []) or []:
                try:
                    comps_total += float(comp.get('price', 0) or 0)
                except Exception:
                    pass
            total_val = qty * (base_price + comps_total)
            items.append({
                'sale_id': close_id,
                'product': it.get('name'),
                'product_id': it.get('product_id'),
                'qty': qty,
                'total': round(total_val, 2),
                'timestamp': ts,
                'timestamp_str': closed_at or '',
                'status': status,
                'customer': customer
            })
    _SALES_CACHE['mtime'] = mtime
    _SALES_CACHE['items'] = items
    return items

def _get_cancellations_from_logs(start_dt, end_dt, products_set):
    results = []
    try:
        if not os.path.isdir(ACTION_LOGS_DIR):
            return results
        norm_filters = set(_norm_name(p) for p in products_set) if products_set else set()
        for fname in os.listdir(ACTION_LOGS_DIR):
            if not fname.endswith('.json'):
                continue
            try:
                y, m, d = fname.replace('.json', '').split('-')
                day_dt = datetime(int(y), int(m), int(d))
            except Exception:
                continue
            if day_dt.date() < start_dt.date() or day_dt.date() > end_dt.date():
                continue
            path = os.path.join(ACTION_LOGS_DIR, fname)
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    logs = json.load(f)
            except Exception:
                logs = []
            for log in logs or []:
                if str(log.get('action', '')).lower() not in ['item removido', 'cancelamento mesa']:
                    continue
                ts_str = log.get('timestamp') or ''
                try:
                    ts = datetime.strptime(ts_str, '%d/%m/%Y %H:%M:%S')
                except Exception:
                    ts = day_dt
                details = log.get('details', '')
                prod_name = None
                if isinstance(details, str):
                    if 'Item ' in details and ' removido' in details:
                        try:
                            seg = details.split('Item ', 1)[1]
                            prod_name = seg.split(' removido', 1)[0].strip()
                        except Exception:
                            prod_name = None
                elif isinstance(details, dict):
                    prod_name = details.get('item') or details.get('name')
                if prod_name and (not products_set or _name_matches(prod_name, norm_filters)):
                    results.append({
                        'sale_id': f"CANCEL_{log.get('id','')}",
                        'product': prod_name,
                        'qty': 1.0,
                        'total': 0.0,
                        'timestamp': ts,
                        'timestamp_str': ts.strftime('%d/%m/%Y %H:%M:%S'),
                        'status': 'cancelled',
                        'customer': ''
                    })
    except Exception:
        pass
    return results

@menu_bp.route('/api/menu/sales-history')
@login_required
def menu_sales_history_api():
    user_role = session.get('role', '')
    allowed_roles = ['super', 'admin', 'gerente', 'recepcao', 'supervisor', 'diretor']
    if not any(role in user_role for role in allowed_roles):
        return jsonify({'success': False, 'error': 'Acesso negado'}), 403
    products_param = request.args.get('products', '')
    products = [p.strip() for p in products_param.split(',') if p.strip()]
    product_ids_param = request.args.get('product_ids', '')
    product_ids = [p.strip() for p in product_ids_param.split(',') if p.strip()]
    norm_prod_set = set(_norm_name(p) for p in products)
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    status = request.args.get('status', 'concluidas').lower()
    try:
        page = int(request.args.get('page', 1))
        page_size = int(request.args.get('page_size', 25))
    except Exception:
        page, page_size = 1, 25
    if page_size not in [10, 25, 50, 100]:
        page_size = 25
    now = datetime.now()
    sdt = _parse_date_ddmmyyyy(start_date) if start_date else None
    edt = _parse_date_ddmmyyyy(end_date) if end_date else None
    if sdt and sdt.date() > now.date():
        return jsonify({'success': False, 'error': 'Data inicial no futuro'}), 400
    if edt and edt.date() > now.date():
        return jsonify({'success': False, 'error': 'Data final no futuro'}), 400
    if sdt and edt and sdt > edt:
        return jsonify({'success': False, 'error': 'Data inicial maior que a final'}), 400
    all_items = _get_sales_flat()
    prod_set = set(products)
    prod_id_set = set(product_ids)
    filtered = []
    for it in all_items:
        if prod_id_set:
            pid = (it.get('product_id') or '')
            if pid in prod_id_set:
                pass
            elif prod_set and _name_matches(it['product'], norm_prod_set):
                pass
            else:
                continue
        elif products:
            if not _name_matches(it['product'], norm_prod_set):
                continue
        if sdt and it['timestamp'] and it['timestamp'] < sdt:
            continue
        if edt and it['timestamp'] and it['timestamp'] > (edt.replace(hour=23, minute=59, second=59)):
            continue
        if status in ['concluidas', 'concluídas'] and str(it['status']).lower() != 'closed':
            continue
        filtered.append(it)
    if status == 'canceladas':
        s = sdt or datetime.min
        e = edt or datetime.max
        canc = _get_cancellations_from_logs(s, e, prod_set)
        filtered = canc
    elif status == 'todas':
        s = sdt or datetime.min
        e = edt or datetime.max
        canc = _get_cancellations_from_logs(s, e, prod_set)
        filtered = filtered + canc
        filtered.sort(key=lambda x: x['timestamp'] or datetime.min)
    total_count = len(filtered)
    start_idx = max(0, (page - 1) * page_size)
    end_idx = start_idx + page_size
    page_items = filtered[start_idx:end_idx]
    total_qty = sum(it['qty'] for it in filtered if str(it['status']).lower() == 'closed')
    cancelled_qty = sum(1 for it in filtered if str(it['status']).lower() == 'cancelled')
    net_qty = total_qty - cancelled_qty
    total_value = round(sum(it['total'] for it in filtered if str(it['status']).lower() == 'closed'), 2)
    return jsonify({
        'success': True,
        'items': [
            {
                'sale_id': _format_sale_display_id(it),
                'product': it['product'],
                'qty': it['qty'],
                'total': it['total'],
                'timestamp': it['timestamp_str'],
                'status': 'concluída' if str(it['status']).lower() == 'closed' else 'cancelada',
                'customer': it['customer']
            } for it in page_items
        ],
        'total_count': total_count,
        'summary': {
            'total_vendida': total_qty,
            'total_cancelada': cancelled_qty,
            'quantidade_liquida': net_qty,
            'valor_total': total_value
        }
    })

@menu_bp.route('/menu/sales-history/export')
@login_required
def menu_sales_history_export():
    user_role = session.get('role', '')
    allowed_roles = ['super', 'admin', 'gerente', 'recepcao', 'supervisor', 'diretor']
    if not any(role in user_role for role in allowed_roles):
        return jsonify({'success': False, 'error': 'Acesso negado'}), 403
    products_param = request.args.get('products', '')
    products = [p.strip() for p in products_param.split(',') if p.strip()]
    product_ids_param = request.args.get('product_ids', '')
    product_ids = [p.strip() for p in product_ids_param.split(',') if p.strip()]
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    status = request.args.get('status', 'concluidas').lower()
    fmt = request.args.get('format', 'xlsx').lower()
    now = datetime.now()
    sdt = _parse_date_ddmmyyyy(start_date) if start_date else None
    edt = _parse_date_ddmmyyyy(end_date) if end_date else None
    if sdt and sdt.date() > now.date():
        return jsonify({'success': False, 'error': 'Data inicial no futuro'}), 400
    if edt and edt.date() > now.date():
        return jsonify({'success': False, 'error': 'Data final no futuro'}), 400
    if sdt and edt and sdt > edt:
        return jsonify({'success': False, 'error': 'Data inicial maior que a final'}), 400
    items = []
    all_items = _get_sales_flat()
    prod_set = set(products)
    norm_prod_set = set(_norm_name(p) for p in products)
    prod_id_set = set(product_ids)
    for it in all_items:
        if prod_id_set:
            pid = (it.get('product_id') or '')
            if pid in prod_id_set:
                pass
            elif prod_set and _name_matches(it['product'], norm_prod_set):
                pass
            else:
                continue
        elif products:
            if not _name_matches(it['product'], norm_prod_set):
                continue
        if sdt and it['timestamp'] and it['timestamp'] < sdt:
            continue
        if edt and it['timestamp'] and it['timestamp'] > (edt.replace(hour=23, minute=59, second=59)):
            continue
        if status in ['concluidas', 'concluídas'] and str(it['status']).lower() != 'closed':
            continue
        items.append(it)
    if status == 'canceladas' or status == 'todas':
        s = sdt or datetime.min
        e = edt or datetime.max
        canc = _get_cancellations_from_logs(s, e, prod_set)
        if status == 'canceladas':
            items = canc
        else:
            items = items + canc
            items.sort(key=lambda x: x['timestamp'] or datetime.min)
    total_qty = sum(it['qty'] for it in items if str(it['status']).lower() == 'closed')
    cancelled_qty = sum(1 for it in items if str(it['status']).lower() == 'cancelled')
    net_qty = total_qty - cancelled_qty
    total_value = round(sum(it['total'] for it in items if str(it['status']).lower() == 'closed'), 2)
    if fmt == 'pdf':
        output = io.BytesIO()
        c = canvas.Canvas(output, pagesize=A4)
        width, height = A4
        y = height - 20*mm
        title = "Histórico de Vendas"
        c.setFont("Helvetica-Bold", 14)
        c.drawString(20*mm, y, title)
        y -= 10*mm
        c.setFont("Helvetica", 10)
        c.drawString(20*mm, y, f"Período: {start_date or '-'} a {end_date or '-'}  Status: {status}")
        y -= 8*mm
        c.drawString(20*mm, y, f"Produtos: {', '.join(products) if products else 'Todos'}")
        y -= 10*mm
        c.setFont("Helvetica-Bold", 10)
        c.drawString(20*mm, y, "ID")
        c.drawString(60*mm, y, "Produto")
        c.drawString(120*mm, y, "Qtde")
        c.drawString(140*mm, y, "Valor")
        c.drawString(165*mm, y, "Data/Hora")
        y -= 6*mm
        c.setFont("Helvetica", 10)
        for it in items:
            display_id = _format_sale_display_id(it)
            if y < 20*mm:
                c.showPage()
                y = height - 20*mm
            c.drawString(20*mm, y, str(display_id)[:18])
            c.drawString(60*mm, y, (it['product'] or '')[:25])
            c.drawRightString(135*mm, y, f"{it['qty']:.2f}")
            c.drawRightString(160*mm, y, f"R$ {it['total']:.2f}")
            c.drawString(165*mm, y, it.get('timestamp_str') or '')
            y -= 6*mm
        y -= 6*mm
        c.setFont("Helvetica-Bold", 10)
        c.drawString(20*mm, y, f"Total vendida: {total_qty:.2f}  Cancelada: {cancelled_qty:.2f}  Líquida: {net_qty:.2f}  Valor total: R$ {total_value:.2f}")
        c.save()
        output.seek(0)
        filename = f"historico_vendas_{datetime.now().strftime('%Y%m%d%H%M%S')}.pdf"
        return send_file(output, download_name=filename, as_attachment=True)
    output = io.BytesIO()
    wb = xlsxwriter.Workbook(output)
    ws = wb.add_worksheet('Vendas')
    bold = wb.add_format({'bold': True})
    money = wb.add_format({'num_format': 'R$ #,##0.00'})
    headers = ['ID', 'Produto', 'Quantidade', 'Valor', 'Data/Hora', 'Status', 'Cliente']
    for col, h in enumerate(headers):
        ws.write(0, col, h, bold)
    row = 1
    for it in items:
        display_id = _format_sale_display_id(it)
        ws.write(row, 0, display_id)
        ws.write(row, 1, it['product'])
        ws.write_number(row, 2, it['qty'])
        ws.write_number(row, 3, it['total'], money)
        ws.write(row, 4, it.get('timestamp_str') or '')
        ws.write(row, 5, 'concluída' if str(it['status']).lower() == 'closed' else 'cancelada')
        ws.write(row, 6, it.get('customer') or '')
        row += 1
    ws2 = wb.add_worksheet('Resumo')
    ws2.write(0, 0, 'Total vendida', bold)
    ws2.write(0, 1, total_qty)
    ws2.write(1, 0, 'Total cancelada', bold)
    ws2.write(1, 1, cancelled_qty)
    ws2.write(2, 0, 'Quantidade líquida', bold)
    ws2.write(2, 1, net_qty)
    ws2.write(3, 0, 'Valor total', bold)
    ws2.write_number(3, 1, total_value, money)
    wb.close()
    output.seek(0)
    filename = f"historico_vendas_{datetime.now().strftime('%Y%m%d%H%M%S')}.xlsx"
    return send_file(output, download_name=filename, as_attachment=True)

@menu_bp.route('/menu/sales-history')
@login_required
def menu_sales_history_page():
    user_role = session.get('role', '')
    allowed_roles = ['super', 'admin', 'gerente', 'recepcao', 'supervisor', 'diretor']
    if not any(role in user_role for role in allowed_roles):
        return redirect(url_for('main.index'))
    # Reuse menu items to populate product selector
    try:
        items = load_menu_items()
    except Exception:
        items = []
    return render_template('menu_sales_history.html', menu_items=items)
@menu_bp.route('/api/menu/digital-category-order', methods=['POST'])
@login_required
def save_digital_menu_order():
    user_role = session.get('role')
    user_perms = session.get('permissions', [])
    
    # Allow if role is authorized OR if user has specific permissions
    if user_role not in ['super', 'admin', 'gerente', 'recepcao', 'supervisor'] and \
       'restaurante_full_access' not in user_perms and \
       'recepcao' not in user_perms:
        return jsonify({'success': False, 'error': 'Acesso negado'}), 403
        
    try:
        data = request.get_json()
        order = data.get('order', [])
        
        settings = load_settings()
        settings['digital_menu_category_order'] = order
        save_settings(settings)
        
        return jsonify({'success': True})
    except Exception as e:
        current_app.logger.error(f"Error saving digital menu order: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@menu_bp.route('/api/public/products/paused')
def get_public_paused_products():
    """Returns a list of IDs of paused products (Public access)."""
    menu_items = load_menu_items()
    def _boolish(v):
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v.strip().lower() in ('true','on','1','checked','paused','yes')
        if isinstance(v, int):
            return v != 0
        return False
    paused_ids = [str(p.get('id')) for p in menu_items if _boolish(p.get('paused', False))]
    return jsonify({'paused_ids': paused_ids})

@menu_bp.route('/cardapio')
def client_menu():
    menu_items = load_menu_items()
    def _boolish(v):
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v.strip().lower() in ('true','on','1','checked','paused','yes')
        if isinstance(v, int):
            return v != 0
        return False
    visible_items = []
    for i in menu_items:
        if i.get('active', True) and i.get('visible_virtual_menu', True) and not _boolish(i.get('paused', False)):
            visible_items.append(i)
    
    # Separate Breakfast items
    breakfast_items = []
    other_items = []
    
    for item in visible_items:
        # Check if category is "Café da Manhã" (normalized)
        cat_norm = normalize_text(item.get('category', ''))
        if 'cafe da manha' in cat_norm:
            breakfast_items.append(item)
        else:
            other_items.append(item)
    
    # New Sorting Logic
    all_categories = sorted(list(set(i['category'] for i in other_items)))
    
    settings = load_settings()
    custom_order = settings.get('digital_menu_category_order', [])
    
    # Create a map for order index
    order_map = {cat: i for i, cat in enumerate(custom_order)}
    
    # Sort: First by custom order index (if exists), then alphabetical
    # Items not in custom_order will have index infinity (float('inf')) so they go to end
    categories = sorted(all_categories, key=lambda x: (order_map.get(x, float('inf')), x))
    
    grouped = {cat: [] for cat in categories}
    
    for item in other_items:
        grouped[item['category']].append(item)
        
    # Sort items within each category: Highlighted first, then by Name
    for cat in grouped:
        grouped[cat].sort(key=lambda x: (not x.get('highlight', False), x.get('name', '')))
        
    # Sort breakfast items: Highlighted first, then by Name
    breakfast_items.sort(key=lambda x: (not x.get('highlight', False), x.get('name', '')))
    
    # Breakfast Time Logic (08:00 - 11:00)
    now = datetime.now()
    is_breakfast_time = 8 <= now.hour < 11
    
    if not is_breakfast_time:
        breakfast_items = [] # Hide breakfast items outside hours
        
    return render_template('mirapraia_menu.html', 
                          menu_items_grouped=grouped, 
                          categories=categories,
                          breakfast_items=breakfast_items,
                          is_breakfast_time=is_breakfast_time)

@menu_bp.route('/cardapio/preview')
def client_menu_preview():
    # Duplicated logic for preview
    menu_items = load_menu_items()
    def _boolish(v):
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v.strip().lower() in ('true','on','1','checked','paused','yes')
        if isinstance(v, int):
            return v != 0
        return False
    visible_items = []
    for i in menu_items:
        if i.get('active', True) and i.get('visible_virtual_menu', True) and not _boolish(i.get('paused', False)):
            visible_items.append(i)
    
    # Separate Breakfast items
    breakfast_items = []
    other_items = []
    
    for item in visible_items:
        # Check if category is "Café da Manhã" (normalized)
        cat_norm = normalize_text(item.get('category', ''))
        if 'cafe da manha' in cat_norm:
            breakfast_items.append(item)
        else:
            other_items.append(item)
    
    # New Sorting Logic
    all_categories = sorted(list(set(i['category'] for i in other_items)))
    
    settings = load_settings()
    custom_order = settings.get('digital_menu_category_order', [])
    
    # Create a map for order index
    order_map = {cat: i for i, cat in enumerate(custom_order)}
    
    # Sort: First by custom order index (if exists), then alphabetical
    # Items not in custom_order will have index infinity (float('inf')) so they go to end
    categories = sorted(all_categories, key=lambda x: (order_map.get(x, float('inf')), x))
    
    grouped = {cat: [] for cat in categories}
    
    for item in other_items:
        grouped[item['category']].append(item)
        
    # Sort items within each category: Highlighted first, then by Name
    for cat in grouped:
        grouped[cat].sort(key=lambda x: (not x.get('highlight', False), x.get('name', '')))
        
    # Sort breakfast items: Highlighted first, then by Name
    breakfast_items.sort(key=lambda x: (not x.get('highlight', False), x.get('name', '')))
    
    # Breakfast Time Logic (08:00 - 11:00)
    now = datetime.now()
    is_breakfast_time = 8 <= now.hour < 11
    
    if not is_breakfast_time:
        breakfast_items = [] # Hide breakfast items outside hours
        
    return render_template('mirapraia_menu_preview.html', 
                          menu_items_grouped=grouped, 
                          categories=categories,
                          breakfast_items=breakfast_items,
                          is_breakfast_time=is_breakfast_time)

@menu_bp.route('/menu_showcase')
def menu_showcase():
    menu_items = load_menu_items()
    # Filter active items and items visible in virtual menu
    active_items = [i for i in menu_items if i.get('active', True) and i.get('visible_virtual_menu', True)]
    
    # Group by category
    categories = sorted(list(set(i['category'] for i in active_items)))
    grouped = {cat: [] for cat in categories}
    
    for item in active_items:
        grouped[item['category']].append(item)
        
    return render_template('menu_showcase.html', menu_items_grouped=grouped, categories=categories)

@menu_bp.route('/admin/api/menu_items/fiscal/rescue', methods=['POST'])
@login_required
def admin_rescue_menu_items_fiscal():
    if session.get('role') not in ['super', 'admin', 'gerente', 'supervisor']:
        return jsonify({'success': False, 'error': 'Acesso negado.'}), 403

    data = request.get_json(silent=True) or {}
    excel_paths = data.get('excel_paths')
    if not excel_paths:
        excel_paths = [
            get_data_path("PRODUTOS (250).xlsx"),
            get_data_path("PRODUTOS POR TAMANHO (27).xlsx")
        ]

    try:
        return jsonify(rescue_menu_items_fiscal_from_excel(excel_paths))
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@menu_bp.route('/menu/management', methods=['GET', 'POST'])
@login_required
def menu_management():
    current_app.logger.debug(f"Entering menu_management. User: {session.get('user_id')}, Role: {session.get('role')}")
    
    user_role = session.get('role')
    user_perms = session.get('permissions', [])
    
    # Allow if role is authorized OR if user has specific permissions
    # 'restaurante_full_access' covers service collaborators
    # 'recepcao' covers reception staff who might have 'colaborador' role
    if user_role not in ['super', 'admin', 'gerente', 'recepcao', 'supervisor'] and \
       'restaurante_full_access' not in user_perms and \
       'recepcao' not in user_perms:
         flash('Acesso restrito.')
         return redirect(url_for('main.index'))
         
    if request.method == 'POST':
        current_app.logger.info("Processing menu_management POST request")
        try:
            # Security Check: Sensitive Access
            current_user = session.get('user', 'Sistema')
            item_name_log = request.form.get('name', 'Unknown')
            
            current_app.logger.info(f"POST Data: Name={item_name_log}, User={current_user}")
            
            # --- DEBUG LOGGING START ---
            try:
                with open('debug_product_save.txt', 'w', encoding='utf-8') as f:
                    f.write("--- DEBUG FORM DATA ---\n")
                    f.write(f"POST Data: Name={item_name_log}, User={current_user}\n")
                    for key in request.form:
                        if key not in ['image', 'video_file']:
                            f.write(f"Key: {key}, Value: {request.form.getlist(key)}\n")
                    f.write("--- DEBUG END ---\n")
            except Exception as e:
                current_app.logger.error(f"Failed to write debug log: {e}")

            check_sensitive_access(
                action="Alteração de Menu",
                user=current_user,
                details=f"Tentativa de alteração/criação do produto: {item_name_log}"
            )

            menu_items = load_menu_items()
            
            should_print = request.form.get('should_print') == 'on'
            item_id = request.form.get('id')
            
            # Determine Target ID (for Image Naming and Saving)
            target_id = item_id
            is_new_product = False
            
            if not target_id:
                is_new_product = True
                # Generate new ID
                target_id = str(len(menu_items) + 1)
                while any(i['id'] == target_id for i in menu_items):
                    target_id = str(int(target_id) + 1)
            
            name = request.form.get('name')
            category = request.form.get('category')
            price = parse_br_currency(request.form.get('price'))
            printer_id = request.form.get('printer_id')
            
            # Auto-assign printer from category if missing
            if not printer_id and category:
                current_app.logger.debug(f"No printer selected for {name} (Category: {category}). Searching for default...")
                for item in menu_items:
                    # Skip self if editing
                    if not is_new_product and item.get('id') == item_id:
                        continue
                        
                    if item.get('category') == category and item.get('printer_id'):
                        printer_id = item.get('printer_id')
                        current_app.logger.debug(f"Inherited printer {printer_id} from category {category} (Source: {item.get('name')})")
                        break
            
            if printer_id is None:
                printer_id = ""
            
            current_app.logger.debug(f"Saving Product ID={target_id} (New: {is_new_product}) | Printer={printer_id} | ShouldPrint={should_print}")
            description = request.form.get('description')
            
            # Image Upload
            image_filename = request.form.get('current_image') # Keep existing if no new upload
            if 'image' in request.files:
                file = request.files['image']
                if file and file.filename != '' and allowed_file(file.filename):
                    filename = secure_filename(f"{target_id}_{file.filename}") # Prefix with ID to avoid conflicts
                    
                    # Ensure products upload directory exists
                    os.makedirs(PRODUCT_PHOTOS_DIR, exist_ok=True)
                    
                    file.save(os.path.join(PRODUCT_PHOTOS_DIR, filename))
                    image_filename = filename

            # Video Upload (WebM)
            video_filename = request.form.get('current_video') # Keep existing if no new upload
            if 'video_file' in request.files:
                vfile = request.files['video_file']
                if vfile and vfile.filename != '' and vfile.filename.lower().endswith('.webm'):
                    vfilename = secure_filename(f"{target_id}_{vfile.filename}")
                    
                    # Ensure products upload directory exists
                    os.makedirs(PRODUCT_PHOTOS_DIR, exist_ok=True)
                    
                    vfile.save(os.path.join(PRODUCT_PHOTOS_DIR, vfilename))
                    video_filename = vfilename

            # Additional Fields
            product_type = request.form.get('product_type', 'standard')
            has_accompaniments = request.form.get('has_accompaniments') == 'on'
            allowed_accompaniments = request.form.getlist('allowed_accompaniments')
            
            cost_price = parse_br_currency(request.form.get('cost_price'))
                
            service_fee_exempt = request.form.get('service_fee_exempt') == 'on'
            visible_virtual_menu = request.form.get('visible_virtual_menu') == 'on'
            highlight = request.form.get('highlight') == 'on'
            active = request.form.get('active') == 'on'

            # Pause Info
            paused = request.form.get('paused') == 'on'
            pause_reason = request.form.get('pause_reason')
            pause_start = request.form.get('pause_start')
            pause_end = request.form.get('pause_end')
            
            current_user = session.get('username', 'Admin')

            # Flavor Group Info
            flavor_group_id = request.form.get('flavor_group_id')
            try:
                # Robust float parsing for multiplier (comma/dot)
                raw_mult = request.form.get('flavor_multiplier', '1.0')
                if isinstance(raw_mult, str):
                    raw_mult = raw_mult.replace(',', '.')
                flavor_multiplier = float(raw_mult)
            except ValueError:
                flavor_multiplier = 1.0

            # Fiscal Info
            ncm = request.form.get('ncm')
            cest = request.form.get('cest')
            # Helper for float parsing
            def parse_float_safe(val):
                if not val: return 0.0
                try:
                    return float(str(val).replace(',', '.'))
                except ValueError:
                    return 0.0

            transparency_tax = parse_float_safe(request.form.get('transparency_tax'))
            fiscal_benefit_code = request.form.get('fiscal_benefit_code')
            
            cfop = request.form.get('cfop')
            origin = request.form.get('origin')
            tax_situation = request.form.get('tax_situation')
            icms_rate = parse_float_safe(request.form.get('icms_rate'))
            icms_base_reduction = parse_float_safe(request.form.get('icms_base_reduction'))
            fcp_rate = parse_float_safe(request.form.get('fcp_rate'))
            
            pis_cst = request.form.get('pis_cst')
            pis_rate = parse_float_safe(request.form.get('pis_rate'))
            cofins_cst = request.form.get('cofins_cst')
            cofins_rate = parse_float_safe(request.form.get('cofins_rate'))
            
            # Recipe
            ingredient_ids = request.form.getlist('ingredient_id[]')
            ingredient_qtys = request.form.getlist('ingredient_qty[]')
            
            current_app.logger.info(f"Received Ingredients: IDs={ingredient_ids}, Qtys={ingredient_qtys}")

            recipe = []
            for i in range(len(ingredient_ids)):
                if ingredient_ids[i] and ingredient_qtys[i]:
                    try:
                        qty = float(ingredient_qtys[i])
                        if qty > 0:
                            recipe.append({
                                'ingredient_id': ingredient_ids[i],
                                'qty': qty
                            })
                    except ValueError:
                        pass
            
            # Mandatory Questions
            question_texts = request.form.getlist('question_text[]')
            question_types = request.form.getlist('question_type[]')
            question_options = request.form.getlist('question_options[]')
            question_required = request.form.getlist('question_required[]')
            
            current_app.logger.info(f"Received Questions: {question_texts}")

            mandatory_questions = []
            for i in range(len(question_texts)):
                if question_texts[i]:
                    options = []
                    if question_options[i]:
                        options = [opt.strip() for opt in question_options[i].split(',')]
                    
                    mandatory_questions.append({
                        'question': question_texts[i],
                        'type': question_types[i],
                        'options': options,
                        'required': question_required[i] == 'true'
                    })
            
            if mandatory_questions:
                try:
                    LoggerService.log_acao(
                        acao='Perguntas Produto',
                        entidade='Restaurante',
                        detalhes=f'Produto {name}: {len(mandatory_questions)} perguntas obrigatórias configuradas.',
                        colaborador_id=current_user
                    )
                except Exception:
                    pass

            # Validations
            if item_id:
                # 1. Check for active orders preventing edit/pause
                active_orders = load_table_orders()
                is_active_in_orders = False
                affected_tables = []
                
                for table_num, order_data in active_orders.items():
                    if order_data.get('status') == 'open':
                        # Check confirmed items
                        for order_item in order_data.get('items', []):
                            if str(order_item.get('id')) == str(item_id):
                                is_active_in_orders = True
                                affected_tables.append(table_num)
                                break
                        # Check pending items (if any)
                        if not is_active_in_orders: # optimization
                             for pending_item in order_data.get('pending_items', []):
                                if str(pending_item.get('id')) == str(item_id):
                                    is_active_in_orders = True
                                    affected_tables.append(table_num)
                                    break
                    if is_active_in_orders and len(affected_tables) > 3: # Limit detailed check
                        break
                
                if is_active_in_orders:
                    flash(f'Não é possível editar/pausar este item pois ele está em pedidos ativos nas mesas: {", ".join(affected_tables[:3])}...')
                    return redirect(url_for('menu.menu_management'))

                # 2. Check max paused items limit (if pausing)
                if paused:
                    current_paused_count = sum(1 for i in menu_items if i.get('paused') and str(i.get('id')) != str(item_id))
                    MAX_PAUSED_ITEMS = 15 # Reasonable limit
                    if current_paused_count >= MAX_PAUSED_ITEMS:
                         flash(f'Limite de itens pausados atingido ({MAX_PAUSED_ITEMS}). Reative outros itens antes de pausar este.')
                         return redirect(url_for('menu.menu_management'))
            
            found_for_update = False
            if not is_new_product:
                for item in menu_items:
                    # Compare IDs as strings to be safe
                    if str(item.get('id')) == str(target_id):
                        found_for_update = True
                        
                        # Capture original state for history logging
                        original_state = item.copy()
                        
                        item['name'] = name
                        item['category'] = category
                        item['price'] = price
                        item['cost_price'] = cost_price
                        item['printer_id'] = printer_id
                        item['should_print'] = should_print
                        item['description'] = description
                        item['image'] = image_filename
                        # Fix Image URL for Edit
                        if image_filename:
                             if image_filename.startswith('/') or 'http' in image_filename:
                                 item['image_url'] = image_filename
                             else:
                                 item['image_url'] = f"/Produtos/Fotos/{image_filename}"
                        else:
                             item['image_url'] = ""

                        item['service_fee_exempt'] = service_fee_exempt
                        item['visible_virtual_menu'] = visible_virtual_menu
                        item['highlight'] = highlight
                        item['active'] = active
                        item['recipe'] = recipe
                        item['mandatory_questions'] = mandatory_questions
                        item['flavor_group_id'] = flavor_group_id
                        item['flavor_multiplier'] = flavor_multiplier
                        item['product_type'] = product_type
                        item['has_accompaniments'] = has_accompaniments
                        item['allowed_accompaniments'] = allowed_accompaniments
                        item['ncm'] = ncm
                        item['cest'] = cest
                        item['transparency_tax'] = transparency_tax
                        item['fiscal_benefit_code'] = fiscal_benefit_code
                        item['cfop'] = cfop
                        item['origin'] = origin
                        item['tax_situation'] = tax_situation
                        item['icms_rate'] = icms_rate
                        item['icms_base_reduction'] = icms_base_reduction
                        item['fcp_rate'] = fcp_rate
                        item['pis_cst'] = pis_cst
                        item['pis_rate'] = pis_rate
                        item['cofins_cst'] = cofins_cst
                        item['cofins_rate'] = cofins_rate
                        
                        # Calculate changes for history logging
                        changes = []
                        fields_to_track = {
                            'name': 'Nome',
                            'category': 'Categoria',
                            'price': 'Preço',
                            'cost_price': 'Custo',
                            'printer_id': 'Impressora',
                            'active': 'Ativo',
                            'paused': 'Pausado',
                            'description': 'Descrição'
                        }
                        
                        for field, label in fields_to_track.items():
                            old_val = original_state.get(field)
                            new_val = item.get(field)
                            # Handle potential type mismatches (e.g., None vs "")
                            if str(old_val if old_val is not None else "") != str(new_val if new_val is not None else ""):
                                changes.append(f"{label}: {old_val} -> {new_val}")

                        # Log Pause Change
                        if item.get('paused') != paused:
                            action_type = "PAUSADO" if paused else "RETOMADO"
                            LoggerService.log_acao(
                                acao='Cardápio',
                                entidade='Restaurante',
                                detalhes=f"Produto {name} {action_type}. Motivo: {pause_reason}",
                                colaborador_id=current_user
                            )
                            
                            # Notify Kitchen/Bar via Printer
                            try:
                                printers = load_printers()
                                # Find printer for this item
                                target_printer = next((p for p in printers if p['id'] == printer_id), None)
                                
                                if target_printer:
                                    title = f"ITEM {action_type}"
                                    msg = f"O produto '{name}' foi {action_type.lower()} pela recepção.\nMotivo: {pause_reason or 'Não informado'}"
                                    
                                    is_win = target_printer.get('type') == 'windows'
                                    win_name = target_printer.get('windows_name')
                                    
                                    print_system_notification(
                                        target_printer.get('ip'), 
                                        title, 
                                        msg, 
                                        printer_port=target_printer.get('port', 9100),
                                        is_windows=is_win,
                                        windows_name=win_name
                                    )
                            except Exception as e:
                                print(f"Error printing pause notification: {e}")
                        
                        item['paused'] = paused
                        item['pause_reason'] = pause_reason
                        item['pause_start'] = pause_start
                        item['pause_end'] = pause_end
                        
                        break
            
            if not found_for_update:
                # Add new product
                new_item = {
                    'id': target_id,
                    'name': name,
                    'category': category,
                    'price': price,
                    'cost_price': cost_price,
                    'printer_id': printer_id,
                    'should_print': should_print,
                    'description': description,
                    'image': image_filename,
                    'image_url': f"/Produtos/Fotos/{image_filename}" if image_filename else "",
                    'service_fee_exempt': service_fee_exempt,
                    'visible_virtual_menu': visible_virtual_menu,
                    'highlight': highlight,
                    'active': active,
                    'recipe': recipe,
                    'mandatory_questions': mandatory_questions,
                    'flavor_group_id': flavor_group_id,
                    'flavor_multiplier': flavor_multiplier,
                    'product_type': product_type,
                    'has_accompaniments': has_accompaniments,
                    'allowed_accompaniments': allowed_accompaniments,
                    # Fiscal
                    'ncm': ncm,
                    'cest': cest,
                    'transparency_tax': transparency_tax,
                    'fiscal_benefit_code': fiscal_benefit_code,
                    'cfop': cfop,
                    'origin': origin,
                    'tax_situation': tax_situation,
                    'icms_rate': icms_rate,
                    'icms_base_reduction': icms_base_reduction,
                    'fcp_rate': fcp_rate,
                    'pis_cst': pis_cst,
                    'pis_rate': pis_rate,
                    'cofins_cst': cofins_cst,
                    'cofins_rate': cofins_rate,
                    'paused': paused,
                    'pause_reason': pause_reason
                }
                menu_items.append(new_item)
                
                LoggerService.log_acao(
                    acao='Cardápio Criado',
                    entidade='Cardápio',
                    detalhes={'id': target_id, 'name': name, 'message': f'Produto "{name}" adicionado.'},
                    colaborador_id=current_user
                )

            save_menu_items(menu_items)
            
            # Log Changes for History
            if not is_new_product and changes:
                LoggerService.log_acao(
                    acao='Cardápio Alterado',
                    entidade='Cardápio',
                    detalhes={'id': item_id, 'name': name, 'changes': changes},
                    colaborador_id=current_user
                )

            flash('Produto salvo com sucesso!')
            return_url = request.form.get('return_url')
            if return_url:
                return redirect(return_url)
            return redirect(url_for('menu.menu_management'))
            
        except Exception as e:
            current_app.logger.error(f"Error saving product: {e}")
            current_app.logger.error(traceback.format_exc())
            flash(f'Erro ao salvar produto: {e}')
            return_url = request.form.get('return_url')
            if return_url:
                return redirect(return_url)
            return redirect(url_for('menu.menu_management'))

    # GET Request
    try:
        menu_items = load_menu_items()
        printers = load_printers()
        
        # Sort categories
        all_categories = sorted(list(set(i['category'] for i in menu_items if i.get('category'))))
        categories = all_categories
        
        # Sort items
        menu_items.sort(key=lambda x: (x.get('category', ''), x.get('name', '')))
        
        insumos = load_products()
        insumos.sort(key=lambda x: x['name'])
        
        flavor_groups = load_flavor_groups()
        
        # Add stats
        total_items = len(menu_items)
        active_items = sum(1 for i in menu_items if i.get('active', True))

        # Digital Menu Categories (Sorted)
        settings = load_settings()
        custom_order = settings.get('digital_menu_category_order', [])
        order_map = {cat: i for i, cat in enumerate(custom_order)}
        digital_categories = sorted(all_categories, key=lambda x: (order_map.get(x, float('inf')), x))
        
        return render_template('menu_management.html', 
                              menu_items=menu_items, 
                              printers=printers, 
                              categories=categories,
                              insumos=insumos,
                              flavor_groups=flavor_groups,
                              total_items=total_items,
                              active_items=active_items,
                              digital_categories=digital_categories)
    except Exception as e:
        current_app.logger.error(f"Error rendering menu management: {e}")
        current_app.logger.error(traceback.format_exc())
        flash(f'Erro ao carregar página: {e}')
        return redirect(url_for('main.index'))

@menu_bp.route('/config/categories', methods=['GET', 'POST'])
@login_required
def config_categories():
    user_role = session.get('role')
    user_perms = session.get('permissions', [])
    
    if user_role not in ['super', 'admin', 'gerente', 'recepcao', 'supervisor'] and \
       'restaurante_full_access' not in user_perms and \
       'recepcao' not in user_perms:
        flash('Acesso restrito.')
        return redirect(url_for('menu.menu_management'))
    
    if request.method == 'POST':
        try:
            data = request.get_json()
            new_order = data.get('order', [])
            new_colors = data.get('colors', {})
            
            settings = load_settings()
            settings['category_order'] = new_order
            if new_colors:
                settings['category_colors'] = new_colors
                
            save_settings(settings)
            return jsonify({'success': True})
        except Exception as e:
            print(f"Error saving category order: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    menu_items = load_menu_items()
    all_categories = sorted(list(set(i['category'] for i in menu_items if i.get('category'))))
    settings = load_settings()
    saved_order = settings.get('category_order', [])
    saved_colors = settings.get('category_colors', {})
    
    # Merge saved order with any new categories found
    final_list = []
    # First add saved ones if they still exist in current menu
    for cat in saved_order:
        if cat in all_categories:
            final_list.append(cat)
    
    # Then add any remaining ones (newly created or not yet ordered)
    for cat in all_categories:
        if cat not in final_list:
            final_list.append(cat)
            
    return render_template('category_config.html', categories=final_list, category_colors=saved_colors)

@menu_bp.route('/menu/delete/<item_id>', methods=['POST'])
@login_required
def delete_menu_item(item_id):
    user_role = session.get('role')
    user_perms = session.get('permissions', [])
    
    if user_role not in ['super', 'admin', 'gerente', 'recepcao', 'supervisor'] and \
       'restaurante_full_access' not in user_perms and \
       'recepcao' not in user_perms:
        flash('Acesso restrito.')
        return redirect(url_for('main.index'))
        
    menu_items = load_menu_items()
    # Get name for logging
    item_name = next((i['name'] for i in menu_items if i.get('id') == item_id), 'Desconhecido')
    
    menu_items = [i for i in menu_items if i.get('id') != item_id]
    save_menu_items(menu_items)
    
    LoggerService.log_acao(
        acao='Cardápio Excluído',
        entidade='Cardápio',
        detalhes={'id': item_id, 'name': item_name, 'message': f'Produto "{item_name}" removido do cardápio.'},
        colaborador_id=session.get('user', 'Sistema')
    )
    
    flash('Produto removido do cardápio.')
    return redirect(url_for('menu.menu_management'))

@menu_bp.route('/api/menu/history/<product_name>')
@login_required
def get_product_history(product_name):
    user_role = session.get('role', '')
    allowed_roles = ['super', 'admin', 'gerente', 'recepcao', 'supervisor', 'diretor']
    
    # Check permissions
    has_permission = any(role in user_role for role in allowed_roles)
    if not has_permission:
        return jsonify({'error': 'Acesso negado'}), 403
        
    try:
        # Use LoggerService to find logs related to this product name
        logs_data = LoggerService.get_logs(
            departamento_id='Cardápio', 
            search_query=product_name
        )
        
        # Format for frontend
        history = []
        items = logs_data.get('items', []) if isinstance(logs_data, dict) else logs_data
        
        for log in items:
            if isinstance(log, dict):
                ts = log.get('timestamp')
                user = log.get('colaborador_id')
                action = log.get('acao')
                details = log.get('detalhes')
            else:
                ts = log.timestamp
                user = log.colaborador_id
                action = log.acao
                details = log.detalhes

            # Format timestamp
            if isinstance(ts, str):
                try:
                    dt = datetime.fromisoformat(ts)
                    ts_str = dt.strftime('%d/%m/%Y %H:%M:%S')
                except:
                    ts_str = ts
            elif hasattr(ts, 'strftime'):
                ts_str = ts.strftime('%d/%m/%Y %H:%M:%S')
            else:
                ts_str = str(ts)

            history.append({
                'timestamp': ts_str,
                'user': user,
                'action': action,
                'details': details
            })
            
        return jsonify({'history': history})
    except Exception as e:
        current_app.logger.error(f"Error fetching product history: {e}")
        return jsonify({'error': str(e)}), 500

@menu_bp.route('/menu/backups', methods=['GET'])
@login_required
def list_menu_backups():
    if session.get('role') not in ['super', 'admin', 'gerente']:
        return jsonify({'error': 'Unauthorized'}), 403
    
    from app.services.backup_service import backup_service
    backup_paths = backup_service.list_backups('products')
    
    backups_data = []
    for p in backup_paths:
        try:
            stat = os.stat(p)
            dt = datetime.fromtimestamp(stat.st_mtime)
            backups_data.append({
                'filename': os.path.basename(p),
                'date': dt.strftime('%d/%m/%Y %H:%M:%S'),
                'size': stat.st_size,
                'timestamp': stat.st_mtime
            })
        except Exception as e:
            current_app.logger.error(f"Error reading backup file {p}: {e}")
            continue

    return jsonify({
        'backups': backups_data,
        'history': [] 
    })

@menu_bp.route('/menu/backups/restore/<filename>', methods=['POST'])
@login_required
def restore_menu_backup_route(filename):
    if session.get('role') not in ['super', 'admin', 'gerente']:
         return jsonify({'error': 'Unauthorized'}), 403
         
    from app.services.backup_service import backup_service
    success, message = backup_service.restore_backup('products', filename)
    if success:
        LoggerService.log_acao(
            acao="Backup de Menu Restaurado",
            entidade="Backup",
            detalhes={'type': 'products', 'filename': filename},
            nivel_severidade='ALERTA',
            departamento_id='TI'
        )
        return jsonify({'success': True})
    else:
        return jsonify({'success': False, 'error': message}), 500

@menu_bp.route('/menu/backups/create', methods=['POST'])
@login_required
def create_manual_backup():
    if session.get('role') not in ['super', 'admin', 'gerente']:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
        
    try:
        from app.services.backup_service import backup_service
        success, msg = backup_service.trigger_backup('products')
        if success:
            LoggerService.log_acao(
                acao="Backup Manual de Menu Criado",
                entidade="Backup",
                detalhes={'type': 'products', 'msg': msg},
                nivel_severidade='INFO'
            )
            return jsonify({'success': True, 'message': msg})
        else:
            return jsonify({'success': False, 'error': msg}), 500
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@menu_bp.route('/menu/backups/diff/<filename>', methods=['GET'])
@login_required
def diff_menu_backup(filename):
    return jsonify({'error': 'Diff feature disabled'}), 501

@menu_bp.route('/menu/toggle-active/<item_id>', methods=['POST'])
@login_required
def toggle_menu_item_active(item_id):
    user_role = session.get('role')
    user_perms = session.get('permissions', [])
    
    if user_role not in ['super', 'admin', 'gerente', 'recepcao', 'supervisor'] and \
       'restaurante_full_access' not in user_perms and \
       'recepcao' not in user_perms:
        return jsonify({'success': False, 'message': 'Acesso restrito'}), 403
    menu_items = load_menu_items()
    for item in menu_items:
        if item.get('id') == item_id:
            item['active'] = not item.get('active', True)
            save_menu_items(menu_items)
            
            # Log System Action
            status_str = "ativado" if item['active'] else "desativado"
            changes = [f"Ativo: {not item['active']} -> {item['active']}"]
            LoggerService.log_acao(
                acao='Cardápio Alterado',
                entidade='Cardápio',
                detalhes={'id': item_id, 'name': item.get('name'), 'active': item['active'], 'message': f'Produto "{item.get("name")}" {status_str}.', 'changes': changes},
                colaborador_id=session.get('user', 'Sistema')
            )
            
            return jsonify({'success': True, 'active': item['active']})
    return jsonify({'success': False, 'message': 'Item não encontrado'}), 404

@menu_bp.route('/config/flavors', methods=['GET'], endpoint='flavor_config_endpoint')
@login_required
def flavor_config():
    user_role = session.get('role')
    user_perms = session.get('permissions', [])
    
    if user_role not in ['super', 'admin', 'gerente', 'recepcao', 'supervisor'] and \
       'restaurante_full_access' not in user_perms and \
       'recepcao' not in user_perms:
        flash('Acesso restrito.')
        return redirect(url_for('menu.menu_management'))
        
    flavor_groups = load_flavor_groups()
    insumos = load_products() # Add insumos to selection
    menu_items = load_menu_items()
    
    return render_template('flavor_config.html', flavor_groups=flavor_groups, insumos=insumos, menu_items=menu_items)

@menu_bp.route('/config/flavors/toggle_simple', methods=['POST'])
@login_required
def flavor_config_toggle_simple():
    try:
        data = request.get_json()
        group_id = data.get('group_id')
        item_id = data.get('item_id')
        is_simple = data.get('is_simple', False)
        
        flavor_groups = load_flavor_groups()
        group = next((g for g in flavor_groups if g['id'] == group_id), None)
        
        if not group:
            return jsonify({'success': False, 'message': 'Grupo não encontrado'})
            
        item = next((i for i in group.get('items', []) if i['id'] == item_id), None)
        if not item:
            return jsonify({'success': False, 'message': 'Item não encontrado'})
            
        item['is_simple'] = is_simple
        save_flavor_groups(flavor_groups)
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@menu_bp.route('/config/flavors/product/update_limit', methods=['POST'])
@login_required
def flavor_config_update_product_limit():
    user_role = session.get('role')
    user_perms = session.get('permissions', [])
    
    if user_role not in ['super', 'admin', 'gerente', 'recepcao', 'supervisor'] and \
       'restaurante_full_access' not in user_perms and \
       'recepcao' not in user_perms:
        return jsonify({'success': False, 'message': 'Acesso negado'}), 403
        
    try:
        data = request.get_json()
        product_id = data.get('product_id')
        max_flavors = int(data.get('max_flavors', 1))
        
        if max_flavors < 1:
            return jsonify({'success': False, 'message': 'O limite deve ser pelo menos 1'}), 400
            
        menu_items = load_menu_items()
        updated = False
        
        for item in menu_items:
            if str(item.get('id')) == str(product_id):
                item['max_flavors'] = max_flavors
                updated = True
                break
                
        if updated:
            save_menu_items(menu_items)
            return jsonify({'success': True, 'message': 'Limite atualizado com sucesso'})
        else:
            return jsonify({'success': False, 'message': 'Produto não encontrado'}), 404
            
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@menu_bp.route('/config/flavors/add', methods=['POST'])
@login_required
def flavor_config_add_group():
    user_role = session.get('role')
    user_perms = session.get('permissions', [])
    
    if user_role not in ['super', 'admin', 'gerente', 'recepcao', 'supervisor'] and \
       'restaurante_full_access' not in user_perms and \
       'recepcao' not in user_perms:
        return redirect(url_for('main.index'))
        
    group_id = request.form.get('group_id')
    group_name = request.form.get('group_name')
    
    if group_id and group_name:
        groups = load_flavor_groups()
        if any(g['id'] == group_id for g in groups):
            flash('ID do grupo já existe.')
        else:
            groups.append({
                'id': group_id,
                'name': group_name,
                'items': []
            })
            save_flavor_groups(groups)
            flash('Grupo criado com sucesso.')
            
    return redirect(url_for('menu.flavor_config_endpoint'))

@menu_bp.route('/config/flavors/delete', methods=['POST'])
@login_required
def flavor_config_delete_group():
    user_role = session.get('role')
    user_perms = session.get('permissions', [])
    
    if user_role not in ['super', 'admin', 'gerente', 'recepcao', 'supervisor'] and \
       'restaurante_full_access' not in user_perms and \
       'recepcao' not in user_perms:
        return redirect(url_for('main.index'))
        
    group_id = request.form.get('group_id')
    
    if group_id:
        groups = load_flavor_groups()
        groups = [g for g in groups if g['id'] != group_id]
        save_flavor_groups(groups)
        flash('Grupo excluído com sucesso.')
            
    return redirect(url_for('menu.flavor_config_endpoint'))

@menu_bp.route('/config/flavors/item/add', methods=['POST'])
@login_required
def flavor_config_add_item():
    user_role = session.get('role')
    user_perms = session.get('permissions', [])
    
    if user_role not in ['super', 'admin', 'gerente', 'recepcao', 'supervisor'] and \
       'restaurante_full_access' not in user_perms and \
       'recepcao' not in user_perms:
        return redirect(url_for('main.index'))
        
    group_id = request.form.get('group_id')
    # The form sends 'product_id' and optional 'qty'
    product_id = request.form.get('product_id')
    raw_qty = request.form.get('qty', '1.0')
    try:
        if isinstance(raw_qty, str):
            raw_qty = raw_qty.replace(',', '.')
        qty = float(raw_qty)
        if qty <= 0:
            qty = 1.0
    except Exception:
        qty = 1.0
    
    if group_id and product_id:
        groups = load_flavor_groups()
        group = next((g for g in groups if g['id'] == group_id), None)
        if group:
            if not any(i.get('id') == product_id for i in group.get('items', [])):
                insumos = load_products()
                insumo = next((p for p in insumos if str(p.get('id')) == str(product_id)), None)
                
                if insumo:
                    item_entry = {
                        'id': str(product_id),
                        'name': insumo.get('name', 'Item'),
                        'is_simple': False,
                        'qty': qty
                    }
                    if 'items' not in group or not isinstance(group['items'], list):
                        group['items'] = []
                    group['items'].append(item_entry)
                    save_flavor_groups(groups)
                    flash('Item adicionado ao grupo.')
                else:
                    flash('Insumo não encontrado.')
            else:
                flash('Item já está no grupo.')
        else:
            flash('Grupo não encontrado.')
            
    return redirect(url_for('menu.flavor_config_endpoint'))

@menu_bp.route('/config/flavors/item/delete', methods=['POST'])
@login_required
def flavor_config_delete_item():
    user_role = session.get('role')
    user_perms = session.get('permissions', [])
    
    if user_role not in ['super', 'admin', 'gerente', 'recepcao', 'supervisor'] and \
       'restaurante_full_access' not in user_perms and \
       'recepcao' not in user_perms:
        return redirect(url_for('main.index'))
        
    group_id = request.form.get('group_id')
    item_id = request.form.get('item_id')
    
    if group_id and item_id:
        groups = load_flavor_groups()
        group = next((g for g in groups if g['id'] == group_id), None)
        if group:
            group['items'] = [i for i in group['items'] if i['id'] != item_id]
            save_flavor_groups(groups)
            flash('Item removido do grupo.')
            
    return redirect(url_for('menu.flavor_config_endpoint'))
