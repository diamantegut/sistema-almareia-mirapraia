import json
import os
from app import create_app

def _is_truthy(value):
    return str(value or "").strip().lower() in ("1", "true", "yes", "on")

def is_debug_enabled():
    debug_env = os.environ.get("ALMAREIA_DEBUG")
    if debug_env is None:
        debug_env = os.environ.get("FLASK_DEBUG")
    if debug_env is not None:
        return _is_truthy(debug_env)
    runtime_env = str(os.environ.get("ALMAREIA_ENV") or "").strip().lower()
    return runtime_env in ("dev", "development")

# Carregar configuração de porta
def load_port():
    env_port = os.environ.get('ALMAREIA_PORT') or os.environ.get('PORT')
    if env_port:
        try:
            return int(str(env_port).strip())
        except Exception:
            print(f"Aviso: porta de ambiente invalida ({env_port}). Usando configuracao padrao.")
    try:
        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'system_config.json')
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
                return config.get('server_port', 5001)
    except Exception as e:
        print(f"Erro ao carregar configuração de porta: {e}")
    return 5001

# Inicializa a aplicação
app = create_app()

if __name__ == "__main__":
    port = load_port()
    debug_mode = is_debug_enabled()
    if debug_mode:
        print(f"--- INICIANDO SERVIDOR DE DESENVOLVIMENTO (Porta {port}) ---")
    else:
        print(f"--- INICIANDO SERVIDOR DE PRODUCAO (Porta {port}) ---")
    app.run(host='0.0.0.0', port=port, debug=debug_mode, use_reloader=debug_mode)
