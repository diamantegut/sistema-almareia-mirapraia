from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

from app.services.logger_service import LoggerService


class AuthorizationHeatmapService:
    @staticmethod
    def aggregate_payload(
        *,
        group_by: str = "endpoint",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        area: Optional[str] = None,
        endpoint: Optional[str] = None,
        user: Optional[str] = None,
        reason_code: Optional[str] = None,
        events: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        group_name = str(group_by or "endpoint").strip().lower()
        filtered = AuthorizationHeatmapService._resolve_filtered_events(
            start_date=start_date,
            end_date=end_date,
            area=area,
            endpoint=endpoint,
            user=user,
            reason_code=reason_code,
            events=events,
        )
        rows = AuthorizationHeatmapService._build_rows_from_events(group_by=group_name, filtered_events=filtered)
        payload = AuthorizationHeatmapService._finalize_payload(rows)
        payload["charts"] = {
            "matrix": AuthorizationHeatmapService._build_matrix(rows),
            "timeseries": AuthorizationHeatmapService._build_timeseries(filtered),
        }
        return payload

    @staticmethod
    def aggregate_by_endpoint(
        *,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        area: Optional[str] = None,
        endpoint: Optional[str] = None,
        user: Optional[str] = None,
        reason_code: Optional[str] = None,
        events: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        return AuthorizationHeatmapService.aggregate_payload(
            group_by="endpoint",
            start_date=start_date,
            end_date=end_date,
            area=area,
            endpoint=endpoint,
            user=user,
            reason_code=reason_code,
            events=events,
        )

    @staticmethod
    def aggregate_by_area(
        *,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        area: Optional[str] = None,
        endpoint: Optional[str] = None,
        user: Optional[str] = None,
        reason_code: Optional[str] = None,
        events: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        return AuthorizationHeatmapService.aggregate_payload(
            group_by="area",
            start_date=start_date,
            end_date=end_date,
            area=area,
            endpoint=endpoint,
            user=user,
            reason_code=reason_code,
            events=events,
        )

    @staticmethod
    def aggregate_by_user(
        *,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        area: Optional[str] = None,
        endpoint: Optional[str] = None,
        user: Optional[str] = None,
        reason_code: Optional[str] = None,
        events: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        return AuthorizationHeatmapService.aggregate_payload(
            group_by="user",
            start_date=start_date,
            end_date=end_date,
            area=area,
            endpoint=endpoint,
            user=user,
            reason_code=reason_code,
            events=events,
        )

    @staticmethod
    def list_filters(*, events: Optional[List[Dict[str, Any]]] = None) -> Dict[str, List[str]]:
        source = list(events or AuthorizationHeatmapService._load_events())
        areas = sorted({str(item.get("area") or "").strip() for item in source if str(item.get("area") or "").strip()})
        endpoints = sorted({str(item.get("endpoint") or "").strip() for item in source if str(item.get("endpoint") or "").strip()})
        users = sorted({str(item.get("user_id") or "").strip() for item in source if str(item.get("user_id") or "").strip()})
        reasons = sorted({str(item.get("reason_code") or "").strip() for item in source if str(item.get("reason_code") or "").strip()})
        return {"areas": areas, "endpoints": endpoints, "users": users, "reason_codes": reasons}

    @staticmethod
    def _build_rows(
        *,
        group_by: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        area: Optional[str] = None,
        endpoint: Optional[str] = None,
        user: Optional[str] = None,
        reason_code: Optional[str] = None,
        events: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        filtered = AuthorizationHeatmapService._resolve_filtered_events(
            start_date=start_date,
            end_date=end_date,
            area=area,
            endpoint=endpoint,
            user=user,
            reason_code=reason_code,
            events=events,
        )
        return AuthorizationHeatmapService._build_rows_from_events(group_by=group_by, filtered_events=filtered)

    @staticmethod
    def _resolve_filtered_events(
        *,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        area: Optional[str] = None,
        endpoint: Optional[str] = None,
        user: Optional[str] = None,
        reason_code: Optional[str] = None,
        events: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        source = list(events or AuthorizationHeatmapService._load_events(start_date=start_date, end_date=end_date))
        return AuthorizationHeatmapService._apply_filters(
            source,
            area=area,
            endpoint=endpoint,
            user=user,
            reason_code=reason_code,
        )

    @staticmethod
    def _build_rows_from_events(*, group_by: str, filtered_events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        grouped: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
        for event in filtered_events:
            group_key = AuthorizationHeatmapService._group_key(group_by, event)
            row = grouped.get(group_key)
            if row is None:
                row = {
                    "area": str(event.get("area") or "unknown"),
                    "endpoint": str(event.get("endpoint") or "unknown"),
                    "user_id": str(event.get("user_id") or "unknown"),
                    "total_requests": 0,
                    "allow_count": 0,
                    "deny_count": 0,
                    "override_count": 0,
                    "reasons": defaultdict(int),
                }
                grouped[group_key] = row
            row["total_requests"] += 1
            decision = str(event.get("decision") or "").strip().upper()
            if decision == "ALLOW":
                row["allow_count"] += 1
            elif decision == "DENY":
                row["deny_count"] += 1
            elif decision == "REQUIRE_OVERRIDE":
                row["override_count"] += 1
            reason_value = str(event.get("reason_code") or "").strip()
            if reason_value:
                row["reasons"][reason_value] += 1

        rows: List[Dict[str, Any]] = []
        for row in grouped.values():
            total = int(row["total_requests"])
            deny_ratio = float(row["deny_count"] / total) if total > 0 else 0.0
            override_ratio = float(row["override_count"] / total) if total > 0 else 0.0
            risk_level = AuthorizationHeatmapService._risk_from_deny_ratio(deny_ratio)
            row["deny_ratio"] = deny_ratio
            row["override_ratio"] = override_ratio
            row["risk_level"] = risk_level
            row["override_alert"] = override_ratio >= 0.30
            row["reasons"] = dict(sorted(row["reasons"].items(), key=lambda item: item[1], reverse=True))
            rows.append(row)
        rows.sort(key=lambda item: (item["risk_level"], -item["deny_ratio"], -item["override_ratio"], -item["total_requests"]))
        return rows

    @staticmethod
    def _build_matrix(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        matrix: List[Dict[str, Any]] = []
        for row in rows:
            matrix.append(
                {
                    "area": row.get("area"),
                    "endpoint": row.get("endpoint"),
                    "user_id": row.get("user_id"),
                    "deny_ratio": float(row.get("deny_ratio") or 0.0),
                    "override_ratio": float(row.get("override_ratio") or 0.0),
                    "risk_level": row.get("risk_level"),
                    "override_alert": bool(row.get("override_alert")),
                    "total_requests": int(row.get("total_requests") or 0),
                }
            )
        return matrix

    @staticmethod
    def _build_timeseries(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        by_day: Dict[str, Dict[str, int]] = {}
        for event in events:
            timestamp = str(event.get("timestamp") or "").strip()
            day = timestamp[:10] if len(timestamp) >= 10 else "unknown"
            row = by_day.get(day)
            if row is None:
                row = {"total": 0, "allow": 0, "deny": 0, "override": 0}
                by_day[day] = row
            row["total"] += 1
            decision = str(event.get("decision") or "").strip().upper()
            if decision == "ALLOW":
                row["allow"] += 1
            elif decision == "DENY":
                row["deny"] += 1
            elif decision == "REQUIRE_OVERRIDE":
                row["override"] += 1
        output: List[Dict[str, Any]] = []
        for day in sorted(by_day.keys()):
            row = by_day[day]
            total = int(row["total"])
            output.append(
                {
                    "day": day,
                    "total": total,
                    "allow": int(row["allow"]),
                    "deny": int(row["deny"]),
                    "override": int(row["override"]),
                    "deny_ratio": float(row["deny"] / total) if total > 0 else 0.0,
                    "override_ratio": float(row["override"] / total) if total > 0 else 0.0,
                }
            )
        return output

    @staticmethod
    def _finalize_payload(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        total_requests = sum(int(item.get("total_requests") or 0) for item in rows)
        deny_total = sum(int(item.get("deny_count") or 0) for item in rows)
        override_total = sum(int(item.get("override_count") or 0) for item in rows)
        allow_total = sum(int(item.get("allow_count") or 0) for item in rows)
        deny_ratio = float(deny_total / total_requests) if total_requests > 0 else 0.0
        override_ratio = float(override_total / total_requests) if total_requests > 0 else 0.0
        insights = AuthorizationHeatmapService._build_insights(rows)
        return {
            "rows": rows,
            "summary": {
                "total_requests": total_requests,
                "allow_count": allow_total,
                "deny_count": deny_total,
                "override_count": override_total,
                "deny_ratio": deny_ratio,
                "override_ratio": override_ratio,
            },
            "insights": insights,
        }

    @staticmethod
    def _build_insights(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        insights: List[Dict[str, Any]] = []
        missing_rows = [item for item in rows if "AUTHZ_POLICY_MISSING" in " ".join((item.get("reasons") or {}).keys())]
        for item in missing_rows[:5]:
            insights.append(
                {
                    "type": "policy_missing",
                    "severity": "high",
                    "area": item.get("area"),
                    "endpoint": item.get("endpoint"),
                    "message": "Policy missing detectada no endpoint.",
                }
            )
        deny_spikes = [item for item in rows if float(item.get("deny_ratio") or 0.0) >= 0.20 and int(item.get("total_requests") or 0) >= 5]
        for item in deny_spikes[:5]:
            insights.append(
                {
                    "type": "deny_spike",
                    "severity": "high",
                    "area": item.get("area"),
                    "endpoint": item.get("endpoint"),
                    "message": "Pico de DENY detectado.",
                }
            )
        override_spikes = [item for item in rows if float(item.get("override_ratio") or 0.0) >= 0.30 and int(item.get("total_requests") or 0) >= 5]
        for item in override_spikes[:5]:
            insights.append(
                {
                    "type": "override_spike",
                    "severity": "medium",
                    "area": item.get("area"),
                    "endpoint": item.get("endpoint"),
                    "message": "Pico de REQUIRE_OVERRIDE detectado.",
                }
            )
        return insights

    @staticmethod
    def _group_key(group_by: str, event: Dict[str, Any]) -> Tuple[str, str, str]:
        area = str(event.get("area") or "unknown")
        endpoint = str(event.get("endpoint") or "unknown")
        user_id = str(event.get("user_id") or "unknown")
        if group_by == "area":
            return (area, "*", "*")
        if group_by == "user":
            return (area, endpoint, user_id)
        return (area, endpoint, "*")

    @staticmethod
    def _apply_filters(
        events: Iterable[Dict[str, Any]],
        *,
        area: Optional[str] = None,
        endpoint: Optional[str] = None,
        user: Optional[str] = None,
        reason_code: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        area_filter = str(area or "").strip().lower()
        endpoint_filter = str(endpoint or "").strip().lower()
        user_filter = str(user or "").strip().lower()
        reason_filter = str(reason_code or "").strip().lower()
        result: List[Dict[str, Any]] = []
        for item in events:
            area_value = str(item.get("area") or "").strip().lower()
            endpoint_value = str(item.get("endpoint") or "").strip().lower()
            user_value = str(item.get("user_id") or "").strip().lower()
            reason_value = str(item.get("reason_code") or "").strip().lower()
            if area_filter and area_value != area_filter:
                continue
            if endpoint_filter and endpoint_value != endpoint_filter:
                continue
            if user_filter and user_value != user_filter:
                continue
            if reason_filter and reason_value != reason_filter:
                continue
            result.append(item)
        return result

    @staticmethod
    def _load_events(*, start_date: Optional[str] = None, end_date: Optional[str] = None) -> List[Dict[str, Any]]:
        start = AuthorizationHeatmapService._parse_date(start_date, default=datetime.now() - timedelta(days=7))
        end = AuthorizationHeatmapService._parse_date(end_date, default=datetime.now()).replace(hour=23, minute=59, second=59)
        payload = LoggerService.get_logs(
            start_date=start,
            end_date=end,
            per_page=2000,
            acao="authz_",
        )
        items = payload.get("items") if isinstance(payload, dict) else []
        if not isinstance(items, list):
            return []
        events: List[Dict[str, Any]] = []
        for item in items:
            parsed = AuthorizationHeatmapService._parse_log_item(item)
            if parsed is not None:
                events.append(parsed)
        return events

    @staticmethod
    def _parse_log_item(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not isinstance(item, dict):
            return None
        action = str(item.get("acao") or "").strip().lower()
        if action not in ("authz_decision", "authz_override"):
            return None
        details = item.get("detalhes")
        details_payload = details if isinstance(details, dict) else {}
        decision = str(details_payload.get("decision") or "").strip().upper()
        if action == "authz_override":
            decision = "REQUIRE_OVERRIDE"
        if decision not in ("ALLOW", "DENY", "REQUIRE_OVERRIDE"):
            return None
        endpoint = str(details_payload.get("endpoint") or "unknown.endpoint").strip()
        area = str(details_payload.get("area") or "").strip()
        if not area:
            prefix = endpoint.split(".", 1)[0] if "." in endpoint else endpoint
            area = {
                "finance": "financeiro",
                "admin": "administracao_sistema",
                "financial_audit": "auditoria_financeira",
            }.get(prefix, prefix or "unknown")
        return {
            "timestamp": str(details_payload.get("timestamp") or item.get("timestamp") or "").strip(),
            "user_id": str(details_payload.get("executor_user") or item.get("colaborador_id") or "unknown").strip(),
            "endpoint": endpoint,
            "area": area,
            "decision": decision,
            "reason_code": str(details_payload.get("reason_code") or "").strip(),
            "policy_hash": str(details_payload.get("policy_hash") or "").strip(),
            "policy_version": str(details_payload.get("policy_version") or "").strip(),
        }

    @staticmethod
    def _risk_from_deny_ratio(deny_ratio: float) -> str:
        if deny_ratio < 0.05:
            return "green"
        if deny_ratio < 0.20:
            return "yellow"
        return "red"

    @staticmethod
    def _parse_date(value: Optional[str], *, default: datetime) -> datetime:
        raw = str(value or "").strip()
        if not raw:
            return default
        try:
            return datetime.strptime(raw, "%Y-%m-%d")
        except Exception:
            return default
