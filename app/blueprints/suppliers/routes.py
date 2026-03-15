import uuid
import requests
import json
from datetime import datetime
from flask import render_template, request, redirect, url_for, flash, jsonify, session
from app.utils.decorators import login_required, role_required
from app.services.data_service import load_suppliers, save_suppliers, load_products
from . import suppliers_bp

# --- Helpers ---

def get_supplier_by_id(supplier_id):
    suppliers = load_suppliers()
    # Handle legacy list of strings or dicts
    for s in suppliers:
        if isinstance(s, dict) and s.get('id') == supplier_id:
            return s
    return None

def normalize_supplier_data(s):
    """Ensures supplier has all new fields."""
    if isinstance(s, str):
        # Convert legacy string to object
        return {
            'id': str(uuid.uuid4()),
            'name': s,
            'trade_name': '',
            'cnpj': '',
            'ie': '',
            'address': {},
            'contacts': [],
            'category': 'Geral',
            'notes': '',
            'active': True,
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat()
        }
    
    # Ensure defaults
    defaults = {
        'id': str(uuid.uuid4()), # Assign ID if missing
        'trade_name': '',
        'cnpj': '',
        'ie': '',
        'address': {},
        'contacts': [],
        'category': 'Geral',
        'notes': '',
        'active': True,
        'created_at': datetime.now().isoformat(),
        'updated_at': datetime.now().isoformat()
    }
    
    for key, val in defaults.items():
        if key not in s:
            s[key] = val
            
    return s

# --- Routes ---

@suppliers_bp.route('/service/principal/suppliers')
@login_required
def index():
    try:
        suppliers = load_suppliers()
        # Normalize on the fly for display (but better to migrate properly)
        normalized_suppliers = []
        for s in suppliers:
            try:
                normalized_suppliers.append(normalize_supplier_data(s))
            except Exception as e:
                print(f"Error normalizing supplier: {s} - {e}")
                continue
            
        # Sorting
        sort_by = request.args.get('sort', 'name')
        order = request.args.get('order', 'asc')
        
        normalized_suppliers.sort(key=lambda x: x.get(sort_by, '').lower() if isinstance(x.get(sort_by), str) else '', reverse=(order == 'desc'))
        
        return render_template('suppliers/index.html', suppliers=normalized_suppliers)
    except Exception as e:
        print(f"Error in suppliers index: {e}")
        flash('Erro ao carregar fornecedores.', 'error')
        return redirect(url_for('main.index'))

@suppliers_bp.route('/service/principal/suppliers/new')
@login_required
def create():
    return render_template('suppliers/form.html', supplier=None)

@suppliers_bp.route('/service/principal/suppliers/edit/<supplier_id>')
@login_required
def edit(supplier_id):
    supplier = get_supplier_by_id(supplier_id)
    if not supplier:
        flash('Fornecedor não encontrado.', 'error')
        return redirect(url_for('suppliers.index'))
    return render_template('suppliers/form.html', supplier=supplier)

