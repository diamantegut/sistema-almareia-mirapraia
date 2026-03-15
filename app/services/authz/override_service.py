from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import uuid
from typing import Any, Callable, Dict, List, Optional

from app.services.authz.audit_authz import emit_authz_override_event
from app.services.authz.reason_codes import is_valid_reason_code
from app.services.authz.schemas import DecisionSchema, normalize_role_name, role_level_for, validate_override_ttl


OVERRIDE_PENDING = "pending"
OVERRIDE_APPROVED = "approved"
OVERRIDE_DENIED = "denied"
OVERRIDE_EXPIRED = "expired"
OVERRIDE_STATES = {OVERRIDE_PENDING, OVERRIDE_APPROVED, OVERRIDE_DENIED, OVERRIDE_EXPIRED}


class OverrideServiceError(ValueError):
    pass


@dataclass
class OverrideRecord:
    override_id: str
    request_id: str
    endpoint: str
    action: str
    executor_user: str
    policy_version: str
    policy_hash: str
    approver_minimum_role: str
    approver_minimum_role_level: int
    ttl_seconds: int
    reason_required: bool
    request_reason: str
    created_at: str
    status: str = OVERRIDE_PENDING
    approver_user: str = ""
    decision_reason: str = ""
    decided_at: str = ""
    result: str = OVERRIDE_PENDING
    history: List[Dict[str, Any]] = field(default_factory=list)


