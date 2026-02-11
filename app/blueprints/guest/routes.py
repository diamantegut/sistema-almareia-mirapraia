from flask import render_template, request, redirect, url_for, flash, jsonify, current_app, session
from . import guest_bp
from app.services.pre_checkin_service import pre_checkin_service
from app.models.models import SatisfactionSurvey, SatisfactionSurveyQuestion, SatisfactionSurveyResponse, SatisfactionSurveyInvite
from app.models.database import db
import json
import uuid
from datetime import datetime

@guest_bp.route('/pre-checkin/<token>', methods=['GET'])
def pre_checkin_form(token):
    data, error = pre_checkin_service.validate_token(token)
    if error:
        return render_template('pre_checkin.html', error=error)
    
    return render_template('pre_checkin.html', 
                           token=token, 
                           link_data=data['link_data'], 
                           guest=data['guest_data'])

@guest_bp.route('/api/pre-checkin/submit', methods=['POST'])
def pre_checkin_submit():
    token = request.form.get('token')
    if not token:
        return jsonify({'success': False, 'message': 'Token ausente.'}), 400
        
    success, message = pre_checkin_service.complete_pre_checkin(token, request.form, request.files)
    
    if success:
        return render_template('pre_checkin.html', success=True)
    else:
        return render_template('pre_checkin.html', error=message)

@guest_bp.route('/pesquisa', methods=['GET', 'POST'])
def satisfaction_survey():
    # Find the first active survey
    survey = SatisfactionSurvey.query.filter_by(is_active=True).first()
    if not survey:
        return "Nenhuma pesquisa ativa no momento.", 404
        
    questions_query = SatisfactionSurveyQuestion.query.filter_by(survey_id=survey.id).order_by(SatisfactionSurveyQuestion.position).all()
    
    # Prepare questions for template
    questions = []
    for q in questions_query:
        options = []
        if q.options_json:
            try:
                options = json.loads(q.options_json)
            except:
                pass
        questions.append({'q': q, 'options': options})
        
    if request.method == 'POST':
        answers = {}
        errors = {}
        
        for q in questions_query:
            field_name = f'q_{q.id}'
            val = request.form.get(field_name)
            
            if q.required and not val:
                errors[q.id] = "Campo obrigatório"
            else:
                answers[q.id] = val
                
        if errors:
            return render_template('satisfaction_survey_public.html', 
                                   survey=survey, 
                                   questions=questions, 
                                   errors=errors)
                                   
        # Save response
        response = SatisfactionSurveyResponse(
            survey_id=survey.id,
            answers_json=json.dumps(answers, ensure_ascii=False),
            meta_json=json.dumps({
                'ip': request.remote_addr,
                'user_agent': request.user_agent.string
            })
        )
        db.session.add(response)
        db.session.commit()
        
        # Check if there was an invite ref
        ref = request.form.get('ref')
        if ref:
            invite = SatisfactionSurveyInvite.query.filter_by(survey_id=survey.id, ref=ref).first()
            if invite:
                invite.used_at = datetime.now()
                invite.used_response_id = response.id
                db.session.commit()
        
        return render_template('satisfaction_survey_public.html', 
                               survey=survey, 
                               submitted=True, 
                               response_id=response.id)

    return render_template('satisfaction_survey_public.html', 
                           survey=survey, 
                           questions=questions, 
                           errors={})
