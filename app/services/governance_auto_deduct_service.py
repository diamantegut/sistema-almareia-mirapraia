import json
from datetime import datetime

from app.services.system_config_manager import get_data_path
from app.services.data_service import load_products, load_stock_entries, load_stock_requests, load_stock_transfers, add_stock_entries_batch
from app.services.stock_service import calculate_inventory


AUTO_DEDUCT_CONFIG_FILE = get_data_path('governance_auto_deduct_config.json')
AUTO_DEDUCT_AUDIT_FILE = get_data_path('governance_auto_deduct_audit.json')
EVENT_TYPES = ('checkin', 'daily_cleaning', 'checkout_cleaning')


def _load_json(path, default):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default


def _save_json(path, payload):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def _base_config():
    return {
        'checkin': [],
        'daily_cleaning': [],
        'checkout_cleaning': []
    }


def load_auto_deduct_config():
    raw = _load_json(AUTO_DEDUCT_CONFIG_FILE, _base_config())
    if not isinstance(raw, dict):
        raw = _base_config()
    out = _base_config()
    for event_type in EVENT_TYPES:
        event_items = raw.get(event_type, [])
        normalized = []
        for item in event_items if isinstance(event_items, list) else []:
            if not isinstance(item, dict):
                continue
            product_id = str(item.get('product_id') or '').strip()
            if not product_id:
                continue
            try:
                qty = round(float(item.get('qty') or 0.0), 4)
            except Exception:
                qty = 0.0
            if qty <= 0:
                continue
            normalized.append({
                'product_id': product_id,
                'product_name': str(item.get('product_name') or '').strip(),
                'qty': qty,
                'active': bool(item.get('active', True))
            })
        out[event_type] = normalized
    return out


def save_auto_deduct_config(config):
    payload = _base_config()
    src = config if isinstance(config, dict) else {}
    for event_type in EVENT_TYPES:
        payload[event_type] = src.get(event_type, [])
    _save_json(AUTO_DEDUCT_CONFIG_FILE, payload)
    return True


def load_auto_deduct_audit():
    raw = _load_json(AUTO_DEDUCT_AUDIT_FILE, [])
    if isinstance(raw, list):
        return raw
    return []


def save_auto_deduct_audit(rows):
    payload = rows if isinstance(rows, list) else []
    _save_json(AUTO_DEDUCT_AUDIT_FILE, payload)
    return True


def append_auto_deduct_audit(entry):
    rows = load_auto_deduct_audit()
    rows.append(entry)
    save_auto_deduct_audit(rows)
    return True


def _governance_products(all_products):
    items = []
    for p in all_products:
        if not isinstance(p, dict):
            continue
        name = str(p.get('name') or '')
        dep = str(p.get('department') or '')
        cat = str(p.get('category') or '')
        if dep.lower() == 'governança'.lower() or dep.lower() == 'governanca' or 'govern' in cat.lower() or 'govern' in name.lower():
            items.append(p)
    items.sort(key=lambda x: str(x.get('name') or '').lower())
    return items


def list_governance_candidate_products():
    return _governance_products(load_products())


def _balance_map(products):
    entries = load_stock_entries()
    requests = load_stock_requests()
    transfers = load_stock_transfers()
    inventory = calculate_inventory(products, entries, requests, transfers, target_dept='Geral')
    out = {}
    for name, info in (inventory or {}).items():
        try:
            out[str(name)] = float(info.get('balance') or 0.0)
        except Exception:
            out[str(name)] = 0.0
    return out


def low_stock_alerts_for_auto_deduct():
    products = load_products()
    by_id = {str(p.get('id')): p for p in products if isinstance(p, dict)}
    config = load_auto_deduct_config()
    balances = _balance_map(products)
    seen = set()
    alerts = []
    for event_type in EVENT_TYPES:
        for rule in config.get(event_type, []):
            if not rule.get('active', True):
                continue
            pid = str(rule.get('product_id'))
            if pid in seen:
                continue
            prod = by_id.get(pid)
            if not prod:
                continue
            seen.add(pid)
            name = str(prod.get('name') or '')
            balance = float(balances.get(name, 0.0))
            min_stock = float(prod.get('min_stock') or 0.0)
            if balance <= min_stock:
                alerts.append({
                    'product_id': pid,
                    'product_name': name,
                    'balance': round(balance, 2),
                    'min_stock': round(min_stock, 2)
                })
    alerts.sort(key=lambda x: x['balance'])
    return alerts