def _now_iso(now: Optional[datetime] = None) -> str:
    base = now if isinstance(now, datetime) else datetime.now(tz=timezone.utc)
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    return base.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_iso(value: str) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise OverrideServiceError("timestamp inválido para override")
    normalized = text.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _require_non_empty(value: Any, message: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise OverrideServiceError(message)
    return text


class OverrideService:
    def __init__(self, *, sink: Optional[Callable[[Dict[str, Any]], None]] = None):
        self._items: Dict[str, OverrideRecord] = {}
        self._sink = sink

    def _append_history(self, record: OverrideRecord, event: str, payload: Optional[Dict[str, Any]] = None, at_time: Optional[str] = None) -> None:
        entry = {
            "event": event,
            "timestamp": at_time or _now_iso(),
            "status": record.status,
            "payload": payload or {},
        }
        record.history.append(entry)

    def _emit_audit(self, record: OverrideRecord, *, approver_user: str, reason: str, result: str, ttl_seconds: Optional[int] = None) -> None:
        decision_event = {
            "event_type": "authz_decision",
            "action": record.action,
            "endpoint": record.endpoint,
            "executor_user": record.executor_user,
            "request_id": record.request_id,
            "policy_version": record.policy_version,
            "policy_hash": record.policy_hash,
        }
        emit_authz_override_event(
            decision_event=decision_event,
            approver_user=approver_user,
            reason=reason,
            result=result,
            sink=self._sink,
            ttl_seconds=ttl_seconds,
        )

    def get(self, override_id: str) -> Optional[OverrideRecord]:
        key = str(override_id or "").strip()
        return self._items.get(key)

    def create_override_request(
        self,
        *,
        request_id: str,
        endpoint: str,
        action: str,
        executor_user: str,
        policy_version: str,
        policy_hash: str,
        approver_minimum_role: str,
        ttl_seconds: int,
        request_reason: str,
        reason_required: bool = True,
        created_at: Optional[str] = None,
    ) -> OverrideRecord:
        request_id_value = _require_non_empty(request_id, "request_id é obrigatório")
        endpoint_value = _require_non_empty(endpoint, "endpoint é obrigatório")
        action_value = _require_non_empty(action, "action é obrigatória")
        executor_user_value = _require_non_empty(executor_user, "executor_user é obrigatório")
        policy_version_value = _require_non_empty(policy_version, "policy_version é obrigatório")
        policy_hash_value = _require_non_empty(policy_hash, "policy_hash é obrigatório")
        role_value = normalize_role_name(approver_minimum_role)
        ttl_value = validate_override_ttl(ttl_seconds)
        reason_value = str(request_reason or "").strip()
        if bool(reason_required) and not reason_value:
            raise OverrideServiceError("motivo de solicitação de override é obrigatório")

        override_id = uuid.uuid4().hex
        record = OverrideRecord(
            override_id=override_id,
            request_id=request_id_value,
            endpoint=endpoint_value,
            action=action_value,
            executor_user=executor_user_value,
            policy_version=policy_version_value,
            policy_hash=policy_hash_value,
            approver_minimum_role=role_value,
            approver_minimum_role_level=role_level_for(role_value),
            ttl_seconds=ttl_value,
            reason_required=bool(reason_required),
            request_reason=reason_value,
            created_at=_now_iso(_parse_iso(created_at) if created_at else None),
            status=OVERRIDE_PENDING,
            result=OVERRIDE_PENDING,
        )
        self._items[override_id] = record
        self._append_history(record, "created", {"request_reason": reason_value}, at_time=record.created_at)
        self._emit_audit(
            record,
            approver_user="",
            reason=reason_value or "pending",
            result=OVERRIDE_PENDING,
            ttl_seconds=record.ttl_seconds,
        )
        return record

    def create_from_engine_decision(
        self,
        *,
        decision: DecisionSchema,
        request_context: Dict[str, Any],
        executor_user: str,
        request_reason: str,
    ) -> OverrideRecord:
        if str(decision.decision or "").upper() != "REQUIRE_OVERRIDE":
            raise OverrideServiceError("decisão inválida para criação de override")
        if not is_valid_reason_code(decision.reason_code):
            raise OverrideServiceError("reason_code da decisão é inválido")
        required = decision.required if isinstance(decision.required, dict) else {}
        approver_minimum_role = str(required.get("approver_minimum_role") or "").strip() or "gerente"
        ttl_seconds = int(required.get("ttl_seconds", 300))
        reason_required = bool(required.get("reason_required", True))
        action = str((request_context or {}).get("action") or (request_context or {}).get("method") or "UNKNOWN").strip()
        endpoint = str((request_context or {}).get("endpoint") or "").strip()
        request_id = str((request_context or {}).get("request_id") or decision.request_id or "").strip()
        return self.create_override_request(
            request_id=request_id,
            endpoint=endpoint,
            action=action,
            executor_user=executor_user,
            policy_version=decision.policy_version,
            policy_hash=decision.policy_hash,
            approver_minimum_role=approver_minimum_role,
            ttl_seconds=ttl_seconds,
            request_reason=request_reason,
            reason_required=reason_required,
        )

    def _ensure_not_expired(self, record: OverrideRecord, *, at_time: Optional[str] = None) -> None:
        if record.status == OVERRIDE_EXPIRED:
            raise OverrideServiceError("override já expirado")
        if record.status in (OVERRIDE_APPROVED, OVERRIDE_DENIED):
            return
        now_dt = _parse_iso(at_time) if at_time else datetime.now(tz=timezone.utc)
        created_dt = _parse_iso(record.created_at)
        expires_at = created_dt + timedelta(seconds=int(record.ttl_seconds))
        if now_dt > expires_at:
            record.status = OVERRIDE_EXPIRED
            record.result = OVERRIDE_EXPIRED
            record.decided_at = _now_iso(now_dt)
            self._append_history(record, "expired", {"expired_at": record.decided_at}, at_time=record.decided_at)
            self._emit_audit(record, approver_user="", reason="ttl_expired", result=OVERRIDE_EXPIRED, ttl_seconds=record.ttl_seconds)
            raise OverrideServiceError("override expirado")

    def approve_override(
        self,
        *,
        override_id: str,
        approver_user: str,
        approver_role: str,
        reason: str,
        at_time: Optional[str] = None,
    ) -> OverrideRecord:
        record = self.get(override_id)
        if record is None:
            raise OverrideServiceError("override não encontrado")
        if record.status != OVERRIDE_PENDING:
            raise OverrideServiceError("override não está pendente")
        self._ensure_not_expired(record, at_time=at_time)
        role = normalize_role_name(approver_role)
        if role_level_for(role) < int(record.approver_minimum_role_level):
            raise OverrideServiceError("aprovador abaixo do role mínimo exigido")
        reason_text = str(reason or "").strip()
        if record.reason_required and not reason_text:
            raise OverrideServiceError("motivo obrigatório para aprovação de override")

        record.status = OVERRIDE_APPROVED
        record.result = OVERRIDE_APPROVED
        record.approver_user = _require_non_empty(approver_user, "approver_user é obrigatório")
        record.decision_reason = reason_text
        record.decided_at = _now_iso(_parse_iso(at_time) if at_time else None)
        self._append_history(
            record,
            "approved",
            {"approver_user": record.approver_user, "reason": reason_text},
            at_time=record.decided_at,
        )
        self._emit_audit(
            record,
            approver_user=record.approver_user,
            reason=reason_text,
            result=OVERRIDE_APPROVED,
            ttl_seconds=record.ttl_seconds,
        )
        return record

    def deny_override(
        self,
        *,
        override_id: str,
        approver_user: str,
        reason: str,
        at_time: Optional[str] = None,
    ) -> OverrideRecord:
        record = self.get(override_id)
        if record is None:
            raise OverrideServiceError("override não encontrado")
        if record.status != OVERRIDE_PENDING:
            raise OverrideServiceError("override não está pendente")
        self._ensure_not_expired(record, at_time=at_time)
        reason_text = str(reason or "").strip()
        if not reason_text:
            raise OverrideServiceError("motivo obrigatório para negação de override")

        record.status = OVERRIDE_DENIED
        record.result = OVERRIDE_DENIED
        record.approver_user = _require_non_empty(approver_user, "approver_user é obrigatório")
        record.decision_reason = reason_text
        record.decided_at = _now_iso(_parse_iso(at_time) if at_time else None)
        self._append_history(
            record,
            "denied",
            {"approver_user": record.approver_user, "reason": reason_text},
            at_time=record.decided_at,
        )
        self._emit_audit(
            record,
            approver_user=record.approver_user,
            reason=reason_text,
            result=OVERRIDE_DENIED,
            ttl_seconds=record.ttl_seconds,
        )
        return record

    def expire_override(self, *, override_id: str, at_time: Optional[str] = None) -> OverrideRecord:
        record = self.get(override_id)
        if record is None:
            raise OverrideServiceError("override não encontrado")
        if record.status == OVERRIDE_EXPIRED:
            return record
        if record.status in (OVERRIDE_APPROVED, OVERRIDE_DENIED):
            raise OverrideServiceError("override já finalizado")
        self._ensure_not_expired(record, at_time=at_time)
        now_iso = _now_iso(_parse_iso(at_time) if at_time else None)
        record.status = OVERRIDE_EXPIRED
        record.result = OVERRIDE_EXPIRED
        record.decided_at = now_iso
        self._append_history(record, "expired", {"expired_at": now_iso}, at_time=now_iso)
        self._emit_audit(
            record,
            approver_user="",
            reason="ttl_expired",
            result=OVERRIDE_EXPIRED,
            ttl_seconds=record.ttl_seconds,
        )
        return record
