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

    nome_completo = db.Column(db.String(120), nullable=True, index=True)
    telefone_raw = db.Column(db.String(40), nullable=True)
    telefone_normalizado = db.Column(db.String(30), nullable=True, index=True)
    ddi = db.Column(db.String(6), nullable=True)
    pais = db.Column(db.String(8), nullable=True, index=True)
    numero_pessoas = db.Column(db.Integer, nullable=True)
    origem_cadastro = db.Column(db.String(40), nullable=True, index=True)
    status_atual = db.Column(db.String(30), nullable=True, index=True)
    data_hora_entrada = db.Column(db.DateTime, nullable=True, index=True)
    data_hora_primeira_chamada = db.Column(db.DateTime, nullable=True)
    data_hora_ultima_chamada = db.Column(db.DateTime, nullable=True)
    data_hora_sentou = db.Column(db.DateTime, nullable=True)
    data_hora_encerramento = db.Column(db.DateTime, nullable=True)
    motivo_cancelamento = db.Column(db.Text, nullable=True)
    observacoes_internas = db.Column(db.Text, nullable=True)
    consentimento_marketing = db.Column(db.Boolean, nullable=False, default=False)
    consentimento_pesquisa = db.Column(db.Boolean, nullable=False, default=False)
    survey_status = db.Column(db.String(30), nullable=True, default='nao_enviada')
    survey_sent_at = db.Column(db.DateTime, nullable=True)
    tempo_espera_ate_chamada = db.Column(db.Integer, nullable=True)
    tempo_espera_ate_sentar = db.Column(db.Integer, nullable=True)
    tempo_entre_chamada_e_sentar = db.Column(db.Integer, nullable=True)
    tempo_total_do_fluxo = db.Column(db.Integer, nullable=True)

    raw_data = db.Column(db.Text, nullable=True)

class WaitingListEvent(db.Model):
    __tablename__ = 'waiting_list_events'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    waiting_list_id = db.Column(db.String(36), db.ForeignKey('waiting_list_entries.id'), nullable=False, index=True)
    tipo_evento = db.Column(db.String(40), nullable=False, index=True)
    status_anterior = db.Column(db.String(30), nullable=True, index=True)
    status_novo = db.Column(db.String(30), nullable=True, index=True)
    descricao = db.Column(db.Text, nullable=True)
    colaborador_id = db.Column(db.String(60), nullable=True, index=True)
    colaborador_nome = db.Column(db.String(120), nullable=True)
    mesa_id = db.Column(db.String(20), nullable=True, index=True)
    mesa_nome_ou_numero = db.Column(db.String(60), nullable=True)
    metadata_json = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False, index=True)

class WaitingListTableAllocation(db.Model):
    __tablename__ = 'waiting_list_table_allocations'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    waiting_list_id = db.Column(db.String(36), db.ForeignKey('waiting_list_entries.id'), nullable=False, index=True)
    mesa_id = db.Column(db.String(20), nullable=False, index=True)
    mesa_nome_ou_numero = db.Column(db.String(60), nullable=True)
    started_at = db.Column(db.DateTime, nullable=False, index=True)
    ended_at = db.Column(db.DateTime, nullable=True, index=True)
    is_current = db.Column(db.Boolean, nullable=False, default=True, index=True)
    moved_by_user_id = db.Column(db.String(60), nullable=True, index=True)
    moved_by_user_name = db.Column(db.String(120), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.now, nullable=False, index=True)

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
    waiting_list_id = db.Column(db.String(36), db.ForeignKey('waiting_list_entries.id'), nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    sent_at = db.Column(db.DateTime, default=datetime.now, nullable=False)

    ref = db.Column(db.String(32), nullable=False)
    delivery_status = db.Column(db.String(20), nullable=False, default='enviada', index=True)
    delivery_error = db.Column(db.Text, nullable=True)
    used_at = db.Column(db.DateTime, nullable=True)
    used_response_id = db.Column(db.String(36), nullable=True)

    __table_args__ = (
        db.UniqueConstraint('survey_id', 'ref', name='uq_satisfaction_survey_invite_ref'),
        db.Index('idx_satisfaction_survey_invites_survey_created', 'survey_id', 'created_at'),
    )


class RoomCategory(db.Model):
    __tablename__ = 'room_categories'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    code = db.Column(db.String(40), nullable=False, unique=True, index=True)
    name = db.Column(db.String(120), nullable=False, unique=True)
    capacity = db.Column(db.Integer, nullable=False, default=2)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.now, nullable=False)