def upsert_auto_rule(event_type, product_id, qty, active=True):
    event_key = str(event_type or '').strip()
    if event_key not in EVENT_TYPES:
        return False, 'Evento inválido.'
    pid = str(product_id or '').strip()
    if not pid:
        return False, 'Produto inválido.'
    try:
        qty_val = round(float(qty or 0.0), 4)
    except Exception:
        return False, 'Quantidade inválida.'
    if qty_val <= 0:
        return False, 'Quantidade deve ser maior que zero.'
    config = load_auto_deduct_config()
    products = load_products()
    product = next((p for p in products if str(p.get('id') or '') == pid), None)
    if not product:
        return False, 'Produto não encontrado.'
    updated = False
    for row in config[event_key]:
        if str(row.get('product_id') or '') == pid:
            row['qty'] = qty_val
            row['active'] = bool(active)
            row['product_name'] = str(product.get('name') or '')
            updated = True
            break
    if not updated:
        config[event_key].append({
            'product_id': pid,
            'product_name': str(product.get('name') or ''),
            'qty': qty_val,
            'active': bool(active)
        })
    save_auto_deduct_config(config)
    return True, ''


def remove_auto_rule(event_type, product_id):
    event_key = str(event_type or '').strip()
    pid = str(product_id or '').strip()
    if event_key not in EVENT_TYPES:
        return False, 'Evento inválido.'
    config = load_auto_deduct_config()
    before = len(config[event_key])
    config[event_key] = [r for r in config[event_key] if str(r.get('product_id') or '') != pid]
    if len(config[event_key]) == before:
        return False, 'Regra não encontrada.'
    save_auto_deduct_config(config)
    return True, ''


def _product_indexes(products):
    by_id = {}
    by_name = {}
    for p in products:
        if not isinstance(p, dict):
            continue
        pid = str(p.get('id') or '').strip()
        pname = str(p.get('name') or '').strip()
        if pid:
            by_id[pid] = p
        if pname:
            by_name[pname.lower()] = p
    return by_id, by_name


