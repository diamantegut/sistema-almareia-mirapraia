from app.models.database import db
from datetime import datetime
import uuid
import json

class LogAcaoDepartamento(db.Model):
    __tablename__ = 'logs_acoes_departamento'
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    timestamp = db.Column(db.DateTime, default=datetime.now, nullable=False)
    departamento_id = db.Column(db.String(50), nullable=False)
    colaborador_id = db.Column(db.String(50), nullable=False)
    acao = db.Column(db.Text, nullable=False)
    entidade = db.Column(db.String(255), nullable=False)
    detalhes = db.Column(db.Text, nullable=True) # Stored as JSON string
    nivel_severidade = db.Column(db.String(20), nullable=False, default='INFO')

    __table_args__ = (
        db.Index('idx_departamento_timestamp', 'departamento_id', 'timestamp'),
        db.Index('idx_colaborador_timestamp', 'colaborador_id', 'timestamp'),
        db.Index('idx_acao', 'acao'),
        db.Index('idx_acao_timestamp', 'acao', 'timestamp'),
        db.Index('idx_entidade', 'entidade'),
        db.Index('idx_timestamp', 'timestamp'),
    )

    def to_dict(self):
        detalhes_parsed = None
        if self.detalhes:
            try:
                detalhes_parsed = json.loads(self.detalhes)
            except (json.JSONDecodeError, TypeError):
                detalhes_parsed = self.detalhes

        return {
            'id': self.id,
            'timestamp': self.timestamp.isoformat(),
            'departamento_id': self.departamento_id,
            'colaborador_id': self.colaborador_id,
            'acao': self.acao,
            'entidade': self.entidade,
            'detalhes': detalhes_parsed,
            'nivel_severidade': self.nivel_severidade
        }

class WaitingListEntry(db.Model):
    __tablename__ = 'waiting_list_entries'

    id = db.Column(db.String(36), primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    entry_time = db.Column(db.DateTime, nullable=False)

    name = db.Column(db.String(60), nullable=False)
    phone = db.Column(db.String(30), nullable=True)
    phone_wa = db.Column(db.String(20), nullable=True, index=True)
    party_size = db.Column(db.Integer, nullable=False)

    status = db.Column(db.String(20), nullable=False, default='waiting')
    status_reason = db.Column(db.Text, nullable=True)
    last_updated = db.Column(db.DateTime, nullable=True)

    source = db.Column(db.String(30), nullable=True)
    created_by = db.Column(db.String(50), nullable=True)

    is_recurring = db.Column(db.Boolean, nullable=False, default=False)
    visit_number = db.Column(db.Integer, nullable=True)

    raw_data = db.Column(db.Text, nullable=True)

class SatisfactionSurvey(db.Model):
    __tablename__ = 'satisfaction_surveys'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.now, nullable=False)

    title = db.Column(db.String(120), nullable=False)
    audience = db.Column(db.String(20), nullable=False, default='hotel')
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    public_slug = db.Column(db.String(40), nullable=False, unique=True, index=True)

    intro_text = db.Column(db.Text, nullable=True)
    thank_you_text = db.Column(db.Text, nullable=True)

class SatisfactionSurveyQuestion(db.Model):
    __tablename__ = 'satisfaction_survey_questions'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    survey_id = db.Column(db.String(36), db.ForeignKey('satisfaction_surveys.id'), nullable=False, index=True)

    position = db.Column(db.Integer, nullable=False, default=1)
    question_text = db.Column(db.Text, nullable=False)
    question_type = db.Column(db.String(30), nullable=False, default='rating_0_10')
    required = db.Column(db.Boolean, nullable=False, default=True)
    options_json = db.Column(db.Text, nullable=True)

class SatisfactionSurveyResponse(db.Model):
    __tablename__ = 'satisfaction_survey_responses'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    survey_id = db.Column(db.String(36), db.ForeignKey('satisfaction_surveys.id'), nullable=False, index=True)
    submitted_at = db.Column(db.DateTime, default=datetime.now, nullable=False)

    answers_json = db.Column(db.Text, nullable=False)
    meta_json = db.Column(db.Text, nullable=True)

class SatisfactionSurveyInvite(db.Model):
    __tablename__ = 'satisfaction_survey_invites'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    survey_id = db.Column(db.String(36), db.ForeignKey('satisfaction_surveys.id'), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)

    ref = db.Column(db.String(32), nullable=False)
    used_at = db.Column(db.DateTime, nullable=True)
    used_response_id = db.Column(db.String(36), nullable=True)

    __table_args__ = (
        db.UniqueConstraint('survey_id', 'ref', name='uq_satisfaction_survey_invite_ref'),
        db.Index('idx_satisfaction_survey_invites_survey_created', 'survey_id', 'created_at'),
    )
