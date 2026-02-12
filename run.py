import json
import os
from app import create_app

# Carregar configuração de porta
def load_port():
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
    print(f"--- INICIANDO SERVIDOR DE DESENVOLVIMENTO (Porta {port}) ---")
    app.run(host='0.0.0.0', port=port, debug=True)
