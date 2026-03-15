from flask import render_template, request, redirect, url_for, flash, jsonify, session
import uuid
from datetime import datetime
from . import quality_bp
from app.utils.decorators import login_required
from app.utils.logger import log_action
from app.services.data_service import load_quality_audits, save_quality_audits

@quality_bp.route('/quality/audit')
@login_required
def quality_audit_form():
    if session.get('role') not in ['admin', 'gerente', 'supervisor']:
        flash('Acesso restrito a gerência/supervisão.', 'error')
        return redirect(url_for('main.index'))
    return render_template('quality_audit.html')

@quality_bp.route('/quality/audit_submit', methods=['POST'])
@login_required
def quality_audit_submit():
    if session.get('role') not in ['admin', 'gerente', 'supervisor']:
        return jsonify({'success': False, 'error': 'Acesso negado'}), 403
    
    try:
        data = request.form
        
        # Calculate average score
        scores = [
            int(data.get('score_service', 0)),
            int(data.get('score_speed', 0)),
            int(data.get('score_cleanliness', 0)),
            int(data.get('score_accuracy', 0)),
            int(data.get('score_safety', 0)),
            int(data.get('score_general', 0))
        ]
        avg_score = sum(scores) / len(scores) if scores else 0
        
        audit_entry = {
            'id': str(uuid.uuid4()),
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'evaluator': session.get('user', 'Unknown'),
            'peak_scenario': 'peak_scenario' in data,
            'scores': {
                'service': int(data.get('score_service', 0)),
                'time': int(data.get('score_speed', 0)),
                'cleanliness': int(data.get('score_cleanliness', 0)),
                'accuracy': int(data.get('score_accuracy', 0)),
                'safety': int(data.get('score_safety', 0)),
                'general': int(data.get('score_general', 0))
            },
            'comments': {
                'service': data.get('obs_service', ''),
                'time': data.get('obs_speed', ''),
                'cleanliness': data.get('obs_cleanliness', ''),
                'accuracy': data.get('obs_accuracy', ''),
                'safety': data.get('obs_safety', ''),
                'general': data.get('obs_general', '')
            },
            'average_score': round(avg_score, 2)
        }
        
        audits = load_quality_audits()
        audits.insert(0, audit_entry) # Add to top
        save_quality_audits(audits)
        
        # Log action
        log_action('Auditoria de Qualidade', f"Nova auditoria registrada por {audit_entry['evaluator']} - Nota: {audit_entry['average_score']}", department='Gerência')
        
        flash('Auditoria registrada com sucesso!', 'success')
        return redirect(url_for('quality.quality_audit_history'))
        
    except Exception as e:
        print(f"Error submitting audit: {e}")
        flash('Erro ao salvar auditoria.', 'error')
        return redirect(url_for('quality.quality_audit_form'))

@quality_bp.route('/quality/history')
@login_required
def quality_audit_history():
    if session.get('role') not in ['admin', 'gerente', 'supervisor']:
        flash('Acesso restrito.', 'error')
        return redirect(url_for('main.index'))
    
    audits = load_quality_audits()
    return render_template('quality_audit_history.html', audits=audits)
