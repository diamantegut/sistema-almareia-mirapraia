import json
import os
import socket
import sys

CONFIG_FILE = 'system_config.json'
DEFAULT_PORT = 5001

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Erro ao ler arquivo de configuração: {e}")
            return {}
    return {}

def save_config(config):
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=4)
        return True
    except Exception as e:
        print(f"Erro ao salvar configuração: {e}")
        return False

def is_port_available(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('localhost', port)) != 0

def main():
    print("=== Configuração de Porta do Sistema Almareia Mirapraia ===")
    
    config = load_config()
    current_port = config.get('server_port', DEFAULT_PORT)
    
    print(f"\nA porta atual configurada é: {current_port}")
    
    while True:
        user_input = input(f"Digite a nova porta (ou pressione Enter para manter {current_port}): ").strip()
        
        if not user_input:
            port_to_use = current_port
            break
            
        if not user_input.isdigit():
            print("Erro: Por favor, digite um número válido.")
            continue
            
        port_to_use = int(user_input)
        
        if not (1024 <= port_to_use <= 65535):
            print("Erro: A porta deve estar entre 1024 e 65535.")
            continue
            
        if not is_port_available(port_to_use):
            print(f"Aviso: A porta {port_to_use} parece estar em uso no momento.")
            confirm = input("Deseja usar esta porta mesmo assim? (s/n): ").lower()
            if confirm != 's':
                continue
        
        break
    
    print(f"\nConfigurando sistema para usar a porta: {port_to_use}...")
    
    config['server_port'] = port_to_use
    
    if save_config(config):
        print("✅ Configuração salva com sucesso!")
        print(f"O sistema usará a porta {port_to_use} na próxima inicialização.")
    else:
        print("❌ Falha ao salvar a configuração.")
        
    input("\nPressione Enter para sair...")

if __name__ == "__main__":
    main()
