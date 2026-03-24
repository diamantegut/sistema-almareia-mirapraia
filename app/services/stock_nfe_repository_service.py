import json
import os
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from app.services.system_config_manager import get_data_path
from app.utils.lock import file_lock

NFE_REPOSITORY_FILE = get_data_path(os.path.join("fiscal", "nfe_received_repository.json"))


def _now_iso() -> str:
    return datetime.now().isoformat()


def _default_sync_state() -> Dict[str, Any]:
    return {
        "ultimo_nsu_processado": "0",
        "max_nsu_recebido": "0",
        "ultima_consulta_em": "",
        "ultimo_sucesso_em": "",
        "ultimo_erro_em": "",
        "ultimo_erro_resumo": "",
        "cooldown_ate": "",
        "lock_ativo": False,
        "lock_started_at": "",
        "last_method": "",
        "last_correlation_id": "",
        "next_sync_planned_at": "",
    }


def _default_data() -> Dict[str, Any]:
    return {
        "notes": [],
        "sync_state": _default_sync_state(),
        "supplier_links": [],
        "item_bindings": [],
        "manual_entries": [],
        "nsu_gaps": [],
        "sync_audit": [],
        "scheduler": {
            "ready_for_daily_schedule": True,
            "windows": ["08:00", "13:00", "17:00"],
        },
    }


