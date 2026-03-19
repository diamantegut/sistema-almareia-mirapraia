import logging
import os
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any, Callable, Dict, List, Optional


_AUDIT_LOCK = Lock()
_AUDIT_EVENTS: List[Dict[str, Any]] = []
_AUDIT_MAX = 5000


def audit_resolution(
    *,
    namespace: str,
    input_value: str,
    resolved_path: str,
    source: str,
    mode: str,
    fallback_used: bool = False,
) -> None:
    event = {
        "event": "path_resolution",
        "namespace": namespace,
        "input": input_value,
        "resolved_path": resolved_path,
        "source": source,
        "mode": mode,
        "fallback_used": fallback_used,
    }
    with _AUDIT_LOCK:
        _AUDIT_EVENTS.append(event)
        if len(_AUDIT_EVENTS) > _AUDIT_MAX:
            del _AUDIT_EVENTS[0 : len(_AUDIT_EVENTS) - _AUDIT_MAX]
    logging.getLogger(__name__).info("path_resolution %s", event)


def get_audit_events(limit: Optional[int] = None) -> List[Dict[str, Any]]:
    with _AUDIT_LOCK:
        if limit is None:
            return list(_AUDIT_EVENTS)
        return list(_AUDIT_EVENTS[-max(0, int(limit)) :])


def reset_audit_events() -> None:
    with _AUDIT_LOCK:
        _AUDIT_EVENTS.clear()


@dataclass
class ValidationReport:
    ok: bool
    checks: Dict[str, str]


@dataclass
class PathTopologySnapshot:
    mode: str
    roots: Dict[str, str]


class PathResolver:
    def __init__(self, *, base_dir: str, config_loader: Callable[[], Dict[str, Any]], mode: str = "legacy"):
        self.base_dir = Path(base_dir).resolve()
        self.config_loader = config_loader
        self.mode = str(mode or "legacy")

    def get_root(self, kind: str) -> Path:
        if kind == "system":
            return self.base_dir
        if kind == "data":
            return self._resolve_root("data_dir", "data")
        if kind == "backup":
            return self._resolve_root("backups_dir", "backups")
        raise ValueError(f"Unsupported root kind: {kind}")

    def resolve_data(self, relative_name: str) -> Path:
        root = self._resolve_root("data_dir", "data")
        root = self.ensure_dir(root)
        resolved = (root / str(relative_name or "")).resolve()
        audit_resolution(
            namespace="data",
            input_value=str(relative_name or ""),
            resolved_path=str(resolved),
            source=self._source_for_key("data_dir"),
            mode=self.mode,
            fallback_used=False,
        )
        return resolved

    def resolve_backup(self, relative_name: str = "") -> Path:
        root = self._resolve_root("backups_dir", "backups")
        fallback_used = False
        try:
            root = self.ensure_dir(root)
        except OSError:
            root = self.ensure_dir(self.base_dir / "Backups")
            fallback_used = True
        resolved = (root / str(relative_name or "")).resolve()
        audit_resolution(
            namespace="backup",
            input_value=str(relative_name or ""),
            resolved_path=str(resolved),
            source=self._source_for_key("backups_dir"),
            mode=self.mode,
            fallback_used=fallback_used,
        )
        return resolved

    def resolve_log(self, relative_name: str = "") -> Path:
        root = self._resolve_root("logs_dir", "logs")
        root = self.ensure_dir(root)
        resolved = (root / str(relative_name or "")).resolve()
        audit_resolution(
            namespace="log",
            input_value=str(relative_name or ""),
            resolved_path=str(resolved),
            source=self._source_for_key("logs_dir"),
            mode=self.mode,
            fallback_used=False,
        )
        return resolved

    def resolve_fiscal(self, relative_name: str = "") -> Path:
        root = self._resolve_root("fiscal_dir", "fiscal_documents")
        root = self.ensure_dir(root)
        resolved = (root / str(relative_name or "")).resolve()
        audit_resolution(
            namespace="fiscal",
            input_value=str(relative_name or ""),
            resolved_path=str(resolved),
            source=self._source_for_key("fiscal_dir"),
            mode=self.mode,
            fallback_used=False,
        )
        return resolved

    def resolve_static(self, relative_name: str = "") -> Path:
        resolved = (self.base_dir / str(relative_name or "")).resolve()
        audit_resolution(
            namespace="asset",
            input_value=str(relative_name or ""),
            resolved_path=str(resolved),
            source="default",
            mode=self.mode,
            fallback_used=False,
        )
        return resolved

    def resolve_upload(self, relative_name: str = "") -> Path:
        config = self._load_config()
        raw_upload = str(config.get("uploads_dir", "static/uploads/maintenance") or "static/uploads/maintenance")
        root = Path(raw_upload)
        source = "config" if "uploads_dir" in config else "default"
        if not root.is_absolute():
            root = (self.base_dir / root).resolve()
        root = self.ensure_dir(root)
        resolved = (root / str(relative_name or "")).resolve()
        audit_resolution(
            namespace="upload",
            input_value=str(relative_name or ""),
            resolved_path=str(resolved),
            source=source,
            mode=self.mode,
            fallback_used=False,
        )
        return resolved

    def ensure_dir(self, path: Path) -> Path:
        path.mkdir(parents=True, exist_ok=True)
        return path

    def validate(self, required: Optional[List[str]] = None) -> ValidationReport:
        checks: Dict[str, str] = {}
        candidates = required or ["data", "backup", "log", "fiscal"]
        ok = True
        for namespace in candidates:
            try:
                if namespace == "data":
                    path = self.resolve_data("")
                elif namespace == "backup":
                    path = self.resolve_backup("")
                elif namespace == "log":
                    path = self.resolve_log("")
                elif namespace == "fiscal":
                    path = self.resolve_fiscal("")
                else:
                    path = self.resolve_static("")
                writable = os.access(str(path), os.W_OK)
                checks[namespace] = "OK" if writable else "NOT_WRITABLE"
                ok = ok and writable
            except Exception as exc:
                checks[namespace] = f"ERROR: {exc}"
                ok = False
        return ValidationReport(ok=ok, checks=checks)

    def snapshot(self) -> PathTopologySnapshot:
        roots = {
            "system": str(self.get_root("system")),
            "data": str(self.get_root("data")),
            "backup": str(self.get_root("backup")),
            "log": str(self._resolve_root("logs_dir", "logs")),
            "fiscal": str(self._resolve_root("fiscal_dir", "fiscal_documents")),
        }
        return PathTopologySnapshot(mode=self.mode, roots=roots)

    def _load_config(self) -> Dict[str, Any]:
        try:
            loaded = self.config_loader() or {}
            if isinstance(loaded, dict):
                return loaded
            return {}
        except Exception:
            return {}

    def _source_for_key(self, key: str) -> str:
        config = self._load_config()
        return "config" if key in config else "default"

    def _resolve_root(self, key: str, default: str) -> Path:
        config = self._load_config()
        raw_value = str(config.get(key, default) or default)
        path = Path(raw_value)
        if not path.is_absolute():
            path = (self.base_dir / path).resolve()
        return path