class Room(db.Model):
    __tablename__ = 'rooms'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    room_number = db.Column(db.String(8), nullable=False, unique=True, index=True)
    category_id = db.Column(db.String(36), db.ForeignKey('room_categories.id'), nullable=True, index=True)
    floor = db.Column(db.String(20), nullable=True)
    max_adults = db.Column(db.Integer, nullable=False, default=2)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.now, nullable=False)


class Guest(db.Model):
    __tablename__ = 'guests'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    guest_uid = db.Column(db.String(80), nullable=False, unique=True, index=True)
    full_name = db.Column(db.String(255), nullable=False, index=True)
    document_id = db.Column(db.String(40), nullable=True, index=True)
    birth_date = db.Column(db.String(20), nullable=True)
    phone = db.Column(db.String(40), nullable=True, index=True)
    email = db.Column(db.String(255), nullable=True, index=True)
    address = db.Column(db.Text, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    document_attachment = db.Column(db.Text, nullable=True)
    signature_attachment = db.Column(db.Text, nullable=True)
    recurrence_count = db.Column(db.Integer, nullable=False, default=0)
    last_stay_date = db.Column(db.String(20), nullable=True)
    legacy_reservation_id = db.Column(db.String(80), nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.now, nullable=False)


class GuestPreference(db.Model):
    __tablename__ = 'guest_preferences'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    guest_id = db.Column(db.String(36), db.ForeignKey('guests.id'), nullable=False, index=True)
    dietary_restrictions = db.Column(db.Text, nullable=True)
    allergies = db.Column(db.Text, nullable=True)
    breakfast_preferences = db.Column(db.Text, nullable=True)
    commemorative_dates = db.Column(db.Text, nullable=True)
    service_notes = db.Column(db.Text, nullable=True)
    housekeeping_notes = db.Column(db.Text, nullable=True)
    is_vip = db.Column(db.Boolean, nullable=False, default=False)
    is_recurring = db.Column(db.Boolean, nullable=False, default=False)
    updated_at = db.Column(db.DateTime, default=datetime.now, nullable=False)


class Reservation(db.Model):
    __tablename__ = 'reservations'

    id = db.Column(db.String(36), primary_key=True)
    source_channel = db.Column(db.String(80), nullable=True, index=True)
    checkin_date = db.Column(db.String(20), nullable=False, index=True)
    checkout_date = db.Column(db.String(20), nullable=False, index=True)
    room_category = db.Column(db.String(120), nullable=True)
    room_id = db.Column(db.String(36), db.ForeignKey('rooms.id'), nullable=True, index=True)
    room_number = db.Column(db.String(8), nullable=True, index=True)
    total_amount = db.Column(db.Float, nullable=False, default=0.0)
    paid_amount = db.Column(db.Float, nullable=False, default=0.0)
    to_receive = db.Column(db.Float, nullable=False, default=0.0)
    reservation_status = db.Column(db.String(40), nullable=False, default='Confirmada', index=True)
    external_source = db.Column(db.String(120), nullable=True, index=True)
    external_reservation_id = db.Column(db.String(120), nullable=True, index=True)
    commercial_notes = db.Column(db.Text, nullable=True)
    legacy_payload = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.now, nullable=False)

    __table_args__ = (
        db.Index('idx_reservation_external_key', 'external_source', 'external_reservation_id'),
    )


class ReservationGuest(db.Model):
    __tablename__ = 'reservation_guests'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    reservation_id = db.Column(db.String(36), db.ForeignKey('reservations.id'), nullable=False, index=True)
    guest_id = db.Column(db.String(36), db.ForeignKey('guests.id'), nullable=False, index=True)
    is_primary = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)

    __table_args__ = (
        db.Index('idx_reservation_guest_unique', 'reservation_id', 'guest_id'),
    )