def _load_data() -> Dict[str, Any]:
    if not os.path.exists(NFE_REPOSITORY_FILE):
        return _default_data()
    try:
        with open(NFE_REPOSITORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return _default_data()
    if not isinstance(data, dict):
        return _default_data()
    notes = data.get("notes")
    sync_state = data.get("sync_state")
    scheduler = data.get("scheduler")
    supplier_links = data.get("supplier_links")
    item_bindings = data.get("item_bindings")
    manual_entries = data.get("manual_entries")
    nsu_gaps = data.get("nsu_gaps")
    sync_audit = data.get("sync_audit")
    if not isinstance(notes, list):
        notes = []
    if not isinstance(sync_state, dict):
        sync_state = _default_sync_state()
    else:
        base = _default_sync_state()
        base.update(sync_state)
        sync_state = base
    if not isinstance(scheduler, dict):
        scheduler = _default_data()["scheduler"]
    if not isinstance(supplier_links, list):
        supplier_links = []
    if not isinstance(item_bindings, list):
        item_bindings = []
    if not isinstance(manual_entries, list):
        manual_entries = []
    if not isinstance(nsu_gaps, list):
        nsu_gaps = []
    if not isinstance(sync_audit, list):
        sync_audit = []
    return {
        "notes": notes,
        "sync_state": sync_state,
        "scheduler": scheduler,
        "supplier_links": supplier_links,
        "item_bindings": item_bindings,
        "manual_entries": manual_entries,
        "nsu_gaps": nsu_gaps,
        "sync_audit": sync_audit,
    }


def _save_data(data: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(NFE_REPOSITORY_FILE), exist_ok=True)
    with open(NFE_REPOSITORY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _safe_nsu_to_int(value: Any) -> Optional[int]:
    raw = str(value or "").strip()
    return int(raw) if raw.isdigit() else None


def _safe_int(value: Any, fallback: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(fallback)


def _apply_gap_operational_policy(row: Dict[str, Any]) -> Dict[str, Any]:
    status = str(row.get("status") or "pending").strip().lower()
    seen_count = max(1, _safe_int(row.get("seen_count"), 1))
    verification_attempts = max(0, _safe_int(row.get("verification_attempts"), 0))
    last_result = str(row.get("last_verification_result") or "").strip().lower()
    row["seen_count"] = seen_count
    row["verification_attempts"] = verification_attempts
    row["classification"] = str(row.get("classification") or "").strip().lower()

    if status == "resolved":
        row["classification"] = "provavel_gap_real"
        row["manual_recovery_recommended"] = False
        row["operational_action"] = "sem_acao"
    elif status == "ignored":
        row["classification"] = "provavelmente_ignorado"
        row["manual_recovery_recommended"] = False
        row["operational_action"] = "nao_tratar_como_problema"
    else:
        status = "pending"
        row["status"] = status
        if last_result in {"duplicate_document", "no_document_137"}:
            row["status"] = "ignored"
            row["classification"] = "provavelmente_ignorado"
            row["manual_recovery_recommended"] = False
            row["operational_action"] = "nao_tratar_como_problema"
        elif last_result == "recovered_document":
            row["status"] = "resolved"
            row["classification"] = "provavel_gap_real"
            row["manual_recovery_recommended"] = False
            row["operational_action"] = "sem_acao"
        elif verification_attempts >= 2 and last_result in {"transient_error", "partial_error", "unexpected_error"}:
            row["classification"] = "provavel_gap_real"
            row["manual_recovery_recommended"] = True
            row["operational_action"] = "sugerir_recuperacao_manual"
        else:
            row["classification"] = "ainda_nao_conclusivo"
            row["manual_recovery_recommended"] = False
            row["operational_action"] = "manter_em_observacao"
    row["policy_version"] = "nsu_gap_v2"
    return row


def _merge_unique_gaps(existing: List[Dict[str, Any]], detected: List[int]) -> List[Dict[str, Any]]:
    now_iso = _now_iso()
    rows = [row for row in existing if isinstance(row, dict)]
    by_nsu = {int(row.get("nsu")): row for row in rows if str(row.get("nsu") or "").isdigit()}
    for nsu_value in detected:
        current = by_nsu.get(nsu_value)
        if isinstance(current, dict):
            if str(current.get("status") or "") in {"resolved", "ignored"}:
                continue
            current["last_seen_at"] = now_iso
            current["status"] = "pending"
            current["seen_count"] = max(1, _safe_int(current.get("seen_count"), 1)) + 1
        else:
            by_nsu[nsu_value] = {
                "id": uuid.uuid4().hex,
                "nsu": str(nsu_value),
                "detected_at": now_iso,
                "last_seen_at": now_iso,
                "status": "pending",
                "classification": "ainda_nao_conclusivo",
                "verification_attempts": 0,
                "seen_count": 1,
                "manual_recovery_recommended": False,
                "operational_action": "manter_em_observacao",
            }
    merged = list(by_nsu.values())
    merged = [_apply_gap_operational_policy(dict(row)) for row in merged if isinstance(row, dict)]
    merged.sort(key=lambda row: int(str(row.get("nsu") or "0")))
    return merged


def _register_gap_verification(
    data: Dict[str, Any],
    *,
    nsu: str,
    outcome: str,
    correlation_id: str,
    message: str = "",
) -> None:
    nsu_value = str(nsu or "").strip()
    if not nsu_value.isdigit():
        return
    outcome_value = str(outcome or "").strip().lower()
    now_iso = _now_iso()
    gaps = data.get("nsu_gaps") if isinstance(data.get("nsu_gaps"), list) else []
    target = None
    for gap in gaps:
        if not isinstance(gap, dict):
            continue
        if str(gap.get("nsu") or "") == nsu_value:
            target = gap
            break
    if target is None:
        return
    target["verification_attempts"] = max(0, _safe_int(target.get("verification_attempts"), 0)) + 1
    target["last_verification_result"] = outcome_value
    target["last_verification_at"] = now_iso
    target["last_verification_correlation_id"] = str(correlation_id or "")
    target["updated_at"] = now_iso
    if message:
        target["last_verification_message"] = str(message)
    _apply_gap_operational_policy(target)


def _detect_nsu_gaps_values(nsu_values: List[int]) -> List[int]:
    if not nsu_values:
        return []
    ordered = sorted(set(nsu_values))
    missing: List[int] = []
    for idx in range(len(ordered) - 1):
        current = ordered[idx]
        nxt = ordered[idx + 1]
        if nxt - current <= 1:
            continue
        for gap in range(current + 1, nxt):
            missing.append(gap)
    return missing


def _append_sync_audit(data: Dict[str, Any], payload: Dict[str, Any]) -> None:
    rows = data.get("sync_audit") if isinstance(data.get("sync_audit"), list) else []
    rows.append(payload)
    data["sync_audit"] = rows[-1000:]


def _normalize_status(note: Dict[str, Any]) -> Dict[str, Any]:
    status_download = str(note.get("status_download") or "downloaded")
    status_conferencia = str(note.get("status_conferencia") or "pending_conference")
    status_estoque = str(note.get("status_estoque") or "pending")
    note["status_download"] = status_download
    note["status_conferencia"] = status_conferencia
    note["status_estoque"] = status_estoque
    if not note.get("document_type"):
        classified = _classify_document_payload(
            str(note.get("xml_raw") or ""),
            note.get("items_fiscais") if isinstance(note.get("items_fiscais"), list) else [],
        )
        note["document_type"] = str(classified.get("document_type") or "unknown_structure")
        note["has_full_items"] = bool(classified.get("has_full_items"))
        note["items_loaded"] = bool(classified.get("items_loaded"))
        note["items_reason"] = str(classified.get("items_reason") or "")
        note["xml_root"] = str(classified.get("xml_root") or "")
    note["has_full_items"] = bool(note.get("has_full_items"))
    note["items_loaded"] = bool(note.get("items_loaded"))
    note["items_reason"] = str(note.get("items_reason") or "")
    note["xml_root"] = str(note.get("xml_root") or "")
    note["manifestation_status"] = str(note.get("manifestation_status") or "not_sent")
    note["manifestation_type"] = str(note.get("manifestation_type") or "")
    note["manifestation_sent_at"] = str(note.get("manifestation_sent_at") or "")
    note["manifestation_protocol"] = str(note.get("manifestation_protocol") or "")
    note["manifestation_result"] = str(note.get("manifestation_result") or "")
    note["manifestation_error"] = str(note.get("manifestation_error") or "")
    note["manifestation_response_cstat"] = str(note.get("manifestation_response_cstat") or "")
    note["manifestation_response_xmotivo"] = str(note.get("manifestation_response_xmotivo") or "")
    note["manifestation_registered_at"] = str(note.get("manifestation_registered_at") or "")
    note["receipt_status"] = str(note.get("receipt_status") or "")
    note["financial_trace"] = bool(note.get("financial_trace"))
    note["stock_applied"] = bool(note.get("stock_applied"))
    note["approved_for_stock"] = bool(note.get("approved_for_stock"))
    note["received_not_stocked_at"] = str(note.get("received_not_stocked_at") or "")
    note["received_not_stocked_by"] = str(note.get("received_not_stocked_by") or "")
    note["received_not_stocked_note"] = str(note.get("received_not_stocked_note") or "")
    note["approved_for_stock_at"] = str(note.get("approved_for_stock_at") or "")
    note["approved_for_stock_by"] = str(note.get("approved_for_stock_by") or "")
    note["receipt_correlation_id"] = str(note.get("receipt_correlation_id") or "")
    note["rejected_at"] = str(note.get("rejected_at") or "")
    note["rejected_by"] = str(note.get("rejected_by") or "")
    note["rejection_reason"] = str(note.get("rejection_reason") or "")
    note["decision_source"] = str(note.get("decision_source") or "")
    note["decision_notes"] = str(note.get("decision_notes") or "")
    note["destination_type"] = str(note.get("destination_type") or "")
    note["destination_id"] = str(note.get("destination_id") or "")
    note["full_download_attempts"] = int(note.get("full_download_attempts") or 0)
    note["full_download_last_at"] = str(note.get("full_download_last_at") or "")
    note["full_download_last_result"] = str(note.get("full_download_last_result") or "")
    note["full_download_last_user"] = str(note.get("full_download_last_user") or "")
    note["last_full_xml_attempt_at"] = str(note.get("last_full_xml_attempt_at") or note.get("full_download_last_at") or "")
    note["full_xml_attempt_result"] = str(note.get("full_xml_attempt_result") or note.get("full_download_last_result") or "")
    note["full_xml_attempt_error"] = str(note.get("full_xml_attempt_error") or "")
    note["full_xml_upgrade_success"] = bool(note.get("full_xml_upgrade_success"))
    note["completeness_audit"] = note.get("completeness_audit") if isinstance(note.get("completeness_audit"), list) else []
    note["completeness_status"] = _derive_completeness_status(note)
    if status_estoque == "imported":
        note["status_conferencia"] = "conferenced"
        note["stock_applied"] = True
        note["approved_for_stock"] = True
        if not note.get("receipt_status"):
            note["receipt_status"] = "stocked"
        if not note.get("destination_type"):
            note["destination_type"] = "stock"
    elif status_estoque == "imported_asset":
        note["status_conferencia"] = "conferenced"
        note["stock_applied"] = False
        note["approved_for_stock"] = True
        note["financial_trace"] = True
        note["receipt_status"] = "stocked"
        note["destination_type"] = "asset"
    elif status_estoque == "received_not_stocked":
        note["receipt_status"] = "received_not_stocked"
        note["financial_trace"] = True
        note["stock_applied"] = False
        if not str(note.get("status_conferencia") or "").strip():
            note["status_conferencia"] = "conferenced"
    elif status_estoque == "rejected":
        note["receipt_status"] = "rejected"
        note["financial_trace"] = True
        note["stock_applied"] = False
        note["approved_for_stock"] = False
    else:
        if not note.get("receipt_status"):
            note["receipt_status"] = "pending"
    return note


def _note_status(note: Dict[str, Any]) -> str:
    status_estoque = str(note.get("status_estoque") or "")
    status_conferencia = str(note.get("status_conferencia") or "")
    status_download = str(note.get("status_download") or "")
    if status_estoque == "imported":
        return "imported"
    if status_estoque == "imported_asset":
        return "imported"
    if status_estoque == "received_not_stocked":
        return "received_not_stocked"
    if status_estoque == "rejected":
        return "rejected"
    if status_conferencia == "conferenced":
        return "conferenced"
    if status_conferencia == "in_conference":
        return "in_conference"
    if status_download == "error":
        return "error"
    return "pending_conference"


def _strip_xml_namespace(tag: str) -> str:
    tag_value = str(tag or "")
    return tag_value.split("}", 1)[1] if "}" in tag_value else tag_value


def _classify_document_payload(xml_raw: str, fiscal_items: List[Dict[str, Any]]) -> Dict[str, Any]:
    xml_value = str(xml_raw or "").strip()
    items = fiscal_items if isinstance(fiscal_items, list) else []
    has_items_list = len(items) > 0
    if not xml_value:
        return {
            "document_type": "unknown_structure",
            "has_full_items": bool(has_items_list),
            "items_loaded": bool(has_items_list),
            "items_reason": "xml_ausente" if not has_items_list else "",
            "xml_root": "",
        }
    try:
        root = ET.fromstring(xml_value)
        root_tag = _strip_xml_namespace(getattr(root, "tag", ""))
        inf_nfe = None
        if root_tag == "nfeProc":
            nfe_node = next((n for n in root if _strip_xml_namespace(getattr(n, "tag", "")) == "NFe"), None)
            if nfe_node is not None:
                inf_nfe = next((n for n in nfe_node if _strip_xml_namespace(getattr(n, "tag", "")) == "infNFe"), None)
        elif root_tag == "NFe":
            inf_nfe = next((n for n in root if _strip_xml_namespace(getattr(n, "tag", "")) == "infNFe"), None)
        if inf_nfe is None:
            inf_nfe = next((n for n in root.iter() if _strip_xml_namespace(getattr(n, "tag", "")) == "infNFe"), None)
        if root_tag in {"resNFe", "procNFe"}:
            return {
                "document_type": "summarized_nfe",
                "has_full_items": bool(has_items_list),
                "items_loaded": bool(has_items_list),
                "items_reason": "" if has_items_list else "document_summary_without_det",
                "xml_root": root_tag,
            }
        if inf_nfe is not None:
            det_count = len([n for n in list(inf_nfe) if _strip_xml_namespace(getattr(n, "tag", "")) == "det"])
            has_full = det_count > 0 or has_items_list
            return {
                "document_type": "full_nfe" if has_full else "summarized_nfe",
                "has_full_items": bool(has_full),
                "items_loaded": bool(has_full),
                "items_reason": "" if has_full else "infnfe_without_det",
                "xml_root": root_tag,
            }
        if root_tag.lower().endswith("evento") or root_tag.lower().startswith("procevento"):
            return {
                "document_type": "event_only",
                "has_full_items": bool(has_items_list),
                "items_loaded": bool(has_items_list),
                "items_reason": "" if has_items_list else "event_only_document",
                "xml_root": root_tag,
            }
        return {
            "document_type": "unknown_structure",
            "has_full_items": bool(has_items_list),
            "items_loaded": bool(has_items_list),
            "items_reason": "" if has_items_list else "unknown_xml_structure",
            "xml_root": root_tag,
        }
    except Exception:
        return {
            "document_type": "unknown_structure",
            "has_full_items": bool(has_items_list),
            "items_loaded": bool(has_items_list),
            "items_reason": "" if has_items_list else "xml_parse_error",
            "xml_root": "",
        }


def _derive_completeness_status(note: Dict[str, Any]) -> str:
    document_type = str(note.get("document_type") or "unknown_structure")
    has_full_items = bool(note.get("has_full_items"))
    manifestation_status = str(note.get("manifestation_status") or "not_sent")
    last_download_result = str(note.get("full_download_last_result") or "")
    if has_full_items and document_type == "full_nfe":
        return "ready_for_conference"
    if document_type == "summarized_nfe":
        if manifestation_status in {"sent", "registered"}:
            if last_download_result == "failed":
                return "full_download_failed"
            return "awaiting_full_download"
        return "awaiting_manifestation"
    if document_type in {"event_only", "unknown_structure"}:
        return "blocked_for_stock"
    return "blocked_for_stock"


def _build_note_from_document(
    doc: Dict[str, Any], source_method: str, correlation_id: str
) -> Dict[str, Any]:
    emit = doc.get("emitente") if isinstance(doc.get("emitente"), dict) else {}
    nsu_value = str(doc.get("nsu") or "")
    access_key = str(doc.get("access_key") or doc.get("chave") or "")
    number_value = str(doc.get("invoice_number") or "")
    serie_value = str(doc.get("invoice_serial") or "")
    data_emissao = str(doc.get("issued_at") or doc.get("created_at") or "")
    valor_total = float(doc.get("total_amount") or doc.get("amount") or doc.get("total") or 0.0)
    xml_raw = str(doc.get("xml_content") or "")
    resumo_json = {
        "issuer": emit.get("nome") or emit.get("xNome") or "",
        "cnpj": emit.get("cpf_cnpj") or emit.get("cnpj") or "",
        "amount": valor_total,
        "date": data_emissao,
    }
    fiscal_items = doc.get("items") if isinstance(doc.get("items"), list) else []
    document_info = _classify_document_payload(xml_raw, fiscal_items)
    return _normalize_status(
        {
            "id": uuid.uuid4().hex,
            "nsu": nsu_value,
            "chave_nfe": access_key,
            "numero_nfe": number_value,
            "serie": serie_value,
            "cnpj_emitente": str(resumo_json.get("cnpj") or ""),
            "nome_emitente": str(resumo_json.get("issuer") or ""),
            "data_emissao": data_emissao,
            "data_recebimento_sefaz": _now_iso(),
            "valor_total": valor_total,
            "xml_raw": xml_raw,
            "resumo_json": resumo_json,
            "source_method": str(source_method or "lastNSU"),
            "status_download": "downloaded" if xml_raw else "error",
            "status_conferencia": "pending_conference",
            "status_estoque": "pending",
            "downloaded_at": _now_iso(),
            "imported_to_stock_at": "",
            "last_seen_at": _now_iso(),
            "correlation_id": correlation_id,
            "supplier_id": "",
            "status_match_fornecedor": "not_matched",
            "item_mappings": [],
            "items_fiscais": fiscal_items,
            "document_type": str(document_info.get("document_type") or "unknown_structure"),
            "has_full_items": bool(document_info.get("has_full_items")),
            "items_loaded": bool(document_info.get("items_loaded")),
            "items_reason": str(document_info.get("items_reason") or ""),
            "xml_root": str(document_info.get("xml_root") or ""),
            "completeness_status": "ready_for_conference"
            if (str(document_info.get("document_type") or "") == "full_nfe" and bool(document_info.get("has_full_items")))
            else ("awaiting_manifestation" if str(document_info.get("document_type") or "") == "summarized_nfe" else "blocked_for_stock"),
            "manifestation_status": "not_sent",
            "manifestation_type": "",
            "manifestation_sent_at": "",
            "manifestation_protocol": "",
            "manifestation_result": "",
            "manifestation_error": "",
            "full_download_attempts": 0,
            "full_download_last_at": "",
            "full_download_last_result": "",
            "full_download_last_user": "",
            "completeness_audit": [],
        }
    )


def _find_note(notes: List[Dict[str, Any]], nsu: str, chave_nfe: str) -> Optional[Dict[str, Any]]:
    nsu_value = str(nsu or "")
    chave_value = str(chave_nfe or "")
    for note in notes:
        if str(note.get("chave_nfe") or "") and chave_value and str(note.get("chave_nfe") or "") == chave_value:
            return note
        if str(note.get("nsu") or "") and nsu_value and str(note.get("nsu") or "") == nsu_value:
            return note
    return None


def _upgrade_existing_note_snapshot(existing_note: Dict[str, Any], incoming_note: Dict[str, Any]) -> bool:
    if not isinstance(existing_note, dict) or not isinstance(incoming_note, dict):
        return False
    changed = False
    existing_has_items = bool(existing_note.get("has_full_items")) or bool(existing_note.get("items_fiscais"))
    incoming_has_items = bool(incoming_note.get("has_full_items")) or bool(incoming_note.get("items_fiscais"))
    incoming_xml = str(incoming_note.get("xml_raw") or "").strip()
    existing_xml = str(existing_note.get("xml_raw") or "").strip()
    if incoming_xml and (not existing_xml or (not existing_has_items and incoming_has_items)):
        existing_note["xml_raw"] = incoming_xml
        existing_note["status_download"] = "downloaded"
        changed = True
    if incoming_has_items and not existing_has_items:
        existing_note["items_fiscais"] = [dict(item) for item in (incoming_note.get("items_fiscais") or []) if isinstance(item, dict)]
        changed = True
    for field in ("document_type", "has_full_items", "items_loaded", "items_reason", "xml_root"):
        incoming_value = incoming_note.get(field)
        if incoming_value in ("", None, False) and field in {"document_type", "items_reason", "xml_root"}:
            continue
        if field == "has_full_items":
            if bool(incoming_value) and not bool(existing_note.get(field)):
                existing_note[field] = True
                changed = True
            continue
        if field == "items_loaded":
            if bool(incoming_value) and not bool(existing_note.get(field)):
                existing_note[field] = True
                changed = True
            continue
        if incoming_value and str(existing_note.get(field) or "") != str(incoming_value):
            existing_note[field] = incoming_value
            changed = True
    if changed:
        classified = _classify_document_payload(
            str(existing_note.get("xml_raw") or ""),
            existing_note.get("items_fiscais") if isinstance(existing_note.get("items_fiscais"), list) else [],
        )
        existing_note["document_type"] = str(classified.get("document_type") or existing_note.get("document_type") or "unknown_structure")
        existing_note["has_full_items"] = bool(classified.get("has_full_items"))
        existing_note["items_loaded"] = bool(classified.get("items_loaded"))
        existing_note["items_reason"] = str(classified.get("items_reason") or "")
        existing_note["xml_root"] = str(classified.get("xml_root") or "")
        existing_note["completeness_status"] = _derive_completeness_status(existing_note)
        existing_note["last_seen_at"] = _now_iso()
    return changed


def get_sync_state() -> Dict[str, Any]:
    with file_lock(NFE_REPOSITORY_FILE):
        data = _load_data()
        state = data.get("sync_state") if isinstance(data.get("sync_state"), dict) else _default_sync_state()
    return dict(state)


def list_sync_audit(*, limit: int = 200) -> List[Dict[str, Any]]:
    with file_lock(NFE_REPOSITORY_FILE):
        data = _load_data()
        rows = data.get("sync_audit") if isinstance(data.get("sync_audit"), list) else []
    out = [dict(row) for row in rows if isinstance(row, dict)]
    out.sort(key=lambda r: str(r.get("started_at") or ""), reverse=True)
    return out[: max(1, int(limit))]


def get_sync_operational_status() -> Dict[str, Any]:
    state = get_sync_state()
    gaps = list_nsu_gaps(limit=500)
    audits = list_sync_audit(limit=1)
    now = datetime.now()
    cooldown_ate = str(state.get("cooldown_ate") or "").strip()
    in_cooldown = False
    if cooldown_ate:
        try:
            in_cooldown = now < datetime.fromisoformat(cooldown_ate)
        except Exception:
            in_cooldown = False
    last_error = str(state.get("ultimo_erro_em") or "").strip()
    error_recent = False
    if last_error:
        try:
            error_recent = (now - datetime.fromisoformat(last_error)).total_seconds() < 2 * 3600
        except Exception:
            error_recent = False
    pending_total = sum(1 for gap in gaps if str(gap.get("status") or "").strip().lower() == "pending")
    pending_action = sum(
        1
        for gap in gaps
        if str(gap.get("status") or "").strip().lower() == "pending"
        and bool(gap.get("manual_recovery_recommended"))
    )
    pending_inconclusive = max(0, pending_total - pending_action)
    if in_cooldown or error_recent:
        label = "Erro recente detectado" if error_recent else "Em cooldown"
        color = "danger"
        code = "cooldown" if in_cooldown else "error_recent"
    elif pending_action > 0:
        label = "Com gaps com ação recomendada"
        color = "warning"
        code = "gaps_action_recommended"
    elif pending_inconclusive > 0:
        label = "Com gaps ainda inconclusivos"
        color = "info"
        code = "gaps_inconclusive"
    else:
        label = "Operação normal"
        color = "success"
        code = "ok"
    latest = audits[0] if audits else {}
    return {
        "code": code,
        "label": label,
        "color": color,
        "in_cooldown": in_cooldown,
        "pending_gaps": pending_total,
        "pending_action_count": pending_action,
        "pending_inconclusive_count": pending_inconclusive,
        "last_sync_result": str(latest.get("result") or ""),
        "last_sync_at": str(latest.get("finished_at") or state.get("ultima_consulta_em") or ""),
        "last_sync_duration_ms": int(latest.get("duration_ms") or 0),
    }


def get_scheduler_plan() -> Dict[str, Any]:
    with file_lock(NFE_REPOSITORY_FILE):
        data = _load_data()
    scheduler = data.get("scheduler") if isinstance(data.get("scheduler"), dict) else {}
    return dict(scheduler)


def detect_nsu_gaps() -> List[Dict[str, Any]]:
    with file_lock(NFE_REPOSITORY_FILE):
        data = _load_data()
        notes = data.get("notes") if isinstance(data.get("notes"), list) else []
        nsu_values = []
        for note in notes:
            if not isinstance(note, dict):
                continue
            nsu_int = _safe_nsu_to_int(note.get("nsu"))
            if nsu_int is not None:
                nsu_values.append(nsu_int)
        detected = _detect_nsu_gaps_values(nsu_values)
        existing = data.get("nsu_gaps") if isinstance(data.get("nsu_gaps"), list) else []
        merged = _merge_unique_gaps(existing, detected)
        data["nsu_gaps"] = merged
        _save_data(data)
    return merged


def list_nsu_gaps(*, status: str = "", limit: int = 500) -> List[Dict[str, Any]]:
    status_filter = str(status or "").strip().lower()
    with file_lock(NFE_REPOSITORY_FILE):
        data = _load_data()
        rows = data.get("nsu_gaps") if isinstance(data.get("nsu_gaps"), list) else []
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        current_row = _apply_gap_operational_policy(dict(row))
        current_status = str(current_row.get("status") or "pending").strip().lower()
        if status_filter and current_status != status_filter:
            continue
        out.append(current_row)
    out.sort(key=lambda r: int(str(r.get("nsu") or "0")))
    return out[: max(1, int(limit))]


def update_nsu_gap_status(*, nsu: str, status: str) -> bool:
    nsu_value = str(nsu or "").strip()
    status_value = str(status or "").strip().lower()
    if not nsu_value.isdigit():
        return False
    if status_value not in {"pending", "resolved", "ignored"}:
        return False
    changed = False
    with file_lock(NFE_REPOSITORY_FILE):
        data = _load_data()
        rows = data.get("nsu_gaps") if isinstance(data.get("nsu_gaps"), list) else []
        for row in rows:
            if not isinstance(row, dict):
                continue
            if str(row.get("nsu") or "") != nsu_value:
                continue
            row["status"] = status_value
            row["updated_at"] = _now_iso()
            _apply_gap_operational_policy(row)
            changed = True
            break
        if changed:
            _save_data(data)
    return changed


def list_notes(
    *,
    supplier: str = "",
    status: str = "",
    number: str = "",
    start_date: str = "",
    end_date: str = "",
    limit: int = 500,
) -> List[Dict[str, Any]]:
    supplier_filter = str(supplier or "").strip().lower()
    status_filter = str(status or "").strip().lower()
    number_filter = str(number or "").strip().lower()
    start_filter = str(start_date or "").strip()
    end_filter = str(end_date or "").strip()
    with file_lock(NFE_REPOSITORY_FILE):
        data = _load_data()
        notes = data.get("notes") if isinstance(data.get("notes"), list) else []
    out: List[Dict[str, Any]] = []
    for note in notes:
        if not isinstance(note, dict):
            continue
        item = _normalize_status(dict(note))
        if supplier_filter and supplier_filter not in str(item.get("nome_emitente") or "").strip().lower():
            continue
        current_status = _note_status(item)
        if status_filter and current_status != status_filter:
            continue
        if number_filter and number_filter not in str(item.get("numero_nfe") or "").strip().lower():
            continue
        data_emissao = str(item.get("data_emissao") or "")
        day = data_emissao[:10] if data_emissao else ""
        if start_filter and (not day or day < start_filter):
            continue
        if end_filter and (not day or day > end_filter):
            continue
        item["status"] = current_status
        item["item_pending_count"] = sum(
            1
            for mapping in (item.get("item_mappings") if isinstance(item.get("item_mappings"), list) else [])
            if str(mapping.get("status") or "") != "linked"
        )
        out.append(item)
    out.sort(key=lambda row: str(row.get("last_seen_at") or row.get("downloaded_at") or ""), reverse=True)
    return out[: max(1, int(limit))]


def get_note_by_access_key(access_key: str) -> Optional[Dict[str, Any]]:
    key_value = str(access_key or "").strip()
    if not key_value:
        return None
    with file_lock(NFE_REPOSITORY_FILE):
        data = _load_data()
        notes = data.get("notes") if isinstance(data.get("notes"), list) else []
        for note in notes:
            if not isinstance(note, dict):
                continue
            if str(note.get("chave_nfe") or "") == key_value:
                item = _normalize_status(dict(note))
                if not item.get("document_type"):
                    classified = _classify_document_payload(
                        str(item.get("xml_raw") or ""),
                        item.get("items_fiscais") if isinstance(item.get("items_fiscais"), list) else [],
                    )
                    item["document_type"] = classified.get("document_type")
                    item["has_full_items"] = bool(classified.get("has_full_items"))
                    item["items_loaded"] = bool(classified.get("items_loaded"))
                    item["items_reason"] = str(classified.get("items_reason") or "")
                    item["xml_root"] = str(classified.get("xml_root") or "")
                item["status"] = _note_status(item)
                return item
    return None


def suggest_supplier_for_note(
    *,
    cnpj_emitente: str,
    nome_emitente: str,
    suppliers: List[Dict[str, Any]],
) -> Dict[str, Any]:
    cnpj_value = "".join(ch for ch in str(cnpj_emitente or "") if ch.isdigit())
    nome_value = str(nome_emitente or "").strip().lower()
    supplier_rows = suppliers if isinstance(suppliers, list) else []
    by_cnpj = []
    by_name = []
    for supplier in supplier_rows:
        if not isinstance(supplier, dict):
            continue
        supplier_cnpj = "".join(ch for ch in str(supplier.get("cnpj") or supplier.get("cpf_cnpj") or "") if ch.isdigit())
        supplier_name = str(supplier.get("name") or "").strip().lower()
        if cnpj_value and supplier_cnpj and cnpj_value == supplier_cnpj:
            by_cnpj.append(supplier)
        elif nome_value and supplier_name and nome_value in supplier_name:
            by_name.append(supplier)
    if len(by_cnpj) == 1:
        hit = by_cnpj[0]
        return {
            "matched": True,
            "match_type": "auto_matched",
            "supplier_id": str(hit.get("id") or ""),
            "supplier_name": str(hit.get("name") or ""),
            "confidence": "high",
            "confidence_score": 0.95,
            "reason": "Fornecedor identificado pelo CNPJ",
            "source": "cnpj_exact",
        }
    historical_match = None
    with file_lock(NFE_REPOSITORY_FILE):
        data = _load_data()
        notes = data.get("notes") if isinstance(data.get("notes"), list) else []
    for note in notes:
        if not isinstance(note, dict):
            continue
        if not str(note.get("supplier_id") or "").strip():
            continue
        note_cnpj = "".join(ch for ch in str(note.get("cnpj_emitente") or "") if ch.isdigit())
        note_name = str(note.get("nome_emitente") or "").strip().lower()
        if cnpj_value and note_cnpj and cnpj_value == note_cnpj:
            historical_match = str(note.get("supplier_id") or "")
            break
        if nome_value and note_name and nome_value == note_name:
            historical_match = str(note.get("supplier_id") or "")
    if historical_match:
        suggested = next((s for s in supplier_rows if str(s.get("id") or "") == historical_match), None)
        if isinstance(suggested, dict):
            return {
                "matched": True,
                "match_type": "manual_matched",
                "supplier_id": str(suggested.get("id") or ""),
                "supplier_name": str(suggested.get("name") or ""),
                "confidence": "medium",
                "confidence_score": 0.75,
                "reason": "Fornecedor sugerido por vínculo anterior",
                "source": "history_match",
            }
    if by_cnpj or by_name:
        options = by_cnpj if by_cnpj else by_name
        return {
            "matched": False,
            "match_type": "manual_matched",
            "supplier_id": "",
            "supplier_name": "",
            "confidence": "low",
            "confidence_score": 0.45,
            "reason": "Fornecedor com nome semelhante encontrado",
            "source": "name_similarity",
            "options": [
                {"id": str(row.get("id") or ""), "name": str(row.get("name") or "")}
                for row in options[:20]
            ],
        }
    return {
        "matched": False,
        "match_type": "not_matched",
        "supplier_id": "",
        "supplier_name": "",
        "confidence": "low",
        "confidence_score": 0.2,
        "reason": "Nenhum fornecedor compatível encontrado",
        "source": "none",
        "options": [],
    }


def bind_note_supplier(
    *,
    access_key: str,
    supplier_id: str,
    status_match_fornecedor: str,
    suggestion_used: bool = False,
    suggestion_modified: bool = False,
    supplier_match_source: str = "",
    enrichment_applied: bool = False,
    enriched_fields: Optional[List[str]] = None,
    created_via_nfe: bool = False,
    created_supplier_id: str = "",
    decision_notes: str = "",
    decided_by: str = "",
    supplier_divergences: Optional[List[str]] = None,
) -> bool:
    key_value = str(access_key or "").strip()
    supplier_value = str(supplier_id or "").strip()
    status_value = str(status_match_fornecedor or "manual_matched").strip().lower()
    if status_value not in {"auto_matched", "manual_matched", "not_matched"}:
        return False
    changed = False
    with file_lock(NFE_REPOSITORY_FILE):
        data = _load_data()
        notes = data.get("notes") if isinstance(data.get("notes"), list) else []
        links = data.get("supplier_links") if isinstance(data.get("supplier_links"), list) else []
        for note in notes:
            if not isinstance(note, dict):
                continue
            if str(note.get("chave_nfe") or "") != key_value:
                continue
            note["supplier_id"] = supplier_value
            note["status_match_fornecedor"] = status_value
            note["supplier_suggestion_used"] = bool(suggestion_used)
            note["supplier_suggestion_modified"] = bool(suggestion_modified)
            note["supplier_match_source"] = str(supplier_match_source or "")
            note["enrichment_applied"] = bool(enrichment_applied)
            note["enriched_fields"] = [str(x) for x in (enriched_fields or []) if str(x).strip()]
            note["created_via_nfe"] = bool(created_via_nfe)
            note["created_supplier_id"] = str(created_supplier_id or "")
            note["supplier_decision_notes"] = str(decision_notes or "")
            note["supplier_decided_by"] = str(decided_by or "")
            note["supplier_decided_at"] = _now_iso()
            note["supplier_divergences"] = [str(x) for x in (supplier_divergences or []) if str(x).strip()]
            note["last_seen_at"] = _now_iso()
            changed = True
            break
        if changed:
            links = [row for row in links if not (isinstance(row, dict) and str(row.get("access_key") or "") == key_value)]
            links.append(
                {
                    "id": uuid.uuid4().hex,
                    "access_key": key_value,
                    "supplier_id": supplier_value,
                    "status_match_fornecedor": status_value,
                    "suggestion_used": bool(suggestion_used),
                    "suggestion_modified": bool(suggestion_modified),
                    "supplier_match_source": str(supplier_match_source or ""),
                    "enrichment_applied": bool(enrichment_applied),
                    "enriched_fields": [str(x) for x in (enriched_fields or []) if str(x).strip()],
                    "created_via_nfe": bool(created_via_nfe),
                    "created_supplier_id": str(created_supplier_id or ""),
                    "decision_notes": str(decision_notes or ""),
                    "decided_by": str(decided_by or ""),
                    "supplier_divergences": [str(x) for x in (supplier_divergences or []) if str(x).strip()],
                    "updated_at": _now_iso(),
                }
            )
            data["supplier_links"] = links
            _save_data(data)
    return changed


def list_item_bindings(*, supplier_id: str = "", product_id: str = "", limit: int = 1000) -> List[Dict[str, Any]]:
    supplier_filter = str(supplier_id or "").strip()
    product_filter = str(product_id or "").strip()
    with file_lock(NFE_REPOSITORY_FILE):
        data = _load_data()
        rows = data.get("item_bindings") if isinstance(data.get("item_bindings"), list) else []
    out: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if supplier_filter and str(row.get("supplier_id") or "") != supplier_filter:
            continue
        if product_filter and str(row.get("product_id") or "") != product_filter:
            continue
        out.append(dict(row))
    out.sort(key=lambda r: str(r.get("last_used_at") or ""), reverse=True)
    return out[: max(1, int(limit))]


def suggest_item_binding(
    *,
    supplier_id: str,
    supplier_product_code: str,
    supplier_product_name: str,
) -> Optional[Dict[str, Any]]:
    supplier_value = str(supplier_id or "").strip()
    code_value = str(supplier_product_code or "").strip().lower()
    name_value = str(supplier_product_name or "").strip().lower()
    if not supplier_value:
        return None
    rows = list_item_bindings(supplier_id=supplier_value, limit=500)
    exact_code = next((row for row in rows if code_value and str(row.get("supplier_product_code") or "").strip().lower() == code_value), None)
    if isinstance(exact_code, dict):
        out = dict(exact_code)
        out["confidence"] = "high"
        out["confidence_score"] = 0.92
        out["reason"] = "Código do fornecedor coincide com vínculo anterior"
        out["source"] = "supplier_product_code"
        return out
    by_name = next((row for row in rows if name_value and name_value == str(row.get("supplier_product_name") or "").strip().lower()), None)
    if isinstance(by_name, dict):
        out = dict(by_name)
        out["confidence"] = "medium"
        out["confidence_score"] = 0.75
        out["reason"] = "Descrição fiscal coincide com histórico do fornecedor"
        out["source"] = "supplier_product_name"
        return out
    similar = next(
        (
            row
            for row in rows
            if name_value
            and name_value in str(row.get("supplier_product_name") or "").strip().lower()
        ),
        None,
    )
    if isinstance(similar, dict):
        out = dict(similar)
        out["confidence"] = "low"
        out["confidence_score"] = 0.45
        out["reason"] = "Descrição semelhante com histórico compatível"
        out["source"] = "name_similarity"
        return out
    return None


def bind_note_item(
    *,
    access_key: str,
    item_index: int,
    supplier_id: str,
    product_id: str,
    supplier_product_code: str,
    supplier_product_name: str,
    unidade_fornecedor: str,
    unidade_estoque: str,
    fator_conversao: float,
    is_preferred: bool,
    suggestion_used: bool = False,
    suggestion_modified: bool = False,
    item_match_source: str = "",
    accepted_conversion: bool = False,
) -> bool:
    key_value = str(access_key or "").strip()
    supplier_value = str(supplier_id or "").strip()
    product_value = str(product_id or "").strip()
    if not key_value or item_index < 0 or not supplier_value or not product_value:
        return False
    changed = False
    with file_lock(NFE_REPOSITORY_FILE):
        data = _load_data()
        notes = data.get("notes") if isinstance(data.get("notes"), list) else []
        bindings = data.get("item_bindings") if isinstance(data.get("item_bindings"), list) else []
        for note in notes:
            if not isinstance(note, dict):
                continue
            if str(note.get("chave_nfe") or "") != key_value:
                continue
            mappings = note.get("item_mappings") if isinstance(note.get("item_mappings"), list) else []
            mappings = [row for row in mappings if not (isinstance(row, dict) and int(row.get("item_index") or -1) == int(item_index))]
            mapping = {
                "item_index": int(item_index),
                "supplier_id": supplier_value,
                "product_id": product_value,
                "supplier_product_code": str(supplier_product_code or ""),
                "supplier_product_name": str(supplier_product_name or ""),
                "unidade_fornecedor": str(unidade_fornecedor or ""),
                "unidade_estoque": str(unidade_estoque or ""),
                "fator_conversao": float(fator_conversao or 1.0),
                "is_preferred": bool(is_preferred),
                "status": "linked",
                "suggestion_used": bool(suggestion_used),
                "suggestion_modified": bool(suggestion_modified),
                "item_match_source": str(item_match_source or ""),
                "accepted_conversion": bool(accepted_conversion),
                "updated_at": _now_iso(),
            }
            mappings.append(mapping)
            note["item_mappings"] = mappings
            note["last_seen_at"] = _now_iso()
            changed = True
            break
        if changed:
            binding_row = {
                "id": uuid.uuid4().hex,
                "supplier_id": supplier_value,
                "product_id": product_value,
                "supplier_product_code": str(supplier_product_code or ""),
                "supplier_product_name": str(supplier_product_name or ""),
                "unidade_fornecedor": str(unidade_fornecedor or ""),
                "unidade_estoque": str(unidade_estoque or ""),
                "fator_conversao": float(fator_conversao or 1.0),
                "is_preferred": bool(is_preferred),
                "item_match_source": str(item_match_source or ""),
                "last_used_at": _now_iso(),
            }
            bindings = [
                row
                for row in bindings
                if not (
                    isinstance(row, dict)
                    and str(row.get("supplier_id") or "") == supplier_value
                    and str(row.get("product_id") or "") == product_value
                    and str(row.get("supplier_product_code") or "").strip().lower() == str(supplier_product_code or "").strip().lower()
                )
            ]
            bindings.append(binding_row)
            data["item_bindings"] = bindings
            _save_data(data)
    return changed


def update_note_item_review_status(*, access_key: str, item_index: int, status: str) -> bool:
    key_value = str(access_key or "").strip()
    status_value = str(status or "").strip().lower()
    if not key_value or int(item_index) < 0:
        return False
    if status_value not in {"pending", "linked", "conferido", "divergente"}:
        return False
    changed = False
    with file_lock(NFE_REPOSITORY_FILE):
        data = _load_data()
        notes = data.get("notes") if isinstance(data.get("notes"), list) else []
        for note in notes:
            if not isinstance(note, dict):
                continue
            if str(note.get("chave_nfe") or "") != key_value:
                continue
            mappings = note.get("item_mappings") if isinstance(note.get("item_mappings"), list) else []
            target = next(
                (
                    row
                    for row in mappings
                    if isinstance(row, dict) and int(row.get("item_index") or -1) == int(item_index)
                ),
                None,
            )
            if not isinstance(target, dict):
                target = {
                    "item_index": int(item_index),
                    "supplier_id": str(note.get("supplier_id") or ""),
                    "product_id": "",
                    "supplier_product_code": "",
                    "supplier_product_name": "",
                    "unidade_fornecedor": "",
                    "unidade_estoque": "",
                    "fator_conversao": 1.0,
                    "is_preferred": False,
                    "status": "pending",
                    "suggestion_used": False,
                    "suggestion_modified": False,
                    "item_match_source": "",
                    "accepted_conversion": False,
                    "updated_at": _now_iso(),
                }
                mappings.append(target)
            target["status"] = status_value
            target["updated_at"] = _now_iso()
            note["item_mappings"] = mappings
            note["last_seen_at"] = _now_iso()
            changed = True
            break
        if changed:
            _save_data(data)
    return changed


def _classify_item_confidence(suggestion: Optional[Dict[str, Any]], unidade_fiscal: str, unidade_estoque: str) -> Dict[str, Any]:
    if not isinstance(suggestion, dict):
        return {"label": "Baixa", "score": 0.2}
    score = float(suggestion.get("confidence_score") or 0.2)
    if unidade_fiscal and unidade_estoque and unidade_fiscal.strip().lower() != unidade_estoque.strip().lower():
        score = max(0.1, score - 0.15)
    if score >= 0.8:
        label = "Alta"
    elif score >= 0.5:
        label = "Média"
    else:
        label = "Baixa"
    return {"label": label, "score": score}


def analyze_note_conference_assist(*, note: Dict[str, Any], parsed_items: List[Dict[str, Any]], supplier_id: str) -> Dict[str, Any]:
    items = parsed_items if isinstance(parsed_items, list) else []
    supplier_value = str(supplier_id or note.get("supplier_id") or "").strip()
    item_rows = []
    low_confidence_count = 0
    linked_count = 0
    divergence_count = 0
    pending_count = 0
    for idx, item in enumerate(items):
        code = str(item.get("code") or "")
        name = str(item.get("name") or "")
        unit = str(item.get("unit") or "")
        suggestion = suggest_item_binding(
            supplier_id=supplier_value,
            supplier_product_code=code,
            supplier_product_name=name,
        ) if supplier_value else None
        unidade_estoque = str((suggestion or {}).get("unidade_estoque") or "")
        confidence = _classify_item_confidence(suggestion, unit, unidade_estoque)
        divergence_level = ""
        divergence_reason = ""
        if not suggestion:
            divergence_level = "revisar"
            divergence_reason = "Sem vínculo com insumo"
            pending_count += 1
        elif unit and unidade_estoque and unit.strip().lower() != unidade_estoque.strip().lower() and float((suggestion or {}).get("fator_conversao") or 0) <= 0:
            divergence_level = "bloqueante"
            divergence_reason = "Conversão ausente"
            divergence_count += 1
        else:
            linked_count += 1
        if confidence["label"] == "Baixa":
            low_confidence_count += 1
        item_rows.append(
            {
                "item_index": idx,
                "suggestion": suggestion,
                "confidence": confidence,
                "divergence_level": divergence_level,
                "divergence_reason": divergence_reason,
                "status": "linked" if suggestion else "pending",
            }
        )
    summary = {
        "supplier_identified": bool(str(note.get("supplier_id") or "").strip() or str(supplier_value).strip()),
        "items_total": len(items),
        "items_linked": linked_count,
        "items_pending_review": pending_count,
        "items_low_confidence": low_confidence_count,
        "items_divergence": divergence_count,
        "cta": "Pronto para conferência" if pending_count == 0 and divergence_count == 0 else "Revisão necessária antes de lançar",
    }
    return {"items": item_rows, "summary": summary}


def create_manual_entry(
    *,
    supplier_id: str,
    supplier_name: str,
    document_type: str,
    document_number: str,
    observation: str,
    entry_date: str,
    items: List[Dict[str, Any]],
    created_by: str,
) -> Dict[str, Any]:
    item_rows = items if isinstance(items, list) else []
    normalized_items = []
    total_cost = 0.0
    for row in item_rows:
        if not isinstance(row, dict):
            continue
        qty = float(row.get("qty") or 0)
        cost = float(row.get("cost") or row.get("price") or 0)
        conversion_factor = float(row.get("conversion_factor") or 1)
        total_cost += qty * cost
        normalized_items.append(
            {
                "name": str(row.get("name") or row.get("product_name") or "").strip(),
                "product_id": str(row.get("product_id") or "").strip(),
                "item_nature": "asset_item" if str(row.get("item_nature") or "").strip().lower() == "asset_item" else "stock_item",
                "qty": qty,
                "unit": str(row.get("unit") or "").strip(),
                "base_unit": str(row.get("base_unit") or "").strip(),
                "conversion_factor": conversion_factor if conversion_factor > 0 else 1.0,
                "cost": cost,
                "divergence_note": str(row.get("divergence_note") or "").strip(),
            }
        )
    requested_status = str(document_type or "").strip().lower()
    status_value = requested_status if requested_status in {"draft", "received_not_stocked", "approved_for_stock", "imported", "imported_asset", "canceled"} else "draft"
    destination_type = "asset" if status_value == "imported_asset" else ("stock" if status_value == "imported" else "")
    created = {
        "id": uuid.uuid4().hex,
        "origin_type": "manual",
        "origin_type_v2": "manual_entry",
        "supplier_id": str(supplier_id or "").strip(),
        "supplier_name": str(supplier_name or "").strip(),
        "document_type": "manual_entry",
        "document_number": str(document_number or "").strip(),
        "observation": str(observation or "").strip(),
        "entry_date": str(entry_date or datetime.now().strftime("%Y-%m-%d")),
        "items": normalized_items,
        "status": status_value,
        "status_conferencia": "conferenced" if status_value in {"received_not_stocked", "approved_for_stock", "imported"} else "pending_conference",
        "status_importacao": "imported" if status_value == "imported" else "pending",
        "receipt_status": status_value if status_value in {"received_not_stocked", "approved_for_stock"} else ("stocked" if status_value in {"imported", "imported_asset"} else "draft"),
        "approved_for_stock": status_value in {"approved_for_stock", "imported", "imported_asset"},
        "stock_applied": status_value == "imported",
        "financial_trace": status_value in {"received_not_stocked", "approved_for_stock", "imported", "imported_asset"},
        "destination_type": destination_type,
        "destination_id": "",
        "total_cost": round(total_cost, 2),
        "created_at": _now_iso(),
        "created_by": str(created_by or "unknown"),
        "imported_at": "",
        "approved_at": "",
        "approved_by": "",
    }
    with file_lock(NFE_REPOSITORY_FILE):
        data = _load_data()
        rows = data.get("manual_entries") if isinstance(data.get("manual_entries"), list) else []
        rows.append(created)
        data["manual_entries"] = rows
        _save_data(data)
    return created


def list_manual_entries(*, status: str = "", supplier: str = "", limit: int = 500) -> List[Dict[str, Any]]:
    status_filter = str(status or "").strip().lower()
    supplier_filter = str(supplier or "").strip().lower()
    with file_lock(NFE_REPOSITORY_FILE):
        data = _load_data()
        rows = data.get("manual_entries") if isinstance(data.get("manual_entries"), list) else []
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        current_status = str(row.get("status") or "manual_entry").strip().lower()
        supplier_name = str(row.get("supplier_name") or "").strip().lower()
        if status_filter and status_filter != current_status:
            continue
        if supplier_filter and supplier_filter not in supplier_name:
            continue
        out.append(dict(row))
    out.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
    return out[: max(1, int(limit))]


def update_manual_entry_status(entry_id: str, status: str, updated_by: str = "", reason: str = "") -> bool:
    entry_value = str(entry_id or "").strip()
    status_value = str(status or "").strip().lower()
    if status_value not in {"draft", "received_not_stocked", "approved_for_stock", "imported", "imported_asset", "canceled", "rejected", "manual_entry", "conferenced"}:
        return False
    changed = False
    with file_lock(NFE_REPOSITORY_FILE):
        data = _load_data()
        rows = data.get("manual_entries") if isinstance(data.get("manual_entries"), list) else []
        for row in rows:
            if not isinstance(row, dict):
                continue
            if str(row.get("id") or "") != entry_value:
                continue
            mapped_status = "draft" if status_value == "manual_entry" else ("approved_for_stock" if status_value == "conferenced" else status_value)
            row["status"] = mapped_status
            row["status_conferencia"] = "conferenced" if mapped_status in {"received_not_stocked", "approved_for_stock", "imported"} else "pending_conference"
            row["status_importacao"] = "imported" if mapped_status == "imported" else "pending"
            row["receipt_status"] = mapped_status if mapped_status in {"received_not_stocked", "approved_for_stock"} else ("stocked" if mapped_status in {"imported", "imported_asset"} else "draft")
            row["approved_for_stock"] = mapped_status in {"approved_for_stock", "imported", "imported_asset"}
            row["stock_applied"] = mapped_status == "imported"
            row["financial_trace"] = mapped_status in {"received_not_stocked", "approved_for_stock", "imported", "imported_asset"}
            row["destination_type"] = "asset" if mapped_status == "imported_asset" else ("stock" if mapped_status == "imported" else str(row.get("destination_type") or ""))
            row["updated_by"] = str(updated_by or row.get("updated_by") or "")
            row["updated_reason"] = str(reason or row.get("updated_reason") or "")
            row["updated_at"] = _now_iso()
            if mapped_status == "rejected":
                row["rejected_at"] = _now_iso()
                row["rejected_by"] = str(updated_by or "")
                row["rejection_reason"] = str(reason or "")
                row["approved_for_stock"] = False
            if mapped_status == "imported":
                row["imported_at"] = _now_iso()
            if mapped_status == "imported_asset":
                row["imported_at"] = _now_iso()
            if mapped_status == "approved_for_stock":
                row["approved_at"] = _now_iso()
                row["approved_by"] = str(updated_by or row.get("approved_by") or "")
            changed = True
            break
        if changed:
            _save_data(data)
    return changed


def get_manual_entry_by_id(entry_id: str) -> Optional[Dict[str, Any]]:
    entry_value = str(entry_id or "").strip()
    if not entry_value:
        return None
    with file_lock(NFE_REPOSITORY_FILE):
        data = _load_data()
        rows = data.get("manual_entries") if isinstance(data.get("manual_entries"), list) else []
        for row in rows:
            if not isinstance(row, dict):
                continue
            if str(row.get("id") or "") == entry_value:
                return dict(row)
    return None


def update_manual_entry_draft(
    *,
    entry_id: str,
    supplier_id: str,
    supplier_name: str,
    document_number: str,
    observation: str,
    entry_date: str,
    items: List[Dict[str, Any]],
    updated_by: str,
    updated_reason: str = "",
) -> Optional[Dict[str, Any]]:
    entry_value = str(entry_id or "").strip()
    if not entry_value:
        return None
    normalized_items = []
    total_cost = 0.0
    for row in (items if isinstance(items, list) else []):
        if not isinstance(row, dict):
            continue
        qty = float(row.get("qty") or 0)
        cost = float(row.get("cost") or row.get("price") or 0)
        conversion_factor = float(row.get("conversion_factor") or 1)
        normalized_items.append(
            {
                "name": str(row.get("name") or row.get("product_name") or "").strip(),
                "product_id": str(row.get("product_id") or "").strip(),
                "item_nature": "asset_item" if str(row.get("item_nature") or "").strip().lower() == "asset_item" else "stock_item",
                "qty": qty,
                "unit": str(row.get("unit") or "").strip(),
                "base_unit": str(row.get("base_unit") or "").strip(),
                "conversion_factor": conversion_factor if conversion_factor > 0 else 1.0,
                "cost": cost,
                "divergence_note": str(row.get("divergence_note") or "").strip(),
            }
        )
        total_cost += qty * cost
    if not normalized_items:
        return None
    now_iso = _now_iso()
    updated = None
    with file_lock(NFE_REPOSITORY_FILE):
        data = _load_data()
        rows = data.get("manual_entries") if isinstance(data.get("manual_entries"), list) else []
        for row in rows:
            if not isinstance(row, dict):
                continue
            if str(row.get("id") or "") != entry_value:
                continue
            if str(row.get("status") or "").strip().lower() != "draft":
                return None
            old_supplier = str(row.get("supplier_name") or "")
            old_count = len(row.get("items") if isinstance(row.get("items"), list) else [])
            row["supplier_id"] = str(supplier_id or "").strip()
            row["supplier_name"] = str(supplier_name or "").strip()
            row["document_number"] = str(document_number or "").strip()
            row["observation"] = str(observation or "").strip()
            row["entry_date"] = str(entry_date or row.get("entry_date") or datetime.now().strftime("%Y-%m-%d"))
            row["items"] = normalized_items
            row["total_cost"] = round(total_cost, 2)
            row["updated_at"] = now_iso
            row["updated_by"] = str(updated_by or "")
            row["updated_reason"] = str(updated_reason or "")
            row["edit_count"] = int(row.get("edit_count") or 0) + 1
            trail = row.get("audit_trail") if isinstance(row.get("audit_trail"), list) else []
            trail.append(
                {
                    "at": now_iso,
                    "event": "manual_draft_updated",
                    "by": str(updated_by or ""),
                    "reason": str(updated_reason or ""),
                    "summary": {
                        "supplier_before": old_supplier,
                        "supplier_after": str(row.get("supplier_name") or ""),
                        "items_before": int(old_count),
                        "items_after": len(normalized_items),
                        "total_cost": round(total_cost, 2),
                    },
                }
            )
            row["audit_trail"] = trail[-200:]
            updated = dict(row)
            break
        if updated is not None:
            _save_data(data)
    return updated


def register_manual_entry_stock_application(
    *,
    entry_id: str,
    stock_entry_ids: List[str],
    applied_by: str,
    total_cost: float,
    approved_by: str = "",
    destination_type: str = "stock",
    destination_id: str = "",
) -> bool:
    entry_value = str(entry_id or "").strip()
    if not entry_value:
        return False
    changed = False
    now_iso = _now_iso()
    with file_lock(NFE_REPOSITORY_FILE):
        data = _load_data()
        rows = data.get("manual_entries") if isinstance(data.get("manual_entries"), list) else []
        for row in rows:
            if not isinstance(row, dict):
                continue
            if str(row.get("id") or "") != entry_value:
                continue
            row["status"] = "imported"
            if str(destination_type or "").strip().lower() == "asset":
                row["status"] = "imported_asset"
            row["status_importacao"] = "imported"
            row["status_conferencia"] = "conferenced"
            row["stock_applied"] = str(destination_type or "").strip().lower() != "asset"
            row["approved_for_stock"] = True
            row["receipt_status"] = "stocked"
            row["financial_trace"] = True
            row["destination_type"] = "asset" if str(destination_type or "").strip().lower() == "asset" else "stock"
            row["destination_id"] = str(destination_id or "")
            row["total_cost"] = float(total_cost or row.get("total_cost") or 0.0)
            row["stock_entry_ids"] = [str(x) for x in (stock_entry_ids or []) if str(x).strip()]
            row["imported_at"] = now_iso
            row["approved_at"] = str(row.get("approved_at") or now_iso)
            row["approved_by"] = str(approved_by or row.get("approved_by") or applied_by or "")
            row["updated_by"] = str(applied_by or "")
            row["updated_at"] = now_iso
            changed = True
            break
        if changed:
            _save_data(data)
    return changed


def _start_sync(data: Dict[str, Any], *, method: str, initiated_by: str, correlation_id: str) -> Tuple[bool, str]:
    state = data.get("sync_state") if isinstance(data.get("sync_state"), dict) else _default_sync_state()
    now = datetime.now()
    cooldown_ate = str(state.get("cooldown_ate") or "")
    if cooldown_ate:
        try:
            cooldown_dt = datetime.fromisoformat(cooldown_ate)
            if now < cooldown_dt:
                remaining = int((cooldown_dt - now).total_seconds() // 60)
                return False, f"Integração em cooldown. Aguarde {max(1, remaining)} minutos."
        except Exception:
            pass
    if bool(state.get("lock_ativo")):
        lock_started = str(state.get("lock_started_at") or "")
        if lock_started:
            try:
                lock_dt = datetime.fromisoformat(lock_started)
                if (now - lock_dt).total_seconds() < 180:
                    return False, "Sincronização já em andamento. Aguarde finalizar."
            except Exception:
                pass
    state["lock_ativo"] = True
    state["lock_started_at"] = _now_iso()
    state["ultima_consulta_em"] = _now_iso()
    state["last_method"] = str(method or "lastNSU")
    state["last_correlation_id"] = str(correlation_id or "")
    state["initiated_by"] = str(initiated_by or "system")
    data["sync_state"] = state
    return True, ""


def _finish_sync(
    data: Dict[str, Any],
    *,
    success: bool,
    error_message: str,
    method: str,
    correlation_id: str,
    nsu_final: str,
) -> None:
    state = data.get("sync_state") if isinstance(data.get("sync_state"), dict) else _default_sync_state()
    state["lock_ativo"] = False
    state["lock_started_at"] = ""
    state["last_method"] = str(method or state.get("last_method") or "")
    state["last_correlation_id"] = str(correlation_id or state.get("last_correlation_id") or "")
    if nsu_final:
        state["ultimo_nsu_processado"] = nsu_final
        state["max_nsu_recebido"] = nsu_final
    if success:
        state["ultimo_sucesso_em"] = _now_iso()
        state["ultimo_erro_em"] = ""
        state["ultimo_erro_resumo"] = ""
    else:
        state["ultimo_erro_em"] = _now_iso()
        state["ultimo_erro_resumo"] = str(error_message or "Falha de integração")
    data["sync_state"] = state


def _set_cooldown_if_needed(data: Dict[str, Any], error_message: str) -> int:
    message = str(error_message or "").strip().lower()
    state = data.get("sync_state") if isinstance(data.get("sync_state"), dict) else _default_sync_state()
    minutes = 0
    if "consumo indevido" in message or "656" in message:
        minutes = 60
    elif "137" in message or "sem novos documentos" in message:
        minutes = 60
    elif "timeout" in message or "conex" in message or "tempor" in message:
        minutes = 15
    if minutes > 0:
        state["cooldown_ate"] = (datetime.now() + timedelta(minutes=minutes)).isoformat()
    data["sync_state"] = state
    return minutes


def _ingest_documents_in_data(
    data: Dict[str, Any],
    *,
    documents: List[Dict[str, Any]],
    source_method: str,
    correlation_id: str,
) -> Dict[str, Any]:
    docs = documents if isinstance(documents, list) else []
    notes_original = data.get("notes") if isinstance(data.get("notes"), list) else []
    notes_staged: List[Dict[str, Any]] = [dict(row) for row in notes_original if isinstance(row, dict)]
    seen_by_key = {str(note.get("chave_nfe") or "") for note in notes_staged if str(note.get("chave_nfe") or "")}
    seen_by_nsu = {str(note.get("nsu") or "") for note in notes_staged if str(note.get("nsu") or "")}
    staged_nsu_values = [_safe_nsu_to_int(row.get("nsu")) for row in notes_staged]
    staged_nsu_values = [v for v in staged_nsu_values if isinstance(v, int)]
    per_doc: List[Dict[str, Any]] = []
    new_count = 0
    duplicate_count = 0
    error_count = 0
    highest_nsu = _safe_nsu_to_int(data.get("sync_state", {}).get("ultimo_nsu_processado"))
    highest_nsu = highest_nsu if highest_nsu is not None else 0

    for doc in docs:
        if not isinstance(doc, dict):
            error_count += 1
            per_doc.append({"nsu": "", "chave_nfe": "", "status": "erro", "reason": "documento inválido"})
            continue
        item = _build_note_from_document(doc, source_method, correlation_id)
        nsu_value = str(item.get("nsu") or "").strip()
        chave_value = str(item.get("chave_nfe") or "").strip()
        xml_raw = str(item.get("xml_raw") or "")
        if not nsu_value or not nsu_value.isdigit():
            error_count += 1
            per_doc.append({"nsu": nsu_value, "chave_nfe": chave_value, "status": "erro", "reason": "nsu inválido"})
            continue
        if not chave_value:
            error_count += 1
            per_doc.append({"nsu": nsu_value, "chave_nfe": "", "status": "erro", "reason": "chave ausente"})
            continue
        if not xml_raw:
            error_count += 1
            per_doc.append({"nsu": nsu_value, "chave_nfe": chave_value, "status": "erro", "reason": "xml ausente"})
            continue
        if nsu_value in seen_by_nsu:
            duplicate_count += 1
            existing = _find_note(notes_staged, nsu_value, chave_value)
            if isinstance(existing, dict):
                _upgrade_existing_note_snapshot(existing, item)
            per_doc.append({"nsu": nsu_value, "chave_nfe": chave_value, "status": "duplicado", "reason": "nsu já existe"})
            nsu_int = int(nsu_value)
            if nsu_int > highest_nsu:
                highest_nsu = nsu_int
            continue
        if chave_value in seen_by_key:
            duplicate_count += 1
            existing = _find_note(notes_staged, nsu_value, chave_value)
            if isinstance(existing, dict):
                _upgrade_existing_note_snapshot(existing, item)
            per_doc.append({"nsu": nsu_value, "chave_nfe": chave_value, "status": "duplicado", "reason": "chave já existe"})
            nsu_int = int(nsu_value)
            if nsu_int > highest_nsu:
                highest_nsu = nsu_int
            continue
        notes_staged.append(item)
        seen_by_nsu.add(nsu_value)
        seen_by_key.add(chave_value)
        nsu_int = int(nsu_value)
        staged_nsu_values.append(nsu_int)
        if nsu_int > highest_nsu:
            highest_nsu = nsu_int
        new_count += 1
        per_doc.append({"nsu": nsu_value, "chave_nfe": chave_value, "status": "novo", "reason": ""})

    if error_count > 0:
        return {
            "ok": False,
            "new": new_count,
            "duplicates": duplicate_count,
            "errors": error_count,
            "per_doc": per_doc,
            "highest_nsu": str(highest_nsu),
            "gaps_detected": [],
        }

    state = data.get("sync_state") if isinstance(data.get("sync_state"), dict) else _default_sync_state()
    state["ultimo_nsu_processado"] = str(highest_nsu)
    state["max_nsu_recebido"] = str(highest_nsu)
    data["sync_state"] = state
    data["notes"] = notes_staged
    detected_gaps = _detect_nsu_gaps_values(staged_nsu_values)
    existing_gaps = data.get("nsu_gaps") if isinstance(data.get("nsu_gaps"), list) else []
    data["nsu_gaps"] = _merge_unique_gaps(existing_gaps, detected_gaps)
    return {
        "ok": True,
        "new": new_count,
        "duplicates": duplicate_count,
        "errors": 0,
        "per_doc": per_doc,
        "highest_nsu": str(highest_nsu),
        "gaps_detected": [str(g) for g in detected_gaps],
    }


def ingest_documents(
    *,
    documents: List[Dict[str, Any]],
    source_method: str,
    correlation_id: str,
) -> Dict[str, Any]:
    with file_lock(NFE_REPOSITORY_FILE):
        data = _load_data()
        result = _ingest_documents_in_data(
            data,
            documents=documents,
            source_method=source_method,
            correlation_id=correlation_id,
        )
        _save_data(data)
    return result


def synchronize_last_nsu(*, settings: Dict[str, Any], initiated_by: str) -> Dict[str, Any]:
    from app.services.fiscal_service import list_received_nfes

    correlation_id = uuid.uuid4().hex
    with file_lock(NFE_REPOSITORY_FILE):
        data = _load_data()
        ok, reason = _start_sync(
            data,
            method="lastNSU",
            initiated_by=initiated_by,
            correlation_id=correlation_id,
        )
        if not ok:
            return {"success": False, "error": reason, "correlation_id": correlation_id}
        _save_data(data)

    started_at = datetime.now()
    documents = None
    error = None
    try:
        documents, error = list_received_nfes(settings)
    except Exception as exc:
        error = str(exc)
    with file_lock(NFE_REPOSITORY_FILE):
        data = _load_data()
        state_before = data.get("sync_state") if isinstance(data.get("sync_state"), dict) else {}
        ult_nsu_sent = str(state_before.get("ultimo_nsu_processado") or "0")
        if error:
            cooldown_minutes = _set_cooldown_if_needed(data, str(error))
            error_kind = "rate_limit" if ("656" in str(error) or "consumo indevido" in str(error).lower()) else (
                "no_documents" if "137" in str(error) else "transport"
            )
            success_flag = error_kind == "no_documents"
            _finish_sync(
                data,
                success=success_flag,
                error_message=str(error),
                method="lastNSU",
                correlation_id=correlation_id,
                nsu_final=str(data.get("sync_state", {}).get("ultimo_nsu_processado") or ""),
            )
            _append_sync_audit(
                data,
                {
                    "id": uuid.uuid4().hex,
                    "correlation_id": correlation_id,
                    "method": "lastNSU",
                    "started_at": started_at.isoformat(),
                    "finished_at": _now_iso(),
                    "duration_ms": int((datetime.now() - started_at).total_seconds() * 1000),
                    "ult_nsu_enviado": ult_nsu_sent,
                    "max_nsu_recebido": str(data.get("sync_state", {}).get("max_nsu_recebido") or ult_nsu_sent),
                    "documents_count": 0,
                    "nsus_processados": [],
                    "nsus_ignorados": [],
                    "gaps_detected": [],
                    "result": "no_documents" if success_flag else "error",
                    "error": str(error),
                    "cooldown_minutes": cooldown_minutes,
                    "initiated_by": str(initiated_by or "unknown"),
                },
            )
            _save_data(data)
            if success_flag:
                return {"success": True, "synced_count": 0, "ignored_count": 0, "error_count": 0, "correlation_id": correlation_id, "message": "Sem novos documentos (cStat 137)."}
            return {"success": False, "error": str(error), "correlation_id": correlation_id}
        ingest_result = _ingest_documents_in_data(
            data,
            documents=documents or [],
            source_method="lastNSU",
            correlation_id=correlation_id,
        )
        if not bool(ingest_result.get("ok")):
            _finish_sync(
                data,
                success=False,
                error_message="Falha parcial no lote. Checkpoint preservado para reprocessamento seguro.",
                method="lastNSU",
                correlation_id=correlation_id,
                nsu_final=ult_nsu_sent,
            )
            _append_sync_audit(
                data,
                {
                    "id": uuid.uuid4().hex,
                    "correlation_id": correlation_id,
                    "method": "lastNSU",
                    "started_at": started_at.isoformat(),
                    "finished_at": _now_iso(),
                    "duration_ms": int((datetime.now() - started_at).total_seconds() * 1000),
                    "ult_nsu_enviado": ult_nsu_sent,
                    "max_nsu_recebido": str(ingest_result.get("highest_nsu") or ult_nsu_sent),
                    "documents_count": len(documents or []),
                    "nsus_processados": [row.get("nsu") for row in ingest_result.get("per_doc", []) if row.get("status") == "novo"],
                    "nsus_ignorados": [row.get("nsu") for row in ingest_result.get("per_doc", []) if row.get("status") == "duplicado"],
                    "gaps_detected": [],
                    "result": "error",
                    "error": "Lote inválido. Checkpoint não avançado.",
                    "cooldown_minutes": 0,
                    "initiated_by": str(initiated_by or "unknown"),
                },
            )
            _save_data(data)
            return {"success": False, "error": "Falha parcial no lote. Checkpoint não avançado.", "correlation_id": correlation_id}
        nsu_final = str(data.get("sync_state", {}).get("ultimo_nsu_processado") or "")
        if int(ingest_result.get("new") or 0) == 0:
            _set_cooldown_if_needed(data, "137 sem novos documentos")
        _finish_sync(
            data,
            success=True,
            error_message="",
            method="lastNSU",
            correlation_id=correlation_id,
            nsu_final=nsu_final,
        )
        _append_sync_audit(
            data,
            {
                "id": uuid.uuid4().hex,
                "correlation_id": correlation_id,
                "method": "lastNSU",
                "started_at": started_at.isoformat(),
                "finished_at": _now_iso(),
                "duration_ms": int((datetime.now() - started_at).total_seconds() * 1000),
                "ult_nsu_enviado": ult_nsu_sent,
                "max_nsu_recebido": str(ingest_result.get("highest_nsu") or nsu_final),
                "documents_count": len(documents or []),
                "nsus_processados": [row.get("nsu") for row in ingest_result.get("per_doc", []) if row.get("status") == "novo"],
                "nsus_ignorados": [row.get("nsu") for row in ingest_result.get("per_doc", []) if row.get("status") == "duplicado"],
                "gaps_detected": ingest_result.get("gaps_detected") or [],
                "result": "success",
                "error": "",
                "cooldown_minutes": 60 if int(ingest_result.get("new") or 0) == 0 else 0,
                "initiated_by": str(initiated_by or "unknown"),
            },
        )
        _save_data(data)
    return {
        "success": True,
        "synced_count": int(ingest_result.get("new") or 0),
        "ignored_count": int(ingest_result.get("duplicates") or 0),
        "error_count": int(ingest_result.get("errors") or 0),
        "correlation_id": correlation_id,
    }


def synchronize_specific_nsu(*, settings: Dict[str, Any], nsu: str, initiated_by: str) -> Dict[str, Any]:
    from app.services.fiscal_service import recover_missing_notes

    nsu_value = str(nsu or "").strip()
    if not nsu_value.isdigit():
        return {"success": False, "error": "NSU inválido.", "correlation_id": ""}
    correlation_id = uuid.uuid4().hex
    with file_lock(NFE_REPOSITORY_FILE):
        data = _load_data()
        ok, reason = _start_sync(
            data,
            method="nsu_specific",
            initiated_by=initiated_by,
            correlation_id=correlation_id,
        )
        if not ok:
            return {"success": False, "error": reason, "correlation_id": correlation_id}
        _save_data(data)
    started_at = datetime.now()
    docs = None
    error = None
    try:
        docs, error = recover_missing_notes(nsu_value, nsu_value, settings)
    except Exception as exc:
        error = str(exc)
    with file_lock(NFE_REPOSITORY_FILE):
        data = _load_data()
        state_before = data.get("sync_state") if isinstance(data.get("sync_state"), dict) else {}
        ult_nsu_sent = str(state_before.get("ultimo_nsu_processado") or "0")
        if error:
            cooldown_minutes = _set_cooldown_if_needed(data, str(error))
            is_137 = "137" in str(error)
            _finish_sync(
                data,
                success=bool(is_137),
                error_message="" if is_137 else str(error),
                method="nsu_specific",
                correlation_id=correlation_id,
                nsu_final=str(data.get("sync_state", {}).get("ultimo_nsu_processado") or ""),
            )
            _register_gap_verification(
                data,
                nsu=nsu_value,
                outcome="no_document_137" if is_137 else "transient_error",
                correlation_id=correlation_id,
                message=str(error),
            )
            _append_sync_audit(
                data,
                {
                    "id": uuid.uuid4().hex,
                    "correlation_id": correlation_id,
                    "method": "nsu_specific",
                    "started_at": started_at.isoformat(),
                    "finished_at": _now_iso(),
                    "duration_ms": int((datetime.now() - started_at).total_seconds() * 1000),
                    "ult_nsu_enviado": ult_nsu_sent,
                    "max_nsu_recebido": str(data.get("sync_state", {}).get("max_nsu_recebido") or ult_nsu_sent),
                    "documents_count": 0,
                    "nsus_processados": [],
                    "nsus_ignorados": [nsu_value] if is_137 else [],
                    "gaps_detected": [],
                    "result": "no_documents" if is_137 else "error",
                    "error": "" if is_137 else str(error),
                    "cooldown_minutes": cooldown_minutes,
                    "initiated_by": str(initiated_by or "unknown"),
                },
            )
            _save_data(data)
            if is_137:
                return {
                    "success": True,
                    "synced_count": 0,
                    "ignored_count": 0,
                    "error_count": 0,
                    "correlation_id": correlation_id,
                    "verification_outcome": "no_document_137",
                    "message": "NSU sem documento (cStat 137). Gap tratado como provavelmente ignorável.",
                }
            return {"success": False, "error": str(error), "correlation_id": correlation_id, "verification_outcome": "transient_error"}
        ingest_result = _ingest_documents_in_data(
            data,
            documents=docs or [],
            source_method="nsu_specific",
            correlation_id=correlation_id,
        )
        if not bool(ingest_result.get("ok")):
            _register_gap_verification(
                data,
                nsu=nsu_value,
                outcome="partial_error",
                correlation_id=correlation_id,
                message="Falha parcial na recuperação assistida",
            )
            _finish_sync(
                data,
                success=False,
                error_message="Falha parcial no lote de recuperação. Checkpoint preservado.",
                method="nsu_specific",
                correlation_id=correlation_id,
                nsu_final=ult_nsu_sent,
            )
            _append_sync_audit(
                data,
                {
                    "id": uuid.uuid4().hex,
                    "correlation_id": correlation_id,
                    "method": "nsu_specific",
                    "started_at": started_at.isoformat(),
                    "finished_at": _now_iso(),
                    "duration_ms": int((datetime.now() - started_at).total_seconds() * 1000),
                    "ult_nsu_enviado": ult_nsu_sent,
                    "max_nsu_recebido": str(ingest_result.get("highest_nsu") or ult_nsu_sent),
                    "documents_count": len(docs or []),
                    "nsus_processados": [],
                    "nsus_ignorados": [],
                    "gaps_detected": [],
                    "result": "error",
                    "error": "Falha parcial em recuperação assistida",
                    "cooldown_minutes": 0,
                    "initiated_by": str(initiated_by or "unknown"),
                },
            )
            _save_data(data)
            return {
                "success": False,
                "error": "Falha parcial na recuperação assistida.",
                "correlation_id": correlation_id,
                "verification_outcome": "partial_error",
            }
        verification_outcome = "inconclusive"
        if int(ingest_result.get("new") or 0) > 0:
            verification_outcome = "recovered_document"
        elif int(ingest_result.get("duplicates") or 0) > 0:
            verification_outcome = "duplicate_document"
        _register_gap_verification(
            data,
            nsu=nsu_value,
            outcome=verification_outcome,
            correlation_id=correlation_id,
            message="Recuperação assistida executada",
        )
        nsu_final = str(data.get("sync_state", {}).get("ultimo_nsu_processado") or "")
        _finish_sync(
            data,
            success=True,
            error_message="",
            method="nsu_specific",
            correlation_id=correlation_id,
            nsu_final=nsu_final,
        )
        _append_sync_audit(
            data,
            {
                "id": uuid.uuid4().hex,
                "correlation_id": correlation_id,
                "method": "nsu_specific",
                "started_at": started_at.isoformat(),
                "finished_at": _now_iso(),
                "duration_ms": int((datetime.now() - started_at).total_seconds() * 1000),
                "ult_nsu_enviado": ult_nsu_sent,
                "max_nsu_recebido": str(ingest_result.get("highest_nsu") or nsu_final),
                "documents_count": len(docs or []),
                "nsus_processados": [row.get("nsu") for row in ingest_result.get("per_doc", []) if row.get("status") == "novo"],
                "nsus_ignorados": [row.get("nsu") for row in ingest_result.get("per_doc", []) if row.get("status") == "duplicado"],
                "gaps_detected": ingest_result.get("gaps_detected") or [],
                "result": "success",
                "error": "",
                "cooldown_minutes": 0,
                "initiated_by": str(initiated_by or "unknown"),
            },
        )
        _save_data(data)
    return {
        "success": True,
        "synced_count": int(ingest_result.get("new") or 0),
        "ignored_count": int(ingest_result.get("duplicates") or 0),
        "error_count": int(ingest_result.get("errors") or 0),
        "correlation_id": correlation_id,
        "verification_outcome": verification_outcome,
    }


def run_assisted_gap_sample(
    *,
    settings: Dict[str, Any],
    initiated_by: str,
    sample_size: int = 5,
) -> Dict[str, Any]:
    size = max(1, min(int(sample_size or 1), 20))
    candidate_gaps = list_nsu_gaps(status="pending", limit=500)
    target = candidate_gaps[:size]
    rows: List[Dict[str, Any]] = []
    counters = {
        "sample_size": len(target),
        "document_returned": 0,
        "cstat_137": 0,
        "duplicate_returned": 0,
        "recoverable": 0,
        "errors": 0,
    }
    for gap in target:
        nsu_value = str(gap.get("nsu") or "").strip()
        if not nsu_value.isdigit():
            continue
        result = synchronize_specific_nsu(settings=settings, nsu=nsu_value, initiated_by=initiated_by)
        outcome = str(result.get("verification_outcome") or "").strip().lower()
        if outcome == "recovered_document":
            counters["document_returned"] += 1
            counters["recoverable"] += 1
        elif outcome == "no_document_137":
            counters["cstat_137"] += 1
        elif outcome == "duplicate_document":
            counters["duplicate_returned"] += 1
        elif not bool(result.get("success")):
            counters["errors"] += 1
        rows.append(
            {
                "nsu": nsu_value,
                "success": bool(result.get("success")),
                "verification_outcome": outcome or ("error" if not bool(result.get("success")) else "inconclusive"),
                "message": str(result.get("message") or result.get("error") or ""),
                "correlation_id": str(result.get("correlation_id") or ""),
            }
        )
    return {"summary": counters, "rows": rows}


def update_note_conference(access_key: str, status: str) -> bool:
    key_value = str(access_key or "").strip()
    status_value = str(status or "").strip().lower()
    if status_value not in {"pending_conference", "in_conference", "conferenced"}:
        return False
    changed = False
    with file_lock(NFE_REPOSITORY_FILE):
        data = _load_data()
        notes = data.get("notes") if isinstance(data.get("notes"), list) else []
        for note in notes:
            if not isinstance(note, dict):
                continue
            if str(note.get("chave_nfe") or "") != key_value:
                continue
            note["status_conferencia"] = status_value
            note["last_seen_at"] = _now_iso()
            changed = True
            break
        if changed:
            _save_data(data)
    return changed


def update_note_local_snapshot(
    access_key: str,
    *,
    items_fiscais: Optional[List[Dict[str, Any]]] = None,
    resumo_json: Optional[Dict[str, Any]] = None,
    xml_raw: Optional[str] = None,
) -> bool:
    key_value = str(access_key or "").strip()
    if not key_value:
        return False
    changed = False
    with file_lock(NFE_REPOSITORY_FILE):
        data = _load_data()
        notes = data.get("notes") if isinstance(data.get("notes"), list) else []
        for note in notes:
            if not isinstance(note, dict):
                continue
            if str(note.get("chave_nfe") or "") != key_value:
                continue
            if isinstance(items_fiscais, list):
                note["items_fiscais"] = [dict(item) for item in items_fiscais if isinstance(item, dict)]
                changed = True
            if isinstance(resumo_json, dict):
                note["resumo_json"] = dict(resumo_json)
                changed = True
            if isinstance(xml_raw, str) and xml_raw.strip():
                note["xml_raw"] = xml_raw
                note["status_download"] = "downloaded"
                changed = True
            if changed:
                classified = _classify_document_payload(
                    str(note.get("xml_raw") or ""),
                    note.get("items_fiscais") if isinstance(note.get("items_fiscais"), list) else [],
                )
                note["document_type"] = str(classified.get("document_type") or "unknown_structure")
                note["has_full_items"] = bool(classified.get("has_full_items"))
                note["items_loaded"] = bool(classified.get("items_loaded"))
                note["items_reason"] = str(classified.get("items_reason") or "")
                note["xml_root"] = str(classified.get("xml_root") or "")
                note["completeness_status"] = _derive_completeness_status(note)
            if changed:
                note["last_seen_at"] = _now_iso()
            break
        if changed:
            _save_data(data)
    return changed


def register_note_manifestation(
    *,
    access_key: str,
    manifestation_type: str,
    result: str,
    protocol: str = "",
    error: str = "",
    response_cstat: str = "",
    response_xmotivo: str = "",
    registered_at: str = "",
    initiated_by: str = "",
) -> bool:
    key_value = str(access_key or "").strip()
    if not key_value:
        return False
    changed = False
    now_iso = _now_iso()
    with file_lock(NFE_REPOSITORY_FILE):
        data = _load_data()
        notes = data.get("notes") if isinstance(data.get("notes"), list) else []
        for note in notes:
            if not isinstance(note, dict):
                continue
            if str(note.get("chave_nfe") or "") != key_value:
                continue
            note["manifestation_type"] = str(manifestation_type or "")
            note["manifestation_result"] = str(result or "")
            result_value = str(result or "").strip().lower()
            note["manifestation_status"] = "registered" if result_value in {"ok", "success", "registered", "already_registered"} else "error"
            note["manifestation_protocol"] = str(protocol or "")
            note["manifestation_error"] = str(error or "")
            note["manifestation_response_cstat"] = str(response_cstat or "")
            note["manifestation_response_xmotivo"] = str(response_xmotivo or "")
            note["manifestation_registered_at"] = str(registered_at or "")
            note["manifestation_sent_at"] = now_iso
            audit = note.get("completeness_audit") if isinstance(note.get("completeness_audit"), list) else []
            audit.append(
                {
                    "at": now_iso,
                    "event": "manifestation_registered",
                    "manifestation_type": str(manifestation_type or ""),
                    "result": str(result or ""),
                    "protocol": str(protocol or ""),
                    "error": str(error or ""),
                    "initiated_by": str(initiated_by or ""),
                }
            )
            note["completeness_audit"] = audit[-200:]
            note["last_seen_at"] = now_iso
            _normalize_status(note)
            changed = True
            break
        if changed:
            _save_data(data)
    return changed


def register_full_download_attempt(
    *,
    access_key: str,
    outcome: str,
    detail: str = "",
    upgrade_success: bool = False,
    initiated_by: str = "",
) -> bool:
    key_value = str(access_key or "").strip()
    if not key_value:
        return False
    changed = False
    now_iso = _now_iso()
    outcome_value = str(outcome or "").strip().lower()
    with file_lock(NFE_REPOSITORY_FILE):
        data = _load_data()
        notes = data.get("notes") if isinstance(data.get("notes"), list) else []
        for note in notes:
            if not isinstance(note, dict):
                continue
            if str(note.get("chave_nfe") or "") != key_value:
                continue
            note["full_download_attempts"] = int(note.get("full_download_attempts") or 0) + 1
            note["full_download_last_at"] = now_iso
            note["full_download_last_result"] = "success" if outcome_value == "success" else "failed"
            note["full_download_last_user"] = str(initiated_by or "")
            note["last_full_xml_attempt_at"] = now_iso
            note["full_xml_attempt_result"] = "success" if outcome_value == "success" else "failed"
            note["full_xml_attempt_error"] = "" if outcome_value == "success" else str(detail or "")
            note["full_xml_upgrade_success"] = bool(upgrade_success)
            audit = note.get("completeness_audit") if isinstance(note.get("completeness_audit"), list) else []
            audit.append(
                {
                    "at": now_iso,
                    "event": "full_download_attempt",
                    "outcome": outcome_value or "failed",
                    "detail": str(detail or ""),
                    "initiated_by": str(initiated_by or ""),
                }
            )
            note["completeness_audit"] = audit[-200:]
            note["last_seen_at"] = now_iso
            _normalize_status(note)
            changed = True
            break
        if changed:
            _save_data(data)
    return changed


def mark_note_imported(access_key: str) -> bool:
    key_value = str(access_key or "").strip()
    changed = False
    if not key_value:
        return False
    with file_lock(NFE_REPOSITORY_FILE):
        data = _load_data()
        notes = data.get("notes") if isinstance(data.get("notes"), list) else []
        for note in notes:
            if not isinstance(note, dict):
                continue
            if str(note.get("chave_nfe") or "") != key_value:
                continue
            note["status_estoque"] = "imported"
            note["status_conferencia"] = "conferenced"
            note["receipt_status"] = "stocked"
            note["stock_applied"] = True
            note["financial_trace"] = True
            note["approved_for_stock"] = True
            note["imported_to_stock_at"] = _now_iso()
            note["last_seen_at"] = _now_iso()
            changed = True
            break
        if changed:
            _save_data(data)
    return changed


def mark_note_imported_as_asset(*, access_key: str, destination_id: str, approved_by: str, decision_notes: str = "") -> bool:
    key_value = str(access_key or "").strip()
    if not key_value:
        return False
    changed = False
    now_iso = _now_iso()
    with file_lock(NFE_REPOSITORY_FILE):
        data = _load_data()
        notes = data.get("notes") if isinstance(data.get("notes"), list) else []
        for note in notes:
            if not isinstance(note, dict):
                continue
            if str(note.get("chave_nfe") or "") != key_value:
                continue
            note["status_estoque"] = "imported_asset"
            note["status_conferencia"] = "conferenced"
            note["receipt_status"] = "stocked"
            note["stock_applied"] = False
            note["approved_for_stock"] = True
            note["financial_trace"] = True
            note["destination_type"] = "asset"
            note["destination_id"] = str(destination_id or "")
            note["approved_for_stock_at"] = now_iso
            note["approved_for_stock_by"] = str(approved_by or "")
            note["decision_source"] = "admin_consolidated_queue"
            note["decision_notes"] = str(decision_notes or "")
            note["imported_to_stock_at"] = ""
            note["last_seen_at"] = now_iso
            audit = note.get("completeness_audit") if isinstance(note.get("completeness_audit"), list) else []
            audit.append(
                {
                    "at": now_iso,
                    "event": "imported_as_asset",
                    "approved_by": str(approved_by or ""),
                    "destination_id": str(destination_id or ""),
                    "decision_notes": str(decision_notes or ""),
                }
            )
            note["completeness_audit"] = audit[-200:]
            changed = True
            break
        if changed:
            _save_data(data)
    return changed


def mark_note_received_not_stocked(
    *,
    access_key: str,
    user: str,
    note_text: str = "",
    correlation_id: str = "",
) -> bool:
    key_value = str(access_key or "").strip()
    if not key_value:
        return False
    changed = False
    now_iso = _now_iso()
    with file_lock(NFE_REPOSITORY_FILE):
        data = _load_data()
        notes = data.get("notes") if isinstance(data.get("notes"), list) else []
        for note in notes:
            if not isinstance(note, dict):
                continue
            if str(note.get("chave_nfe") or "") != key_value:
                continue
            if str(note.get("status_estoque") or "") == "imported":
                return False
            note["status_estoque"] = "received_not_stocked"
            note["status_conferencia"] = "conferenced"
            note["receipt_status"] = "received_not_stocked"
            note["financial_trace"] = True
            note["stock_applied"] = False
            note["approved_for_stock"] = False
            note["received_not_stocked_at"] = now_iso
            note["received_not_stocked_by"] = str(user or "")
            note["received_not_stocked_note"] = str(note_text or "")
            note["receipt_correlation_id"] = str(correlation_id or "")
            note["last_seen_at"] = now_iso
            audit = note.get("completeness_audit") if isinstance(note.get("completeness_audit"), list) else []
            audit.append(
                {
                    "at": now_iso,
                    "event": "received_not_stocked",
                    "initiated_by": str(user or ""),
                    "note": str(note_text or ""),
                    "correlation_id": str(correlation_id or ""),
                }
            )
            note["completeness_audit"] = audit[-200:]
            changed = True
            break
        if changed:
            _save_data(data)
    return changed


def approve_note_for_stock_launch(*, access_key: str, approver: str, note_text: str = "") -> bool:
    key_value = str(access_key or "").strip()
    if not key_value:
        return False
    changed = False
    now_iso = _now_iso()
    with file_lock(NFE_REPOSITORY_FILE):
        data = _load_data()
        notes = data.get("notes") if isinstance(data.get("notes"), list) else []
        for note in notes:
            if not isinstance(note, dict):
                continue
            if str(note.get("chave_nfe") or "") != key_value:
                continue
            if str(note.get("status_estoque") or "") != "received_not_stocked":
                return False
            note["approved_for_stock"] = True
            note["approved_for_stock_at"] = now_iso
            note["approved_for_stock_by"] = str(approver or "")
            note["last_seen_at"] = now_iso
            audit = note.get("completeness_audit") if isinstance(note.get("completeness_audit"), list) else []
            audit.append(
                {
                    "at": now_iso,
                    "event": "approved_for_stock_launch",
                    "approved_by": str(approver or ""),
                    "note": str(note_text or ""),
                }
            )
            note["completeness_audit"] = audit[-200:]
            changed = True
            break
        if changed:
            _save_data(data)
    return changed


def cancel_note_received_not_stocked(*, access_key: str, user: str, reason: str = "") -> bool:
    key_value = str(access_key or "").strip()
    if not key_value:
        return False
    changed = False
    now_iso = _now_iso()
    with file_lock(NFE_REPOSITORY_FILE):
        data = _load_data()
        notes = data.get("notes") if isinstance(data.get("notes"), list) else []
        for note in notes:
            if not isinstance(note, dict):
                continue
            if str(note.get("chave_nfe") or "") != key_value:
                continue
            if str(note.get("status_estoque") or "") not in {"received_not_stocked", "pending"}:
                return False
            note["status_estoque"] = "pending"
            note["receipt_status"] = "pending"
            note["financial_trace"] = False
            note["stock_applied"] = False
            note["approved_for_stock"] = False
            note["last_seen_at"] = now_iso
            audit = note.get("completeness_audit") if isinstance(note.get("completeness_audit"), list) else []
            audit.append(
                {
                    "at": now_iso,
                    "event": "received_not_stocked_canceled",
                    "by": str(user or ""),
                    "reason": str(reason or ""),
                }
            )
            note["completeness_audit"] = audit[-200:]
            changed = True
            break
        if changed:
            _save_data(data)
    return changed


def reject_note_for_stock_launch(*, access_key: str, rejected_by: str, reason: str, decision_source: str = "admin_queue", decision_notes: str = "") -> bool:
    key_value = str(access_key or "").strip()
    if not key_value or not str(reason or "").strip():
        return False
    changed = False
    now_iso = _now_iso()
    with file_lock(NFE_REPOSITORY_FILE):
        data = _load_data()
        notes = data.get("notes") if isinstance(data.get("notes"), list) else []
        for note in notes:
            if not isinstance(note, dict):
                continue
            if str(note.get("chave_nfe") or "") != key_value:
                continue
            if str(note.get("status_estoque") or "") not in {"received_not_stocked", "pending", "approved_for_stock"}:
                return False
            note["status_estoque"] = "rejected"
            note["receipt_status"] = "rejected"
            note["approved_for_stock"] = False
            note["stock_applied"] = False
            note["financial_trace"] = True
            note["rejected_at"] = now_iso
            note["rejected_by"] = str(rejected_by or "")
            note["rejection_reason"] = str(reason or "")
            note["decision_source"] = str(decision_source or "")
            note["decision_notes"] = str(decision_notes or "")
            note["last_seen_at"] = now_iso
            audit = note.get("completeness_audit") if isinstance(note.get("completeness_audit"), list) else []
            audit.append(
                {
                    "at": now_iso,
                    "event": "stock_launch_rejected",
                    "rejected_by": str(rejected_by or ""),
                    "reason": str(reason or ""),
                    "decision_source": str(decision_source or ""),
                    "decision_notes": str(decision_notes or ""),
                }
            )
            note["completeness_audit"] = audit[-200:]
            changed = True
            break
        if changed:
            _save_data(data)
    return changed


def keep_note_pending_stock_launch(*, access_key: str, by_user: str, notes: str = "", decision_source: str = "admin_queue") -> bool:
    key_value = str(access_key or "").strip()
    if not key_value:
        return False
    changed = False
    now_iso = _now_iso()
    with file_lock(NFE_REPOSITORY_FILE):
        data = _load_data()
        notes_list = data.get("notes") if isinstance(data.get("notes"), list) else []
        for note in notes_list:
            if not isinstance(note, dict):
                continue
            if str(note.get("chave_nfe") or "") != key_value:
                continue
            if str(note.get("status_estoque") or "") not in {"received_not_stocked", "approved_for_stock"}:
                return False
            note["status_estoque"] = "received_not_stocked"
            note["receipt_status"] = "received_not_stocked"
            note["approved_for_stock"] = False
            note["decision_source"] = str(decision_source or "")
            note["decision_notes"] = str(notes or "")
            note["last_seen_at"] = now_iso
            audit = note.get("completeness_audit") if isinstance(note.get("completeness_audit"), list) else []
            audit.append(
                {
                    "at": now_iso,
                    "event": "stock_launch_kept_pending",
                    "by": str(by_user or ""),
                    "decision_source": str(decision_source or ""),
                    "decision_notes": str(notes or ""),
                }
            )
            note["completeness_audit"] = audit[-200:]
            changed = True
            break
        if changed:
            _save_data(data)
    return changed