def apply_manual_stock_movement(room_number, triggered_by, source, movement_type, items, event_ref='', metadata=None, strict=False, dry_run=False, allow_negative_stock=False):
    room = str(room_number or '').strip()
    who = str(triggered_by or '').strip() or 'Sistema'
    where = str(source or '').strip() or 'governance'
    mov_type = str(movement_type or '').strip() or 'manual'
    ref = str(event_ref or '').strip() or datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    context = metadata if isinstance(metadata, dict) else {}
    if not room:
        return {'success': False, 'error': 'Quarto inválido.'}
    movement_items = items if isinstance(items, list) else []
    products = load_products()
    by_id, by_name = _product_indexes(products)
    balances = _balance_map(products)
    ts = datetime.now()
    date_str = ts.strftime('%d/%m/%Y')
    normalized = []
    warnings = []
    insufficient = []
    for raw in movement_items:
        if not isinstance(raw, dict):
            continue
        pid = str(raw.get('product_id') or '').strip()
        pname = str(raw.get('product_name') or '').strip()
        product = by_id.get(pid) if pid else None
        if not product and pname:
            product = by_name.get(pname.lower())
        if not product:
            warnings.append(f"Produto não encontrado para movimento manual ({pid or pname}).")
            continue
        pid = str(product.get('id') or '').strip()
        pname = str(product.get('name') or '').strip()
        try:
            qty = round(float(raw.get('qty') or 0.0), 4)
        except Exception:
            warnings.append(f"Quantidade inválida para {pname}.")
            continue
        if abs(qty) <= 0:
            continue
        if qty < 0:
            balance = float(balances.get(pname, 0.0))
            needed = abs(qty)
            if balance < needed:
                warnings.append(f"Estoque insuficiente para {pname}: saldo {round(balance, 2)}, necessário {round(needed, 2)}")
                insufficient.append({'product': pname, 'balance': round(balance, 2), 'needed': round(needed, 2)})
                if not allow_negative_stock:
                    continue
            balances[pname] = balance - needed
        else:
            balances[pname] = float(balances.get(pname, 0.0)) + qty
        normalized.append({'product_id': pid, 'product_name': pname, 'qty': qty, 'price': float(product.get('price') or 0.0)})
    if strict and (insufficient or warnings):
        return {
            'success': False,
            'error': 'Movimento manual bloqueado por inconsistências de estoque.',
            'applied_count': 0,
            'entries': [],
            'warnings': warnings,
            'insufficient': insufficient,
            'normalized': normalized
        }
    if dry_run:
        return {
            'success': True,
            'applied_count': 0,
            'entries': [],
            'warnings': warnings,
            'insufficient': insufficient,
            'normalized': normalized,
            'would_apply_count': len(normalized)
        }
    entries = []
    invoice = str(context.get('invoice') or f"Governança Manual {mov_type}")
    for idx, item in enumerate(normalized):
        entries.append({
            'id': f"GOVMAN_{mov_type}_{room}_{item['product_id']}_{ts.strftime('%Y%m%d%H%M%S%f')}_{idx}",
            'user': who,
            'product': item['product_name'],
            'supplier': f"Governança Manual - Quarto {room} ({mov_type})",
            'qty': item['qty'],
            'price': item['price'],
            'date': date_str,
            'invoice': invoice,
            'room_number': room,
            'manual_event_type': mov_type,
            'manual_event_ref': ref,
            'manual_source': where
        })
    added = add_stock_entries_batch(entries) if entries else 0
    used_entries = entries[:added]
    applied_items = normalized[:added]
    append_auto_deduct_audit({
        'timestamp': datetime.now().strftime('%d/%m/%Y %H:%M:%S'),
        'success': bool(added > 0 or not normalized),
        'event_type': f"manual_{mov_type}",
        'room_number': room,
        'source': where,
        'triggered_by': who,
        'event_ref': ref,
        'items': [{'product': e.get('product'), 'qty': e.get('qty')} for e in used_entries],
        'warnings': warnings
    })
    return {
        'success': True,
        'applied_count': added,
        'entries': used_entries,
        'warnings': warnings,
        'insufficient': insufficient,
        'normalized': normalized,
        'applied_items': applied_items
    }


def _build_dedup_identity(event_type, room, event_ref, event_context=None):
    event_key = str(event_type or '').strip()
    room_key = str(room or '').strip()
    context = event_context if isinstance(event_context, dict) else {}
    raw_ref = str(event_ref or '').strip()
    if event_key == 'checkin':
        stay_ref = str(context.get('stay_ref') or raw_ref).strip()
        if not stay_ref:
            stay_ref = datetime.now().strftime('%Y-%m-%d')
        return {
            'dedup_scope': 'stay',
            'dedup_ref': stay_ref,
            'dedup_key': f"{event_key}|{room_key}|stay|{stay_ref}"
        }
    if event_key in ('daily_cleaning', 'checkout_cleaning'):
        cycle_ref = str(context.get('cleaning_cycle_ref') or raw_ref).strip()
        if cycle_ref:
            return {
                'dedup_scope': 'cleaning_cycle',
                'dedup_ref': cycle_ref,
                'dedup_key': f"{event_key}|{room_key}|cleaning_cycle|{cycle_ref}"
            }
        day_ref = datetime.now().strftime('%Y-%m-%d')
        return {
            'dedup_scope': 'event_day',
            'dedup_ref': day_ref,
            'dedup_key': f"{event_key}|{room_key}|event_day|{day_ref}"
        }
    ref = raw_ref or datetime.now().strftime('%Y-%m-%d')
    return {
        'dedup_scope': 'generic',
        'dedup_ref': ref,
        'dedup_key': f"{event_key}|{room_key}|generic|{ref}"
    }