class Stay(db.Model):
    __tablename__ = 'stays'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    reservation_id = db.Column(db.String(36), db.ForeignKey('reservations.id'), nullable=False, index=True)
    primary_guest_id = db.Column(db.String(36), db.ForeignKey('guests.id'), nullable=True, index=True)
    room_id = db.Column(db.String(36), db.ForeignKey('rooms.id'), nullable=True, index=True)
    room_number = db.Column(db.String(8), nullable=True, index=True)
    operational_status = db.Column(db.String(50), nullable=False, default='Aguardando check-in', index=True)
    checkin_expected_at = db.Column(db.String(20), nullable=True)
    checkout_expected_at = db.Column(db.String(20), nullable=True)
    checkin_done_at = db.Column(db.String(20), nullable=True)
    checkout_done_at = db.Column(db.String(20), nullable=True)
    pending_items = db.Column(db.Text, nullable=True)
    operational_occurrence = db.Column(db.Text, nullable=True)
    legacy_room_key = db.Column(db.String(20), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.now, nullable=False)


class RoomStatusHistory(db.Model):
    __tablename__ = 'room_status_history'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    room_id = db.Column(db.String(36), db.ForeignKey('rooms.id'), nullable=True, index=True)
    room_number = db.Column(db.String(8), nullable=False, index=True)
    stay_id = db.Column(db.String(36), db.ForeignKey('stays.id'), nullable=True, index=True)
    reservation_id = db.Column(db.String(36), db.ForeignKey('reservations.id'), nullable=True, index=True)
    status = db.Column(db.String(50), nullable=False, index=True)
    note = db.Column(db.Text, nullable=True)
    changed_by = db.Column(db.String(80), nullable=True)
    changed_at = db.Column(db.DateTime, default=datetime.now, nullable=False, index=True)


class Payment(db.Model):
    __tablename__ = 'payments'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    reservation_id = db.Column(db.String(36), db.ForeignKey('reservations.id'), nullable=False, index=True)
    stay_id = db.Column(db.String(36), db.ForeignKey('stays.id'), nullable=True, index=True)
    amount = db.Column(db.Float, nullable=False, default=0.0)
    payment_method = db.Column(db.String(60), nullable=True)
    status = db.Column(db.String(40), nullable=False, default='received', index=True)
    paid_at = db.Column(db.String(20), nullable=True)
    source = db.Column(db.String(60), nullable=True)
    legacy_reference = db.Column(db.String(120), nullable=True, index=True)
    details_json = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)


class Consumption(db.Model):
    __tablename__ = 'consumptions'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    reservation_id = db.Column(db.String(36), db.ForeignKey('reservations.id'), nullable=True, index=True)
    stay_id = db.Column(db.String(36), db.ForeignKey('stays.id'), nullable=True, index=True)
    room_number = db.Column(db.String(8), nullable=True, index=True)
    amount = db.Column(db.Float, nullable=False, default=0.0)
    status = db.Column(db.String(40), nullable=False, default='pending', index=True)
    category = db.Column(db.String(80), nullable=True)
    description = db.Column(db.Text, nullable=True)
    launched_at = db.Column(db.String(20), nullable=True)
    legacy_charge_id = db.Column(db.String(120), nullable=True, index=True)
    payload_json = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)


class ReservationAuditLog(db.Model):
    __tablename__ = 'reservation_audit_logs'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    reservation_id = db.Column(db.String(36), db.ForeignKey('reservations.id'), nullable=True, index=True)
    stay_id = db.Column(db.String(36), db.ForeignKey('stays.id'), nullable=True, index=True)
    event_type = db.Column(db.String(80), nullable=False, index=True)
    event_source = db.Column(db.String(80), nullable=False, index=True)
    event_direction = db.Column(db.String(80), nullable=True, index=True)
    payload_json = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False, index=True)