@suppliers_bp.route('/service/principal/suppliers/save', methods=['POST'])
@login_required
def save():
    data = request.form
    supplier_id = data.get('id')
    
    suppliers = load_suppliers()
    new_list = []
    
    # Extract data
    supplier_data = {
        'name': data.get('name'),
        'trade_name': data.get('trade_name'),
        'cnpj': data.get('cnpj'),
        'ie': data.get('ie'),
        'category': data.get('category'),
        'notes': data.get('notes'),
        'active': 'active' in data,
        'address': {
            'zip': data.get('addr_zip'),
            'street': data.get('addr_street'),
            'number': data.get('addr_number'),
            'comp': data.get('addr_comp'),
            'neighborhood': data.get('addr_neighborhood'),
            'city': data.get('addr_city'),
            'state': data.get('addr_state')
        },
        'updated_at': datetime.now().isoformat()
    }
    
    # Process Contacts (dynamic list from form)
    contacts = []
    contact_names = request.form.getlist('contact_name[]')
    contact_emails = request.form.getlist('contact_email[]')
    contact_phones = request.form.getlist('contact_phone[]')
    contact_roles = request.form.getlist('contact_role[]')
    
    for i in range(len(contact_names)):
        if contact_names[i]:
            contacts.append({
                'name': contact_names[i],
                'email': contact_emails[i] if i < len(contact_emails) else '',
                'phone': contact_phones[i] if i < len(contact_phones) else '',
                'role': contact_roles[i] if i < len(contact_roles) else ''
            })
    supplier_data['contacts'] = contacts

    if supplier_id:
        # Update
        found = False
        for s in suppliers:
            # Handle legacy
            s_norm = normalize_supplier_data(s)
            if s_norm['id'] == supplier_id:
                s_norm.update(supplier_data)
                new_list.append(s_norm)
                found = True
            else:
                new_list.append(s_norm)
        
        if not found:
            flash('Erro ao atualizar: ID não encontrado.', 'error')
    else:
        # Create
        supplier_data['id'] = str(uuid.uuid4())
        supplier_data['created_at'] = datetime.now().isoformat()
        # Migrate existing logic: if suppliers was list of strings, convert all?
        # We'll just append dict. load_suppliers should handle mixed types or we migrate all now.
        # Ideally we migrate all on first load/save.
        # Let's assume we append the new dict.
        
        # Ensure all existing are normalized before saving to avoid mixing types too much
        new_list = [normalize_supplier_data(s) for s in suppliers]
        new_list.append(supplier_data)
    
    if save_suppliers(new_list):
        flash('Fornecedor salvo com sucesso!', 'success')
    else:
        flash('Erro ao salvar fornecedor.', 'error')
        
    return redirect(url_for('suppliers.index'))

@suppliers_bp.route('/api/suppliers/validate_cnpj/<cnpj>')
@login_required
def validate_cnpj(cnpj):
    # Remove non-digits
    clean_cnpj = ''.join(filter(str.isdigit, cnpj))
    
    if len(clean_cnpj) != 14:
        return jsonify({'valid': False, 'message': 'CNPJ deve ter 14 dígitos.'})
        
    try:
        # Use BrasilAPI
        response = requests.get(f'https://brasilapi.com.br/api/cnpj/v1/{clean_cnpj}', timeout=5)
        if response.status_code == 200:
            data = response.json()
            return jsonify({
                'valid': True,
                'data': {
                    'name': data.get('razao_social'),
                    'trade_name': data.get('nome_fantasia'),
                    'zip': data.get('cep'),
                    'street': data.get('logradouro'),
                    'number': data.get('numero'),
                    'comp': data.get('complemento'),
                    'neighborhood': data.get('bairro'),
                    'city': data.get('municipio'),
                    'state': data.get('uf'),
                    'email': data.get('email'),
                    'phone': data.get('ddd_telefone_1')
                }
            })
        
        # Fallback to ReceitaWS if BrasilAPI fails (e.g. Rate Limit)
        if response.status_code == 429 or response.status_code >= 500:
             try:
                 ws_response = requests.get(f'https://www.receitaws.com.br/v1/cnpj/{clean_cnpj}', timeout=5)
                 if ws_response.status_code == 200:
                     ws_data = ws_response.json()
                     if ws_data.get('status') == 'OK':
                         return jsonify({
                             'valid': True,
                             'data': {
                                 'name': ws_data.get('nome'),
                                 'trade_name': ws_data.get('fantasia'),
                                 'zip': ws_data.get('cep').replace('.', '').replace('-', '') if ws_data.get('cep') else '',
                                 'street': ws_data.get('logradouro'),
                                 'number': ws_data.get('numero'),
                                 'comp': ws_data.get('complemento'),
                                 'neighborhood': ws_data.get('bairro'),
                                 'city': ws_data.get('municipio'),
                                 'state': ws_data.get('uf'),
                                 'email': ws_data.get('email'),
                                 'phone': ws_data.get('telefone')
                             }
                         })
             except Exception:
                 pass # Ignore fallback errors and return original error

        # BrasilAPI specific error handling
        error_msg = 'CNPJ não encontrado na Receita Federal.'
        if response.status_code == 404:
            error_msg = 'CNPJ não encontrado.'
        elif response.status_code == 500:
            error_msg = 'Erro interno na API de consulta.'
        elif response.status_code == 429:
            error_msg = 'Limite de consultas excedido. Tente novamente mais tarde.'
            
        return jsonify({'valid': False, 'message': error_msg})
            
    except requests.exceptions.ConnectionError as e:
        # Detect DNS specific error in message
        if "getaddrinfo failed" in str(e):
            return jsonify({'valid': False, 'message': 'Erro de DNS no servidor: Não foi possível localizar brasilapi.com.br. Verifique o DNS ou Firewall do servidor.'})
        return jsonify({'valid': False, 'message': 'Erro de conexão com a API. Verifique a internet do servidor.'})
    except requests.exceptions.Timeout:
        return jsonify({'valid': False, 'message': 'Tempo limite de consulta excedido. Tente novamente.'})
    except requests.exceptions.RequestException as e:
        return jsonify({'valid': False, 'message': f'Erro na consulta: Falha de comunicação com o serviço externo.'})
    except Exception as e:
        return jsonify({'valid': False, 'message': f'Erro interno: {str(e)}'})

