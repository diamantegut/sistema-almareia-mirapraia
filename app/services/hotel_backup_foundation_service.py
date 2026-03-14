import hashlib
import json
import os
import shutil
import subprocess
import sys
from contextlib import nullcontext
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from zipfile import ZIP_DEFLATED, ZipFile

from app.services.transfer_service import file_lock
from app.services.system_config_manager import (
    BASE_DIR,
    CONFIG_FILE,
    DEPARTMENT_PERMISSIONS_FILE,
    USERS_FILE,
    get_data_path,
    get_fiscal_path,
    get_log_path,
    load_system_config,
)

DEFAULT_HOTEL_BACKUPS_ROOT = r"G:\Almareia Mirapraia\HotelBackups"
FULL_BACKUP_MAX_BYTES_PRODUCTION = 5 * 1024 * 1024 * 1024


class HotelBackupFoundationService:
    @classmethod
    def _normalize_root_candidate(cls, raw: Optional[str]) -> Optional[Path]:
        candidate_raw = str(raw or "").strip()
        if not candidate_raw:
            return None
        candidate = Path(candidate_raw)
        if not candidate.is_absolute():
            candidate = Path(BASE_DIR) / candidate
        return candidate

    @classmethod
    def _resolve_backup_root(cls, root_path: Optional[str] = None) -> Path:
        config = load_system_config() or {}
        candidates: List[Path] = []
        direct = cls._normalize_root_candidate(root_path)
        if direct is not None:
            candidates.append(direct)
        configured = cls._normalize_root_candidate(config.get("hotel_backups_root"))
        if configured is not None:
            candidates.append(configured)
        configured_generic = cls._normalize_root_candidate(config.get("backups_dir"))
        if configured_generic is not None:
            candidates.append(configured_generic / "HotelBackups")
        default_candidate = cls._normalize_root_candidate(DEFAULT_HOTEL_BACKUPS_ROOT)
        if default_candidate is not None:
            candidates.append(default_candidate)
        fallback = Path(BASE_DIR) / "HotelBackups"
        candidates.append(fallback)

        for candidate in candidates:
            try:
                candidate.mkdir(parents=True, exist_ok=True)
                return candidate
            except Exception:
                continue

        fallback.mkdir(parents=True, exist_ok=True)
        return fallback

    @classmethod
    def _call_scheduler_control(cls, action: str) -> bool:
        try:
            from app.services import scheduler_service
            fn = getattr(scheduler_service, action, None)
            if callable(fn):
                return bool(fn())
        except Exception:
            return False
        return False

    @classmethod
    def _health_max_age_hours(cls, environment: str) -> int:
        return 26 if environment == "production" else 24 * 8

    @classmethod
    def _parse_full_timestamp(cls, backup_name: str) -> Optional[datetime]:
        try:
            if not backup_name.startswith("full_") or not backup_name.endswith(".zip"):
                return None
            stem = backup_name[:-4]
            stamp = stem.rsplit("_", 2)[-2] + "_" + stem.rsplit("_", 2)[-1]
            return datetime.strptime(stamp, "%Y%m%d_%H%M%S")
        except Exception:
            return None

    @classmethod
    def _latest_full_backup(cls, full_dir: Path) -> Optional[Path]:
        files = [path for path in full_dir.glob("full_*.zip") if path.is_file()]
        if not files:
            return None
        files.sort(key=lambda item: item.stat().st_mtime, reverse=True)
        return files[0]

    @classmethod
    def _safe_relative(cls, path: Path, base: Path) -> str:
        try:
            return str(path.relative_to(base))
        except Exception:
            return str(path)

    @classmethod
    def evaluate_full_backup_health(
        cls,
        *,
        environment: Optional[str] = None,
        root_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        env = cls.resolve_environment(environment)
        paths = cls.ensure_backup_structure(env, root_path)
        full_dir = Path(paths["full"])
        manifests_dir = Path(paths["manifests"])
        health_dir = Path(paths["health"])
        now = datetime.now()
        report_timestamp = now.strftime("%Y%m%d_%H%M%S")

        backup_file = cls._latest_full_backup(full_dir)
        status = "OK"
        details: List[str] = []

        backup_size = 0
        last_full_backup = None
        manifest_file = None
        manifest_present = False
        hash_present = False
        hash_valid = False

        if not backup_file:
            status = "CRÍTICO"
            details.append("Nenhum full backup encontrado.")
        else:
            backup_size = int(backup_file.stat().st_size)
            parsed_ts = cls._parse_full_timestamp(backup_file.name)
            if parsed_ts:
                last_full_backup = parsed_ts.isoformat()
                age_hours = (now - parsed_ts).total_seconds() / 3600.0
                if age_hours > cls._health_max_age_hours(env):
                    if status != "CRÍTICO":
                        status = "ALERTA"
                    details.append(f"Full backup antigo ({age_hours:.1f}h).")
            else:
                last_full_backup = datetime.fromtimestamp(backup_file.stat().st_mtime).isoformat()
                details.append("Timestamp do nome do backup não pôde ser interpretado.")

            try:
                with ZipFile(backup_file, "r") as archive:
                    archive.testzip()
            except Exception as exc:
                status = "CRÍTICO"
                details.append(f"Arquivo de backup não legível: {exc}")

            manifest_candidate = manifests_dir / f"manifest_{backup_file.stem}.json"
            manifest_file = manifest_candidate
            manifest_present = manifest_candidate.exists()
            if not manifest_present:
                status = "CRÍTICO"
                details.append("Manifesto correspondente ausente.")
            else:
                manifest_payload = None
                try:
                    with open(manifest_candidate, "r", encoding="utf-8") as stream:
                        manifest_payload = json.load(stream)
                except Exception as exc:
                    status = "CRÍTICO"
                    details.append(f"Manifesto ilegível: {exc}")
                if isinstance(manifest_payload, dict):
                    manifest_hash = str(manifest_payload.get("sha256") or "").strip()
                    hash_present = bool(manifest_hash)
                    if not hash_present:
                        status = "CRÍTICO"
                        details.append("Manifesto sem hash SHA-256.")
                    else:
                        computed = cls._sha256_file(backup_file)
                        hash_valid = computed == manifest_hash
                        if not hash_valid:
                            status = "CRÍTICO"
                            details.append("Hash do artefato diverge do manifesto.")

        if not details and status == "OK":
            details.append("Full backup íntegro e manifesto consistente.")

        health_payload = {
            "timestamp": now.isoformat(),
            "environment": env,
            "last_full_backup": last_full_backup,
            "backup_file": str(backup_file) if backup_file else None,
            "backup_size": int(backup_size),
            "manifest_file": str(manifest_file) if manifest_file else None,
            "manifest_present": bool(manifest_present),
            "hash_present": bool(hash_present),
            "hash_valid": bool(hash_valid),
            "status": status,
            "details": details,
        }
        report_file = health_dir / f"health_full_{env}_{report_timestamp}.json"
        latest_file = health_dir / f"health_full_{env}_latest.json"
        with open(report_file, "w", encoding="utf-8") as stream:
            json.dump(health_payload, stream, indent=2, ensure_ascii=False)
        with open(latest_file, "w", encoding="utf-8") as stream:
            json.dump(health_payload, stream, indent=2, ensure_ascii=False)
        health_payload["health_file"] = str(report_file)
        health_payload["health_latest_file"] = str(latest_file)
        health_payload["backup_file_relative"] = cls._safe_relative(Path(health_payload["backup_file"]), Path(paths["environment_root"])) if health_payload["backup_file"] else None
        return health_payload

    @classmethod
    def _read_health_file(cls, file_path: Path) -> Optional[Dict[str, Any]]:
        try:
            with open(file_path, "r", encoding="utf-8") as stream:
                data = json.load(stream)
            if not isinstance(data, dict):
                return None
            data["health_file"] = str(file_path)
            return data
        except Exception:
            return None

    @classmethod
    def _history_health_files(cls, health_dir: Path, environment: str) -> List[Path]:
        pattern = f"health_full_{environment}_*.json"
        files = [path for path in health_dir.glob(pattern) if path.is_file() and not path.name.endswith("_latest.json")]
        sortable: List[Tuple[Path, datetime]] = []
        for file_path in files:
            payload = cls._read_health_file(file_path)
            timestamp_raw = str((payload or {}).get("timestamp") or "").strip()
            parsed_timestamp: Optional[datetime] = None
            if timestamp_raw:
                try:
                    parsed_timestamp = datetime.fromisoformat(timestamp_raw.replace("Z", "+00:00"))
                except Exception:
                    parsed_timestamp = None
            if parsed_timestamp is None:
                parsed_timestamp = datetime.fromtimestamp(file_path.stat().st_mtime)
            sortable.append((file_path, parsed_timestamp))
        sortable.sort(key=lambda item: item[1], reverse=True)
        files = [item[0] for item in sortable]
        return files

    @classmethod
    def get_latest_health(cls, *, environment: Optional[str] = None, root_path: Optional[str] = None) -> Dict[str, Any]:
        env = cls.resolve_environment(environment)
        paths = cls.ensure_backup_structure(env, root_path)
        health_dir = Path(paths["health"])
        latest_pointer = health_dir / f"health_full_{env}_latest.json"
        latest_payload = cls._read_health_file(latest_pointer) if latest_pointer.exists() else None

        if not latest_payload:
            history_files = cls._history_health_files(health_dir, env)
            if history_files:
                latest_payload = cls._read_health_file(history_files[0])

        return {
            "environment": env,
            "found": bool(latest_payload),
            "latest": latest_payload,
            "latest_file": str(Path(latest_payload["health_file"])) if latest_payload else None,
        }

    @classmethod
    def list_health_history(
        cls,
        *,
        environment: Optional[str] = None,
        root_path: Optional[str] = None,
        limit: int = 10,
    ) -> Dict[str, Any]:
        env = cls.resolve_environment(environment)
        paths = cls.ensure_backup_structure(env, root_path)
        health_dir = Path(paths["health"])
        safe_limit = max(1, int(limit or 10))

        records: List[Dict[str, Any]] = []
        for file_path in cls._history_health_files(health_dir, env):
            payload = cls._read_health_file(file_path)
            if payload:
                records.append(payload)
            if len(records) >= safe_limit:
                break

        return {
            "environment": env,
            "count": len(records),
            "items": records,
        }

    @classmethod
    def get_health_read_model(
        cls,
        *,
        environment: Optional[str] = None,
        root_path: Optional[str] = None,
        history_limit: int = 10,
    ) -> Dict[str, Any]:
        latest_result = cls.get_latest_health(environment=environment, root_path=root_path)
        history_result = cls.list_health_history(environment=environment, root_path=root_path, limit=history_limit)
        latest_payload = latest_result.get("latest") or {}

        if latest_result.get("found"):
            consolidated_status = str(latest_payload.get("status") or "ALERTA")
        else:
            consolidated_status = "CRÍTICO"

        return {
            "environment": latest_result.get("environment"),
            "consolidated_status": consolidated_status,
            "latest_health": latest_payload if latest_result.get("found") else None,
            "history": history_result.get("items", []),
            "history_count": history_result.get("count", 0),
            "backup_file": latest_payload.get("backup_file"),
            "manifest_file": latest_payload.get("manifest_file"),
        }

    @classmethod
    def _resolve_full_backup_and_manifest(
        cls,
        *,
        environment: str,
        root_path: Optional[str],
        backup_reference: str,
    ) -> Tuple[Path, Path, Dict[str, str]]:
        paths = cls.ensure_backup_structure(environment, root_path)
        full_dir = Path(paths["full"])
        manifests_dir = Path(paths["manifests"])
        backup_path = Path(backup_reference)
        if not backup_path.is_absolute():
            backup_path = full_dir / backup_reference
        manifest_path = manifests_dir / f"manifest_{backup_path.stem}.json"
        return backup_path, manifest_path, paths

    @classmethod
    def _is_controlled_restore_target(cls, target: Path, restore_base: Path, paths: Dict[str, str]) -> bool:
        try:
            target.relative_to(restore_base)
        except Exception:
            return False
        critical_paths = {
            Path(BASE_DIR).resolve(),
            Path(paths["root"]).resolve(),
            Path(paths["environment_root"]).resolve(),
        }
        resolved = target.resolve()
        if resolved in critical_paths:
            return False
        return True

    @classmethod
    def validate_restored_full_backup_dev(
        cls,
        *,
        backup_reference: str,
        restore_target_dir: str,
        root_path: Optional[str] = None,
        require_manifest: bool = True,
        validate_manifest_hash: bool = True,
    ) -> Dict[str, Any]:
        env = "dev"
        backup_path, manifest_path, _ = cls._resolve_full_backup_and_manifest(
            environment=env,
            root_path=root_path,
            backup_reference=backup_reference,
        )
        details: List[str] = []
        status = "OK"
        backup_exists = backup_path.exists() and backup_path.is_file()
        if not backup_exists:
            return {
                "success": False,
                "status": "CRÍTICO",
                "details": ["Backup full não encontrado para validação."],
                "backup_file": str(backup_path),
                "restore_target_dir": str(Path(restore_target_dir)),
                "manifest_file": str(manifest_path),
                "manifest_present": False,
                "hash_valid": False,
                "expected_files_ok": False,
            }

        manifest_present = manifest_path.exists() and manifest_path.is_file()
        manifest_data = None
        hash_valid = False
        if require_manifest and not manifest_present:
            status = "CRÍTICO"
            details.append("Manifesto correspondente ausente.")
        elif manifest_present:
            try:
                with open(manifest_path, "r", encoding="utf-8") as stream:
                    manifest_data = json.load(stream)
            except Exception as exc:
                status = "CRÍTICO"
                details.append(f"Manifesto inválido/ilegível: {exc}")

        if validate_manifest_hash and status != "CRÍTICO":
            expected_hash = str((manifest_data or {}).get("sha256") or "").strip()
            if not expected_hash:
                status = "CRÍTICO"
                details.append("Manifesto sem hash para validação.")
            else:
                current_hash = cls._sha256_file(backup_path)
                hash_valid = current_hash == expected_hash
                if not hash_valid:
                    status = "CRÍTICO"
                    details.append("Hash do backup diverge do manifesto.")

        restore_target = Path(restore_target_dir)
        expected_paths = [
            restore_target / "data",
            restore_target / "system_config.json",
        ]
        expected_files_ok = all(path.exists() for path in expected_paths)
        if not expected_files_ok:
            status = "CRÍTICO"
            details.append("Estrutura restaurada incompleta: data/ ou system_config.json ausente.")

        if status == "OK":
            details.append("Restore validado com sucesso no DEV.")

        return {
            "success": status == "OK",
            "status": status,
            "details": details,
            "backup_file": str(backup_path),
            "restore_target_dir": str(restore_target),
            "manifest_file": str(manifest_path),
            "manifest_present": bool(manifest_present),
            "hash_valid": bool(hash_valid),
            "expected_files_ok": bool(expected_files_ok),
        }

    @classmethod
    def restore_full_backup_dev(
        cls,
        *,
        backup_reference: str,
        root_path: Optional[str] = None,
        restore_target_dir: Optional[str] = None,
        overwrite_confirmed: bool = False,
        require_manifest: bool = True,
        validate_manifest_hash: bool = True,
        run_smoke_validation: bool = True,
        smoke_port: int = 5501,
        enforce_app_boot: bool = False,
    ) -> Dict[str, Any]:
        env = cls.resolve_environment("dev")
        backup_path, manifest_path, paths = cls._resolve_full_backup_and_manifest(
            environment=env,
            root_path=root_path,
            backup_reference=backup_reference,
        )
        restore_base = Path(paths["environment_root"]) / "restore_tests"
        restore_base.mkdir(parents=True, exist_ok=True)

        if restore_target_dir:
            restore_target = Path(restore_target_dir)
            if not restore_target.is_absolute():
                restore_target = restore_base / restore_target
        else:
            restore_target = restore_base / f"restore_{backup_path.stem}"
        restore_target = restore_target.resolve()
        restore_base = restore_base.resolve()

        details: List[str] = []
        if not cls._is_controlled_restore_target(restore_target, restore_base, paths):
            return {
                "success": False,
                "status": "CRÍTICO",
                "details": ["Destino de restore fora da área controlada do DEV."],
                "backup_file": str(backup_path),
                "restore_target_dir": str(restore_target),
                "manifest_file": str(manifest_path),
                "manifest_present": manifest_path.exists(),
                "hash_valid": False,
                "expected_files_ok": False,
            }

        if not backup_path.exists() or not backup_path.is_file():
            return {
                "success": False,
                "status": "CRÍTICO",
                "details": ["Backup full selecionado não existe."],
                "backup_file": str(backup_path),
                "restore_target_dir": str(restore_target),
                "manifest_file": str(manifest_path),
                "manifest_present": manifest_path.exists(),
                "hash_valid": False,
                "expected_files_ok": False,
            }

        if restore_target.exists():
            has_content = any(restore_target.iterdir())
            if has_content and not overwrite_confirmed:
                return {
                    "success": False,
                    "status": "CRÍTICO",
                    "details": ["Destino já possui conteúdo. Confirmação explícita de overwrite é obrigatória."],
                    "backup_file": str(backup_path),
                    "restore_target_dir": str(restore_target),
                    "manifest_file": str(manifest_path),
                    "manifest_present": manifest_path.exists(),
                    "hash_valid": False,
                    "expected_files_ok": False,
                }
            if has_content and overwrite_confirmed:
                shutil.rmtree(restore_target)

        restore_target.mkdir(parents=True, exist_ok=True)
        try:
            with ZipFile(backup_path, "r") as archive:
                archive.extractall(restore_target)
        except Exception as exc:
            return {
                "success": False,
                "status": "CRÍTICO",
                "details": [f"Falha ao extrair backup: {exc}"],
                "backup_file": str(backup_path),
                "restore_target_dir": str(restore_target),
                "manifest_file": str(manifest_path),
                "manifest_present": manifest_path.exists(),
                "hash_valid": False,
                "expected_files_ok": False,
            }

        validation = cls.validate_restored_full_backup_dev(
            backup_reference=str(backup_path),
            restore_target_dir=str(restore_target),
            root_path=root_path,
            require_manifest=require_manifest,
            validate_manifest_hash=validate_manifest_hash,
        )
        details.extend(validation.get("details", []))
        smoke_result = None
        if validation.get("success") and run_smoke_validation:
            smoke_result = cls.run_restore_smoke_validation_dev(
                restore_target_dir=str(restore_target),
                smoke_port=smoke_port,
                enforce_app_boot=enforce_app_boot,
            )
            details.extend(smoke_result.get("details", []))
        return {
            "success": bool(validation.get("success")) and bool((smoke_result or {}).get("success", True)),
            "status": (smoke_result or {}).get("status", validation.get("status", "CRÍTICO")),
            "details": details,
            "backup_file": str(backup_path),
            "restore_target_dir": str(restore_target),
            "manifest_file": str(manifest_path),
            "manifest_present": bool(validation.get("manifest_present")),
            "hash_valid": bool(validation.get("hash_valid")),
            "expected_files_ok": bool(validation.get("expected_files_ok")),
            "smoke_result": smoke_result,
        }

    @classmethod
    def _load_json_file(cls, path: Path) -> Tuple[bool, Optional[Any], str]:
        if not path.exists() or not path.is_file():
            return False, None, f"Arquivo ausente: {path}"
        try:
            with open(path, "r", encoding="utf-8") as stream:
                return True, json.load(stream), ""
        except Exception as exc:
            return False, None, f"Arquivo ilegível ({path.name}): {exc}"

    @classmethod
    def _run_app_boot_probe(cls, restore_target: Path, smoke_port: int) -> Tuple[bool, str]:
        app_file = restore_target / "app.py"
        app_pkg = restore_target / "app"
        if not app_file.exists() or not app_pkg.exists():
            return True, "Modo equivalente técnico aplicado (snapshot sem código da aplicação)."
        command = [
            sys.executable,
            "-c",
            (
                "import os,importlib.util;"
                "spec=importlib.util.spec_from_file_location('restore_app','app.py');"
                "mod=importlib.util.module_from_spec(spec);"
                "spec.loader.exec_module(mod);"
                "print('boot_probe_ok')"
            ),
        ]
        env = os.environ.copy()
        env["APP_PORT"] = str(int(smoke_port))
        env["FLASK_ENV"] = "development"
        try:
            result = subprocess.run(
                command,
                cwd=str(restore_target),
                env=env,
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
        except Exception as exc:
            return False, f"Falha no probe de inicialização: {exc}"
        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            stdout = (result.stdout or "").strip()
            return False, f"Probe de inicialização falhou. stdout='{stdout}' stderr='{stderr}'"
        return True, "Probe de inicialização da aplicação executado com sucesso."

    @classmethod
    def run_restore_smoke_validation_dev(
        cls,
        *,
        restore_target_dir: str,
        smoke_port: int = 5501,
        enforce_app_boot: bool = False,
    ) -> Dict[str, Any]:
        restore_target = Path(restore_target_dir)
        details: List[str] = []
        checks: Dict[str, Any] = {}

        essential_paths = {
            "system_config_file": restore_target / "system_config.json",
            "data_dir": restore_target / "data",
            "users_file": restore_target / "data" / "users.json",
        }
        essential_files_present = all(path.exists() for path in essential_paths.values())
        checks["essential_files_present"] = essential_files_present
        if not essential_files_present:
            missing = [name for name, path in essential_paths.items() if not path.exists()]
            return {
                "success": False,
                "status": "CRÍTICO",
                "details": [f"Arquivos essenciais ausentes: {', '.join(missing)}"],
                "restore_target_dir": str(restore_target),
                "checks": checks,
            }

        config_ok, config_data, config_error = cls._load_json_file(essential_paths["system_config_file"])
        checks["system_config_readable"] = config_ok
        if not config_ok:
            return {
                "success": False,
                "status": "CRÍTICO",
                "details": [config_error],
                "restore_target_dir": str(restore_target),
                "checks": checks,
            }
        checks["system_config_type"] = type(config_data).__name__

        users_ok, users_data, users_error = cls._load_json_file(essential_paths["users_file"])
        checks["users_file_readable"] = users_ok
        if not users_ok:
            return {
                "success": False,
                "status": "CRÍTICO",
                "details": [users_error],
                "restore_target_dir": str(restore_target),
                "checks": checks,
            }
        login_validation_ok = isinstance(users_data, list)
        checks["login_validation_ok"] = login_validation_ok
        checks["users_count"] = len(users_data) if isinstance(users_data, list) else 0
        if not login_validation_ok:
            return {
                "success": False,
                "status": "CRÍTICO",
                "details": ["Validação mínima de login falhou: users.json deve ser uma lista."],
                "restore_target_dir": str(restore_target),
                "checks": checks,
            }

        main_data_readable = False
        data_dir = essential_paths["data_dir"]
        json_files = sorted(data_dir.glob("*.json"))
        for candidate in json_files:
            ok, _, _ = cls._load_json_file(candidate)
            if ok:
                main_data_readable = True
                break
        checks["main_data_readable"] = main_data_readable
        if not main_data_readable:
            return {
                "success": False,
                "status": "CRÍTICO",
                "details": ["Não foi possível ler dados principais no diretório restaurado."],
                "restore_target_dir": str(restore_target),
                "checks": checks,
            }

        app_boot_ok, app_boot_detail = cls._run_app_boot_probe(restore_target, smoke_port)
        checks["app_boot_ok"] = app_boot_ok
        checks["smoke_port"] = int(smoke_port)
        details.append(app_boot_detail)
        if enforce_app_boot and not app_boot_ok:
            return {
                "success": False,
                "status": "CRÍTICO",
                "details": details,
                "restore_target_dir": str(restore_target),
                "checks": checks,
            }
        if not app_boot_ok:
            return {
                "success": False,
                "status": "ALERTA",
                "details": details,
                "restore_target_dir": str(restore_target),
                "checks": checks,
            }

        details.append("Smoke funcional DEV concluído com sucesso.")
        return {
            "success": True,
            "status": "OK",
            "details": details,
            "restore_target_dir": str(restore_target),
            "checks": checks,
        }

    @classmethod
    def resolve_environment(cls, environment: Optional[str] = None) -> str:
        env = str(environment or os.getenv("ALMAREIA_ENV") or "").strip().lower()
        if env in {"dev", "development"}:
            return "dev"
        if env in {"prod", "production"}:
            return "production"
        flask_env = str(os.getenv("FLASK_ENV") or "").strip().lower()
        if flask_env in {"dev", "development"}:
            return "dev"
        return "production"

    @classmethod
    def ensure_backup_structure(cls, environment: Optional[str] = None, root_path: Optional[str] = None) -> Dict[str, str]:
        env = cls.resolve_environment(environment)
        root = cls._resolve_backup_root(root_path)
        env_root = root / env
        paths = {
            "root": root,
            "environment_root": env_root,
            "full": env_root / "full",
            "operational": env_root / "operational",
            "manifests": env_root / "manifests",
            "health": env_root / "health",
        }
        for path in paths.values():
            path.mkdir(parents=True, exist_ok=True)
        return {key: str(path) for key, path in paths.items()}

    @classmethod
    def _resolve_path_from_config(cls, raw_path: Any, fallback: str) -> Path:
        raw = str(raw_path or fallback).strip()
        if not raw:
            raw = fallback
        candidate = Path(raw)
        if candidate.is_absolute():
            return candidate
        return Path(BASE_DIR) / candidate

    @classmethod
    def _collect_targets(cls) -> List[Tuple[Path, str]]:
        config = load_system_config() or {}
        uploads_dir = cls._resolve_path_from_config(config.get("uploads_dir"), "static/uploads")
        config_dir = Path(BASE_DIR) / "config"
        permissions_dir = Path(BASE_DIR) / "permissions"
        targets: List[Tuple[Path, str]] = [
            (Path(get_data_path("")), "data"),
            (Path(get_log_path("")), "logs"),
            (uploads_dir, "uploads"),
            (Path(get_fiscal_path("")), "fiscal_documents"),
            (config_dir, "config"),
            (Path(CONFIG_FILE), "system_config.json"),
            (Path(USERS_FILE), "users.json"),
            (Path(DEPARTMENT_PERMISSIONS_FILE), "permissions.json"),
            (permissions_dir, "permissions"),
        ]
        unique: Dict[str, Tuple[Path, str]] = {}
        for src, alias in targets:
            key = f"{str(src.resolve())}|{alias}"
            unique[key] = (src, alias)
        return list(unique.values())

    @classmethod
    def _iter_files_for_manifest(cls, source: Path, alias: str) -> List[Tuple[Path, str]]:
        files: List[Tuple[Path, str]] = []
        if not source.exists():
            return files
        if source.is_file():
            files.append((source, alias))
            return files
        for root, _, filenames in os.walk(source):
            root_path = Path(root)
            for filename in filenames:
                file_path = root_path / filename
                relative = file_path.relative_to(source).as_posix()
                archive_name = f"{alias}/{relative}" if relative else alias
                files.append((file_path, archive_name))
        return files

    @classmethod
    def _sha256_file(cls, file_path: Path) -> str:
        digest = hashlib.sha256()
        with open(file_path, "rb") as stream:
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
        return digest.hexdigest()

    @classmethod
    def _enforce_full_size_limit(cls, full_dir: Path, limit_bytes: int, keep_latest: Path) -> None:
        files = [path for path in full_dir.glob("full_*.zip") if path.is_file()]
        files.sort(key=lambda item: item.stat().st_mtime)
        total_size = sum(path.stat().st_size for path in files)
        for path in files:
            if total_size <= limit_bytes:
                return
            if path.resolve() == keep_latest.resolve():
                continue
            file_size = path.stat().st_size
            path.unlink(missing_ok=True)
            total_size -= file_size

    @classmethod
    def create_consistent_full_backup(
        cls,
        *,
        environment: Optional[str] = None,
        root_path: Optional[str] = None,
        consistency_mode: str = "app_stopped",
        app_confirmed_stopped: bool = False,
        pause_scheduler_during_backup: bool = True,
    ) -> Dict[str, Any]:
        env = cls.resolve_environment(environment)
        mode = str(consistency_mode or "").strip().lower()
        if mode not in {"app_stopped", "write_lock"}:
            raise ValueError("consistency_mode must be 'app_stopped' or 'write_lock'")
        if mode == "app_stopped" and not app_confirmed_stopped:
            raise ValueError("app_confirmed_stopped must be True when consistency_mode='app_stopped'")

        paths = cls.ensure_backup_structure(env, root_path)
        full_dir = Path(paths["full"])
        manifests_dir = Path(paths["manifests"])
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_filename = f"full_{env}_{timestamp}.zip"
        backup_path = full_dir / backup_filename
        targets = cls._collect_targets()
        archived_files: List[Dict[str, Any]] = []

        scheduler_paused = False
        try:
            if pause_scheduler_during_backup:
                scheduler_paused = cls._call_scheduler_control("pause_scheduler")
            lock_anchor = Path(BASE_DIR) / "full_backup_consistency.guard"
            lock_context = file_lock(str(lock_anchor)) if mode == "write_lock" else nullcontext()
            with lock_context:
                with ZipFile(backup_path, mode="w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
                    for source, alias in targets:
                        for file_path, archive_name in cls._iter_files_for_manifest(source, alias):
                            archive.write(file_path, arcname=archive_name)
                            stat = file_path.stat()
                            archived_files.append(
                                {
                                    "path": archive_name,
                                    "size_bytes": int(stat.st_size),
                                    "sha256": cls._sha256_file(file_path),
                                    "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                                }
                            )
        finally:
            if pause_scheduler_during_backup and scheduler_paused:
                cls._call_scheduler_control("resume_scheduler")

        backup_size = int(backup_path.stat().st_size)
        backup_sha = cls._sha256_file(backup_path)
        manifest = {
            "environment": env,
            "backup_type": "full",
            "timestamp": timestamp,
            "generated_at": datetime.now().isoformat(),
            "file_name": backup_filename,
            "file_path": str(backup_path),
            "size_bytes": backup_size,
            "sha256": backup_sha,
            "consistency_mode": mode,
            "scheduler_paused": bool(scheduler_paused),
            "archived_files": archived_files,
            "archived_count": len(archived_files),
        }
        manifest_path = manifests_dir / f"manifest_full_{env}_{timestamp}.json"
        with open(manifest_path, "w", encoding="utf-8") as stream:
            json.dump(manifest, stream, indent=2, ensure_ascii=False)

        if env == "production":
            cls._enforce_full_size_limit(full_dir, FULL_BACKUP_MAX_BYTES_PRODUCTION, keep_latest=backup_path)

        health = cls.evaluate_full_backup_health(environment=env, root_path=root_path)

        return {
            "success": True,
            "environment": env,
            "backup_file": str(backup_path),
            "manifest_file": str(manifest_path),
            "size_bytes": backup_size,
            "sha256": backup_sha,
            "archived_count": len(archived_files),
            "scheduler_paused": bool(scheduler_paused),
            "health_status": health.get("status"),
            "health_file": health.get("health_file"),
        }
