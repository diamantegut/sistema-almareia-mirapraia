import json
import uuid
from datetime import datetime

from app.models.database import db
from app.models.models import (
    Consumption,
    Guest,
    GuestPreference,
    Payment,
    Reservation,
    ReservationAuditLog,
    ReservationGuest,
    Room,
    RoomCategory,
    RoomStatusHistory,
    Stay,
)
from app.services.data_service import load_room_charges, load_room_occupancy
from app.services.reservation_service import ReservationService


class ReceptionUnifiedRepository:
    def __init__(self):
        self.reservation_service = ReservationService()

    def ensure_schema(self):
        db.create_all()

    def _parse_money(self, value):
        try:
            text = str(value or '0').replace('R$', '').replace('.', '').replace(',', '.').strip()
            return float(text)
        except Exception:
            try:
                return float(value or 0)
            except Exception:
                return 0.0

    def _now(self):
        return datetime.now()

    def _normalize_guest_uid(self, details, reservation):
        details = details if isinstance(details, dict) else {}
        guest_uid = str(details.get('guest_uid') or '').strip()
        if guest_uid:
            return guest_uid
        personal = details.get('personal_info') if isinstance(details.get('personal_info'), dict) else {}
        fallback_name = str(personal.get('name') or reservation.get('guest_name') or 'guest').strip().lower()
        return f"legacy-{fallback_name.replace(' ', '-')[:40]}"

    def _upsert_room_category_and_room(self, reservation):
        category_name = str(reservation.get('category') or 'Sem categoria').strip()
        room_number = str(reservation.get('room') or '').strip()
        category_code = category_name.lower().replace(' ', '_')
        category = RoomCategory.query.filter_by(code=category_code).first()
        if not category:
            category = RoomCategory(
                id=str(uuid.uuid4()),
                code=category_code,
                name=category_name,
                capacity=int(self.reservation_service.ROOM_CAPACITIES.get(room_number or '01', 2)),
                created_at=self._now(),
                updated_at=self._now(),
            )
            db.session.add(category)
        else:
            category.name = category_name
            category.updated_at = self._now()

        room = None
        if room_number:
            room = Room.query.filter_by(room_number=room_number).first()
            if not room:
                room = Room(
                    id=str(uuid.uuid4()),
                    room_number=room_number,
                    category_id=category.id,
                    max_adults=int(self.reservation_service.ROOM_CAPACITIES.get(room_number, 2)),
                    created_at=self._now(),
                    updated_at=self._now(),
                )
                db.session.add(room)
            else:
                room.category_id = category.id
                room.max_adults = int(self.reservation_service.ROOM_CAPACITIES.get(room_number, room.max_adults or 2))
                room.updated_at = self._now()
        return category, room

    def _upsert_guest(self, reservation_id, reservation, details):
        details = details if isinstance(details, dict) else {}
        personal = details.get('personal_info') if isinstance(details.get('personal_info'), dict) else {}
        recurrence = details.get('recurrence_summary') if isinstance(details.get('recurrence_summary'), dict) else {}
        guest_uid = self._normalize_guest_uid(details, reservation)
        guest = Guest.query.filter_by(guest_uid=guest_uid).first()
        if not guest:
            guest = Guest(id=str(uuid.uuid4()), guest_uid=guest_uid, created_at=self._now(), updated_at=self._now())
            db.session.add(guest)

        guest.full_name = str(personal.get('name') or reservation.get('guest_name') or 'Hóspede sem nome')
        guest.document_id = str(personal.get('doc_id') or personal.get('cpf') or '')
        guest.birth_date = str(personal.get('birth_date') or '')
        guest.phone = str(personal.get('phone') or '')
        guest.email = str(personal.get('email') or '')
        guest.address = str(personal.get('address') or '')
        guest.notes = str(details.get('notes') or '')
        guest.document_attachment = details.get('document_photo') if details.get('document_photo') else None
        guest.signature_attachment = details.get('signature') if details.get('signature') else None
        guest.recurrence_count = int(recurrence.get('stays_count') or 0)
        guest.last_stay_date = recurrence.get('last_stay')
        guest.legacy_reservation_id = str(reservation_id)
        guest.updated_at = self._now()

        pref = GuestPreference.query.filter_by(guest_id=guest.id).first()
        op = details.get('operational_info') if isinstance(details.get('operational_info'), dict) else {}
        if not pref:
            pref = GuestPreference(id=str(uuid.uuid4()), guest_id=guest.id, updated_at=self._now())
            db.session.add(pref)
        pref.dietary_restrictions = json.dumps(op.get('dietary_restrictions') or [], ensure_ascii=False)
        pref.allergies = str(op.get('allergies') or '')
        pref.breakfast_preferences = json.dumps(
            {
                'start': op.get('breakfast_time_start') or '',
                'end': op.get('breakfast_time_end') or '',
            },
            ensure_ascii=False,
        )
        pref.commemorative_dates = json.dumps(op.get('commemorative_dates') or [], ensure_ascii=False)
        pref.service_notes = str(op.get('service_notes') or op.get('vip_note') or '')
        pref.housekeeping_notes = str(op.get('housekeeping_notes') or '')
        pref.is_vip = bool(op.get('vip_note') or op.get('vip'))
        pref.is_recurring = guest.recurrence_count >= 2
        pref.updated_at = self._now()
        return guest

    def _upsert_reservation(self, reservation_id, reservation, room):
        res = Reservation.query.filter_by(id=str(reservation_id)).first()
        if not res:
            res = Reservation(id=str(reservation_id), created_at=self._now(), updated_at=self._now())
            db.session.add(res)

        status_info = self.reservation_service.normalize_reservation_status(
            reservation.get('status'),
            reservation.get('checkin'),
            reservation.get('checkout'),
        )
        res.source_channel = str(reservation.get('channel') or '')
        res.checkin_date = str(reservation.get('checkin') or '')
        res.checkout_date = str(reservation.get('checkout') or '')
        res.room_category = str(reservation.get('category') or '')
        res.room_id = room.id if room else None
        res.room_number = room.room_number if room else str(reservation.get('room') or '')
        res.total_amount = self._parse_money(reservation.get('amount') or reservation.get('amount_val'))
        res.paid_amount = self._parse_money(reservation.get('paid_amount') or reservation.get('paid_amount_val'))
        res.to_receive = self._parse_money(reservation.get('to_receive') or reservation.get('to_receive_val'))
        res.reservation_status = status_info.get('label')
        res.external_source = str(reservation.get('external_source') or '')
        res.external_reservation_id = str(reservation.get('external_reservation_id') or '')
        res.commercial_notes = str(reservation.get('commercial_notes') or reservation.get('notes') or '')
        res.legacy_payload = json.dumps(reservation, ensure_ascii=False)
        res.updated_at = self._now()
        return res

    def _upsert_stay(self, reservation, reservation_row, guest, room):
        stay = Stay.query.filter_by(reservation_id=reservation_row.id).first()
        if not stay:
            stay = Stay(id=str(uuid.uuid4()), reservation_id=reservation_row.id, created_at=self._now(), updated_at=self._now())
            db.session.add(stay)

        occupancy = load_room_occupancy() or {}
        cleaning = {}
        try:
            from app.services.data_service import load_cleaning_status

            cleaning = load_cleaning_status() or {}
        except Exception:
            cleaning = {}
        op_status = self.reservation_service.derive_stay_operational_status(
            reservation=reservation,
            occupancy_data=occupancy,
            cleaning_status=cleaning,
        )
        stay.primary_guest_id = guest.id if guest else None
        stay.room_id = room.id if room else None
        stay.room_number = (room.room_number if room else str(op_status.get('room') or reservation.get('room') or ''))
        stay.operational_status = op_status.get('label') or 'Aguardando check-in'
        stay.checkin_expected_at = str(reservation.get('checkin') or '')
        stay.checkout_expected_at = str(reservation.get('checkout') or '')
        stay.updated_at = self._now()
        return stay

    def _link_reservation_guest(self, reservation_row, guest):
        if not reservation_row or not guest:
            return
        link = ReservationGuest.query.filter_by(reservation_id=reservation_row.id, guest_id=guest.id).first()
        if not link:
            link = ReservationGuest(
                id=str(uuid.uuid4()),
                reservation_id=reservation_row.id,
                guest_id=guest.id,
                is_primary=True,
                created_at=self._now(),
            )
            db.session.add(link)

    def _sync_legacy_payments_and_consumptions(self, reservation_row, stay_row):
        rid = str(reservation_row.id)
        payment_map = self.reservation_service.get_reservation_payments()
        for p in payment_map.get(rid, []) if isinstance(payment_map, dict) else []:
            pay = Payment.query.filter_by(reservation_id=rid, legacy_reference=str((p or {}).get('id') or '')).first()
            if not pay:
                pay = Payment(
                    id=str(uuid.uuid4()),
                    reservation_id=rid,
                    stay_id=stay_row.id if stay_row else None,
                    created_at=self._now(),
                )
                db.session.add(pay)
            pay.amount = self._parse_money((p or {}).get('amount'))
            pay.payment_method = str((p or {}).get('method') or (p or {}).get('payment_method') or '')
            pay.status = 'received'
            pay.paid_at = str((p or {}).get('date') or '')
            pay.source = 'legacy_reservation_payments_json'
            pay.legacy_reference = str((p or {}).get('id') or '')
            pay.details_json = json.dumps(p or {}, ensure_ascii=False)

        charges = load_room_charges() or []
        linked_room = str(reservation_row.room_number or '')
        for c in charges:
            room_number = str((c or {}).get('room_number') or '')
            if not linked_room or room_number != linked_room:
                continue
            cons = Consumption.query.filter_by(legacy_charge_id=str((c or {}).get('id') or '')).first()
            if not cons:
                cons = Consumption(
                    id=str(uuid.uuid4()),
                    reservation_id=rid,
                    stay_id=stay_row.id if stay_row else None,
                    created_at=self._now(),
                )
                db.session.add(cons)
            cons.room_number = room_number
            cons.amount = self._parse_money((c or {}).get('total'))
            cons.status = str((c or {}).get('status') or 'pending')
            cons.category = 'room_charge'
            cons.description = str((c or {}).get('description') or '')
            cons.launched_at = str((c or {}).get('date') or '')
            cons.legacy_charge_id = str((c or {}).get('id') or '')
            cons.payload_json = json.dumps(c or {}, ensure_ascii=False)

    def _write_audit(self, reservation_id, stay_id, event_type, payload, source='unified_repository', direction='legacy_to_unified'):
        row = ReservationAuditLog(
            id=str(uuid.uuid4()),
            reservation_id=str(reservation_id) if reservation_id else None,
            stay_id=str(stay_id) if stay_id else None,
            event_type=event_type,
            event_source=source,
            event_direction=direction,
            payload_json=json.dumps(payload or {}, ensure_ascii=False),
            created_at=self._now(),
        )
        db.session.add(row)

    def sync_from_legacy_reservation(self, reservation_id):
        rid = str(reservation_id or '').strip()
        if not rid:
            raise ValueError('reservation_id obrigatório')

        self.ensure_schema()
        reservation = self.reservation_service.get_reservation_by_id(rid)
        if not reservation:
            raise ValueError('Reserva não encontrada')
        details = self.reservation_service.get_guest_details(rid) or {}

        category, room = self._upsert_room_category_and_room(reservation)
        guest = self._upsert_guest(rid, reservation, details)
        reservation_row = self._upsert_reservation(rid, reservation, room)
        stay_row = self._upsert_stay(reservation, reservation_row, guest, room)
        self._link_reservation_guest(reservation_row, guest)
        self._sync_legacy_payments_and_consumptions(reservation_row, stay_row)

        self._write_audit(
            reservation_id=rid,
            stay_id=stay_row.id if stay_row else None,
            event_type='legacy_sync',
            payload={'reservation_status': reservation_row.reservation_status, 'room_number': reservation_row.room_number},
        )
        db.session.commit()
        return {'reservation_id': rid, 'stay_id': stay_row.id if stay_row else None}

    def sync_all_from_legacy(self, max_items=0):
        rows = self.reservation_service.get_february_reservations() or []
        total = 0
        errors = []
        for item in rows:
            rid = str((item or {}).get('id') or '').strip()
            if not rid:
                continue
            try:
                self.sync_from_legacy_reservation(rid)
                total += 1
            except Exception as exc:
                errors.append({'reservation_id': rid, 'error': str(exc)})
            if max_items and total >= int(max_items):
                break
        return {'synced': total, 'errors': errors}