def apply_auto_deduction(event_type, room_number, triggered_by, source, event_ref='', event_context=None):
    event_key = str(event_type or '').strip()
    room = str(room_number or '').strip()
    who = str(triggered_by or '').strip() or 'Sistema'
    where = str(source or '').strip() or 'governance'
    if event_key not in EVENT_TYPES:
        return {'success': False, 'error': 'Evento inválido.'}
    if not room:
        return {'success': False, 'error': 'Quarto inválido.'}
    identity = _build_dedup_identity(event_key, room, event_ref, event_context=event_context)
    dedup_key = identity['dedup_key']
    dedup_scope = identity['dedup_scope']
    dedup_ref = identity['dedup_ref']
    audits = load_auto_deduct_audit()
    if any(str(a.get('dedup_key') or '') == dedup_key and bool(a.get('success')) for a in audits if isinstance(a, dict)):
        return {
            'success': True,
            'duplicate': True,
            'dedup_key': dedup_key,
            'dedup_scope': dedup_scope,
            'dedup_ref': dedup_ref,
            'applied_count': 0,
            'entries': [],
            'warnings': []
        }
    config = load_auto_deduct_config()
    rules = [r for r in config.get(event_key, []) if bool(r.get('active', True))]
    if not rules:
        append_auto_deduct_audit({
            'timestamp': datetime.now().strftime('%d/%m/%Y %H:%M:%S'),
            'success': True,
            'dedup_key': dedup_key,
            'dedup_scope': dedup_scope,
            'dedup_ref': dedup_ref,
            'event_type': event_key,
            'room_number': room,
            'source': where,
            'triggered_by': who,
            'items': [],
            'warnings': ['Sem regras ativas para o evento.']
        })
        return {
            'success': True,
            'duplicate': False,
            'dedup_key': dedup_key,
            'dedup_scope': dedup_scope,
            'dedup_ref': dedup_ref,
            'applied_count': 0,
            'entries': [],
            'warnings': ['Sem regras ativas para o evento.']
        }
    products = load_products()
    by_id = {str(p.get('id') or ''): p for p in products if isinstance(p, dict)}
    balances = _balance_map(products)
    entries = []
    warnings = []
    ts = datetime.now()
    date_str = ts.strftime('%d/%m/%Y')
    for rule in rules:
        pid = str(rule.get('product_id') or '')
        prod = by_id.get(pid)
        if not prod:
            warnings.append(f"Produto não encontrado: {pid}")
            continue
        pname = str(prod.get('name') or '')
        qty = float(rule.get('qty') or 0.0)
        if qty <= 0:
            continue
        balance = float(balances.get(pname, 0.0))
        if balance < qty:
            warnings.append(f"Estoque insuficiente para {pname}: saldo {round(balance, 2)}, necessário {round(qty, 2)}")
            continue
        entry = {
            'id': f"GOVAUTO_{event_key}_{room}_{pid}_{ts.strftime('%Y%m%d%H%M%S%f')}",
            'user': who,
            'product': pname,
            'supplier': f"Governança Automática - Quarto {room} ({event_key})",
            'qty': -qty,
            'price': float(prod.get('price') or 0.0),
            'date': date_str,
            'invoice': f"Auto Gov {event_key}",
            'room_number': room,
            'auto_event_type': event_key,
            'auto_event_ref': dedup_ref,
            'auto_source': where
        }
        balances[pname] = balance - qty
        entries.append(entry)
    added = add_stock_entries_batch(entries) if entries else 0
    success = bool(added > 0 or not rules)
    append_auto_deduct_audit({
        'timestamp': datetime.now().strftime('%d/%m/%Y %H:%M:%S'),
        'success': success,
        'dedup_key': dedup_key,
        'dedup_scope': dedup_scope,
        'dedup_ref': dedup_ref,
        'event_type': event_key,
        'room_number': room,
        'source': where,
        'triggered_by': who,
        'event_ref': dedup_ref,
        'items': [{'product': e.get('product'), 'qty': e.get('qty')} for e in entries[:added]],
        'warnings': warnings
    })
    return {
        'success': True,
        'duplicate': False,
        'dedup_key': dedup_key,
        'dedup_scope': dedup_scope,
        'dedup_ref': dedup_ref,
        'applied_count': added,
        'entries': entries[:added],
        'warnings': warnings
    }