@suppliers_bp.route('/service/principal/suppliers/import_products', methods=['POST'])
@login_required
def import_from_products():
    """Imports suppliers from products.json and merges with existing."""
    products = load_products()
    suppliers = load_suppliers()
    
    existing_names = set()
    normalized_suppliers = []
    
    # Normalize existing
    for s in suppliers:
        s_norm = normalize_supplier_data(s)
        normalized_suppliers.append(s_norm)
        existing_names.add(s_norm['name'].strip().lower())
        
    count = 0
    for p in products:
        # Handle both 'suppliers' (list) and legacy 'supplier' (string)
        names_to_add = []
        
        # New format (List)
        if isinstance(p.get('suppliers'), list):
            names_to_add.extend(p['suppliers'])
            
        # Legacy format (String)
        p_supplier = p.get('supplier')
        if isinstance(p_supplier, str) and p_supplier.strip():
            names_to_add.append(p_supplier)
            
        for name in names_to_add:
            if not isinstance(name, str): continue
            
            clean_name = name.strip()
            if clean_name and clean_name.lower() not in existing_names:
                new_s = normalize_supplier_data(clean_name)
                normalized_suppliers.append(new_s)
                existing_names.add(clean_name.lower())
                count += 1
                
    save_suppliers(normalized_suppliers)
    flash(f'{count} fornecedores importados dos produtos.', 'success')
    return redirect(url_for('suppliers.index'))

@suppliers_bp.route('/service/principal/suppliers/toggle_status/<supplier_id>')
@login_required
def toggle_status(supplier_id):
    suppliers = load_suppliers()
    found = False
    
    # We need to reconstruct the list with updates
    new_list = []
    
    for s in suppliers:
        s_norm = normalize_supplier_data(s)
        if s_norm['id'] == supplier_id:
            s_norm['active'] = not s_norm['active']
            found = True
            status_msg = "ativado" if s_norm['active'] else "inativado"
        new_list.append(s_norm)
        
    if found:
        save_suppliers(new_list)
        flash(f'Fornecedor {status_msg} com sucesso.', 'success')
    else:
        flash('Fornecedor não encontrado.', 'error')
        
    return redirect(url_for('suppliers.index'))

@suppliers_bp.route('/api/suppliers/list')
@login_required
def api_list():
    """Returns simple list for dropdowns (e.g. in Stock)"""
    suppliers = load_suppliers()
    normalized = [normalize_supplier_data(s) for s in suppliers]
    # Return only active
    active = [s for s in normalized if s.get('active', True)]
    active.sort(key=lambda x: x['name'])
    return jsonify(active)
