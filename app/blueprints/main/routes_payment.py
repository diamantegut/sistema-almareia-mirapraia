from flask import render_template, request, redirect, url_for, session, flash
from app.utils.decorators import login_required
from app.services.data_service import load_payment_methods, save_payment_methods
from app.services.fiscal_service import load_fiscal_settings
import re
from . import main_bp

@main_bp.route('/payment-methods', methods=['GET', 'POST'])
@login_required
def payment_methods():
    if session.get('role') != 'admin':
        if not session.get('TESTING'): 
            flash('Acesso restrito à Diretoria.')
            return redirect(url_for('main.index'))

    methods = load_payment_methods()
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'add':
            name = request.form.get('name')
            
            # New Checkboxes
            av_rest = request.form.get('available_restaurant') == 'on'
            av_rec = request.form.get('available_reception') == 'on'
            av_res = request.form.get('available_reservas') == 'on'
            
            is_fiscal = request.form.get('is_fiscal') == 'on'
            fiscal_cnpj = request.form.get('fiscal_cnpj', '').strip()
            
            available_in = []
            if av_rest: available_in.append('restaurant')
            if av_rec: available_in.append('reception')
            if av_res: available_in.append('reservations')
            
            if name:
                method_id = re.sub(r'[^a-z0-9]', '', name.lower())
                if not any(m['id'] == method_id for m in methods):
                    methods.append({
                        'id': method_id, 
                        'name': name,
                        'available_in': available_in,
                        'is_fiscal': is_fiscal,
                        'fiscal_cnpj': fiscal_cnpj
                    })
                    save_payment_methods(methods)
                    flash('Forma de pagamento adicionada.')
                else:
                    flash('Esta forma de pagamento já existe.')
        
        elif action == 'edit':
            method_id = request.form.get('id')
            new_name = request.form.get('name')
            
            av_rest = request.form.get('available_restaurant') == 'on'
            av_rec = request.form.get('available_reception') == 'on'
            av_res = request.form.get('available_reservas') == 'on'
            
            is_fiscal = request.form.get('is_fiscal') == 'on'
            fiscal_cnpj = request.form.get('fiscal_cnpj', '').strip()
            
            available_in = []
            if av_rest: available_in.append('restaurant')
            if av_rec: available_in.append('reception')
            if av_res: available_in.append('reservations')

            for m in methods:
                if m['id'] == method_id:
                    m['name'] = new_name
                    m['available_in'] = available_in
                    m['is_fiscal'] = is_fiscal
                    m['fiscal_cnpj'] = fiscal_cnpj
                    break
            save_payment_methods(methods)
            flash('Forma de pagamento atualizada.')

        elif action == 'delete':
            method_id = request.form.get('id')
            methods = [m for m in methods if m['id'] != method_id]
            save_payment_methods(methods)
            flash('Forma de pagamento removida.')
            
        return redirect(url_for('main.payment_methods'))
    
    fiscal_settings = load_fiscal_settings()
    fiscal_integrations = fiscal_settings.get('integrations', [])
        
    return render_template('payment_methods.html', methods=methods, fiscal_integrations=fiscal_integrations)
