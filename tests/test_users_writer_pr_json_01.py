import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.services import data_service
from app.services import hr_service
from app.services import user_service
from app.services.permission_service import effective_profile_for_user, legacy_tokens_from_profile


def _configure_users_paths(monkeypatch, tmp_path):
    users_file = tmp_path / "users.json"
    hr_data_file = tmp_path / "hr_data.json"
    upload_dir = tmp_path / "uploads_hr"
    users_file.write_text("{}", encoding="utf-8")
    hr_data_file.write_text("{}", encoding="utf-8")
    upload_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(data_service, "USERS_FILE", str(users_file))
    monkeypatch.setattr(data_service, "_backup_before_write", lambda *_args, **_kwargs: None)

    monkeypatch.setattr(user_service, "USERS_FILE", str(users_file))

    monkeypatch.setattr(hr_service, "HR_DATA_FILE", str(hr_data_file))
    monkeypatch.setattr(hr_service, "UPLOAD_FOLDER", str(upload_dir))
    monkeypatch.setattr(hr_service, "load_core_users", data_service.load_users)
    monkeypatch.setattr(hr_service, "save_core_users", data_service.save_users)

    return users_file, hr_data_file


def test_criacao_usuario_via_writer_unico(monkeypatch, tmp_path):
    _configure_users_paths(monkeypatch, tmp_path)
    users = user_service.load_users()
    users["alice"] = {"password": "1234", "role": "colaborador", "department": "RH"}
    assert user_service.save_users(users) is True
    stored = data_service.load_users()
    assert "alice" in stored
    assert stored["alice"]["password"] == "1234"


def test_edicao_usuario_no_fluxo_rh(monkeypatch, tmp_path):
    _configure_users_paths(monkeypatch, tmp_path)
    data_service.save_users({"bob": {"password": "9999", "full_name": "Bob", "role": "colaborador"}})
    hr_service.update_employee_hr_data(
        "bob",
        {"full_name": "Bob Silva", "admission_date": "2026-01-01", "birthday": "1990-05-10", "status": "Ativo"},
    )
    stored = data_service.load_users()
    assert stored["bob"]["full_name"] == "Bob Silva"
    assert stored["bob"]["admission_date"] == "2026-01-01"
    assert stored["bob"]["birthday"] == "1990-05-10"


def test_inativacao_usuario_fluxo_rh(monkeypatch, tmp_path):
    _configure_users_paths(monkeypatch, tmp_path)
    data_service.save_users({"carol": {"password": "1111", "role": "colaborador"}})
    hr_service.terminate_employee("carol", "2026-03-15", "Desligamento")
    hr_payload = json.loads((tmp_path / "hr_data.json").read_text(encoding="utf-8"))
    assert hr_payload["carol"]["status"] == "Desligado"
    assert hr_payload["carol"]["termination_date"] == "2026-03-15"
    assert hr_payload["carol"]["termination_reason"] == "Desligamento"
    users_after = data_service.load_users()
    assert "carol" in users_after


def test_fluxo_rh_contratacao_mantem_escrita_via_owner(monkeypatch, tmp_path):
    _configure_users_paths(monkeypatch, tmp_path)
    calls = []

    def _spy_save(users):
        calls.append(dict(users))
        return data_service.save_users(users)

    monkeypatch.setattr(hr_service, "save_core_users", _spy_save)
    ok, _ = hr_service.hire_employee(
        "davi",
        "2222",
        {"role": "colaborador", "full_name": "Davi Souza", "admission_date": "2026-02-01"},
        {"company": "Almareia Hotel"},
    )
    assert ok is True
    assert len(calls) == 1
    assert "davi" in data_service.load_users()


def test_regressao_autenticacao_e_perfil_permissoes(monkeypatch, tmp_path):
    _configure_users_paths(monkeypatch, tmp_path)
    payload = {
        "erika": {
            "password": "4321",
            "role": "colaborador",
            "department": "Recepção",
            "permissions": ["recepcao"],
            "permissions_v2": {
                "version": 2,
                "areas": {"recepcao": {"all": True, "pages": {}}},
                "level_pages": [],
            },
            "full_name": "Erika Lima",
        }
    }
    assert user_service.save_users(payload) is True
    loaded = user_service.load_users()
    assert loaded["erika"]["password"] == "4321"
    profile = effective_profile_for_user("erika", loaded, {})
    legacy_tokens = legacy_tokens_from_profile(profile)
    assert profile["areas"]["recepcao"]["all"] is True
    assert "recepcao" in legacy_tokens


def test_so_data_service_save_users_grava_users_json(monkeypatch, tmp_path):
    _configure_users_paths(monkeypatch, tmp_path)
    owner_calls = {"count": 0}
    owner_impl = data_service.save_users

    def _owner_spy(users):
        owner_calls["count"] += 1
        return owner_impl(users)

    monkeypatch.setattr(data_service, "save_users", _owner_spy)
    monkeypatch.setattr(user_service.data_service, "save_users", _owner_spy)
    monkeypatch.setattr(hr_service, "save_core_users", _owner_spy)

    user_service.save_users({"fabi": {"password": "7777"}})
    hr_service.update_employee_hr_data("fabi", {"full_name": "Fabi"})
    assert owner_calls["count"] == 2
    project_root = Path(__file__).resolve().parents[1]
    source_user_service = (project_root / "app" / "services" / "user_service.py").read_text(encoding="utf-8")
    source_hr_service = (project_root / "app" / "services" / "hr_service.py").read_text(encoding="utf-8")
    assert "open(USERS_FILE, 'w'" not in source_user_service
    assert "save_json(USERS_FILE" not in source_hr_service


def test_concorrencia_basica_atualizacao_usuarios(monkeypatch, tmp_path):
    users_file, _ = _configure_users_paths(monkeypatch, tmp_path)

    def _writer(i):
        current = data_service.load_users()
        current[f"user_{i}"] = {"password": f"{1000 + i}"}
        return data_service.save_users(current)

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(_writer, range(20)))

    assert any(results)
    raw = users_file.read_text(encoding="utf-8")
    parsed = json.loads(raw)
    assert isinstance(parsed, dict)
