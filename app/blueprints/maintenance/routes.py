from flask import render_template, request, redirect, url_for, flash, jsonify, session, current_app
import os
import json
from datetime import datetime
from PIL import Image
from werkzeug.utils import secure_filename
from . import maintenance_bp
from app.utils.decorators import login_required
from app.services.data_service import load_maintenance_requests, save_maintenance_requests

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@maintenance_bp.route('/department/schedules')
@login_required
def department_schedules():
    if session.get('role') != 'gerente' and session.get('role') != 'admin':
        flash('Acesso restrito a gerentes.')
        return redirect(url_for('main.index'))
        
    user_dept = session.get('department')
    requests = load_maintenance_requests()
    
    # Se for admin, vê TODAS as solicitações que precisam de agendamento
    if session.get('role') == 'admin':
        dept_requests = [r for r in requests if r.get('status') == 'Aguardando Agendamento']
    else:
        # Filtra requisições DO departamento atual que precisam de agendamento
        dept_requests = [r for r in requests if r.get('department') == user_dept and r.get('status') == 'Aguardando Agendamento']
    
    return render_template('department_schedules.html', requests=dept_requests)

@maintenance_bp.route('/department/schedules/confirm/<req_id>', methods=['POST'])
@login_required
def confirm_schedule(req_id):
    if session.get('role') != 'gerente' and session.get('role') != 'admin' and session.get('role') != 'supervisor':
        return redirect(url_for('main.index'))
        
    scheduled_date = request.form.get('scheduled_date')
    scheduled_time = request.form.get('scheduled_time')
    
    requests = load_maintenance_requests()
    req = next((r for r in requests if r['id'] == req_id), None)
    
    # Verifica se a requisição é do departamento do usuário logado OU se é admin
    if req and (req.get('department') == session.get('department') or session.get('role') == 'admin'):
        try:
            d_scheduled = datetime.strptime(scheduled_date, '%d/%m/%Y')
            if d_scheduled.date() < datetime.now().date():
                flash('Erro: A data de agendamento não pode ser no passado.')
                return redirect(url_for('maintenance.department_schedules'))
                
            req['status'] = 'Agendado'
            req['scheduled_date'] = d_scheduled.strftime('%d/%m/%Y')
            req['scheduled_time'] = scheduled_time
            req['manager_update_date'] = datetime.now().strftime('%d/%m/%Y %H:%M')
            
            save_maintenance_requests(requests)
                
            flash(f'Agendamento confirmado para {req["scheduled_date"]} às {req["scheduled_time"]}.')
        except ValueError:
            flash('Erro: Data inválida.')
        
    return redirect(url_for('maintenance.department_schedules'))

@maintenance_bp.route('/maintenance/requests')
@login_required
def maintenance_requests_view():
    if session.get('role') != 'gerente' and session.get('role') != 'admin':
        flash('Acesso restrito.')
        return redirect(url_for('main.index'))
    
    if session.get('role') == 'gerente' and session.get('department') != 'Manutenção':
        flash('Acesso restrito a gerentes de manutenção.')
        return redirect(url_for('main.index'))
        
    requests = load_maintenance_requests()
    
    def sort_key(r):
        status_priority = {
            'Pendente': 0,
            'Em Andamento': 1,
            'Finalizado': 2,
            'Não Realizado': 2
        }
        prio = status_priority.get(r.get('status', 'Pendente'), 3)
        
        # Sort by priority, then date desc
        date_str = r.get('date', '01/01/2000')
        time_str = r.get('time', '00:00')
        try:
             dt = datetime.strptime(f"{date_str} {time_str}", '%d/%m/%Y %H:%M')
             timestamp = dt.timestamp()
        except:
             timestamp = 0
             
        return (prio, -timestamp)

    requests.sort(key=sort_key)
    return render_template('maintenance_requests.html', requests=requests)

@maintenance_bp.route('/maintenance/update/<req_id>', methods=['POST'])
@login_required
def update_maintenance_request(req_id):
    if session.get('role') != 'gerente' and session.get('role') != 'admin':
         return redirect(url_for('main.index'))
         
    new_status = request.form.get('status')
    feedback = request.form.get('feedback')
    
    requests = load_maintenance_requests()
    req = next((r for r in requests if r['id'] == req_id), None)
    
    if req:
        req['status'] = new_status
        req['feedback'] = feedback
        req['updated_at'] = datetime.now().strftime('%d/%m/%Y %H:%M')
        req['updated_by'] = session['user']
        
        save_maintenance_requests(requests)
        flash('Solicitação atualizada.')
        
    return redirect(url_for('maintenance.maintenance_requests_view'))

@maintenance_bp.route('/maintenance/new', methods=['GET'])
@login_required
def new_maintenance_request():
    return render_template('maintenance_form.html')

@maintenance_bp.route('/maintenance/submit', methods=['POST'])
@login_required
def submit_maintenance():
    if 'photo' not in request.files:
        flash('Nenhuma foto enviada.')
        return redirect(request.url)
    
    file = request.files['photo']
    location = request.form['location']
    description = request.form['description']
    
    if file.filename == '':
        flash('Nenhuma foto selecionada.')
        return redirect(request.url)
        
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        new_filename = f"{timestamp}_{session['user']}_{filename}"
        
        # Ensure upload folder exists
        upload_folder = os.path.join(current_app.static_folder, 'uploads/maintenance')
        if not os.path.exists(upload_folder):
             os.makedirs(upload_folder)
             
        filepath = os.path.join(upload_folder, new_filename)
        
        try:
            image = Image.open(file)
            if image.mode in ("RGBA", "P"):
                image = image.convert("RGB")
                
            max_width = 1024
            if image.width > max_width:
                ratio = max_width / float(image.width)
                new_height = int((float(image.height) * float(ratio)))
                image = image.resize((max_width, new_height), Image.Resampling.LANCZOS)
            
            image.save(filepath, optimize=True, quality=70)
            
            request_data = {
                'id': timestamp,
                'user': session['user'],
                'department': session.get('department', 'N/A'),
                'date': datetime.now().strftime('%d/%m/%Y'),
                'time': datetime.now().strftime('%H:%M'),
                'location': location,
                'description': description,
                'photo_url': url_for('static', filename=f'uploads/maintenance/{new_filename}'),
                'status': 'Pendente'
            }
            
            requests = load_maintenance_requests()
            requests.append(request_data)
            save_maintenance_requests(requests)
            
            flash('Solicitação de manutenção enviada com sucesso!')
            return redirect(url_for('main.service_page', service_id='manutencao'))
            
        except Exception as e:
            print(e)
            flash('Erro ao processar imagem.')
            return redirect(url_for('maintenance.new_maintenance_request'))
            
    flash('Tipo de arquivo não permitido.')
    return redirect(url_for('maintenance.new_maintenance_request'))
