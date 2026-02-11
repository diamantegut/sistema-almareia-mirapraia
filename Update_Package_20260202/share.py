import time
from pyngrok import ngrok
import sys
import socket
import json
import os

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "127.0.0.1"

def load_settings_domain():
    try:
        # Caminho relativo para data/settings.json ou settings.json na raiz
        paths = [
            os.path.join("data", "settings.json"),
            "settings.json"
        ]
        
        for p in paths:
            if os.path.exists(p):
                with open(p, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    link = data.get("external_access_link", "")
                    # Extrair domínio de https://dominio.com
                    if link:
                        return link.replace("https://", "").replace("http://", "").split("/")[0]
    except Exception as e:
        print(f"Erro ao ler settings.json: {e}")
    return None

def start_tunnel():
    local_ip = get_local_ip()
    print(f"\n==================================================================")
    print(f" * ACESSO NA REDE LOCAL (WI-FI)")
    print(f" * Link: http://{local_ip}:5000")
    print(f"==================================================================\n")

    print("Tentando iniciar túnel para acesso externo (Internet)...")
    
    # Desconecta túneis existentes
    ngrok.kill()
    
    # Abre um túnel HTTP na porta 5001
    try:
        domain = load_settings_domain()
        public_url = ""
        
        if domain:
            print(f"Tentando conectar com domínio fixo: {domain}")
            try:
                public_url = ngrok.connect(5000, domain=domain).public_url
            except Exception as e:
                print(f"Falha ao usar domínio {domain}: {e}")
                print("Tentando domínio aleatório...")
                public_url = ngrok.connect(5000).public_url
        else:
            public_url = ngrok.connect(5000).public_url

        print(f"\n==================================================================")
        print(f" * SISTEMA ONLINE PARA ACESSO EXTERNO (INTERNET)")
        print(f" * Link Público: {public_url}")
        print(f" * Envie este link para quem precisa acessar de fora.")
        print(f"==================================================================\n")
        
        # Mantém o script rodando
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("Encerrando compartilhamento...")
            ngrok.kill()
            sys.exit(0)
            
    except Exception as e:
        print(f"\n[ERRO] Não foi possível iniciar o acesso externo via Ngrok.")
        print(f"Detalhe: {e}")
        print("\nPARA CORRIGIR:")
        print("1. Crie uma conta grátis em https://dashboard.ngrok.com/signup")
        print("2. Copie seu Authtoken")
        print("3. Execute no terminal: ngrok config add-authtoken SEU_TOKEN")
        print("4. Execute novamente: python share.py")

if __name__ == "__main__":
    start_tunnel()

