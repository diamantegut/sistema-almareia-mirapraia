from app import app
from waitress import serve
import socket
import os

def get_ip_address():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # doesn't even have to be reachable
        s.connect(('10.255.255.255', 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = '127.0.0.1'
    finally:
        s.close()
    return IP

if __name__ == "__main__":
    host = '0.0.0.0'
    port = 5000
    ip = get_ip_address()
    
    # Print header
    print(f"-------------------------------------------------------")
    print(f" SISTEMA ALMAREIA MIRAPRAIA - SERVIDOR DE PRODUÇÃO")
    print(f"-------------------------------------------------------")
    print(f" Status: RODANDO")
    print(f" Acessar Localmente: http://127.0.0.1:{port}")
    print(f" Acessar na Rede:    http://{ip}:{port}")
    print(f"-------------------------------------------------------")
    print(f" Para parar o servidor, feche esta janela.")
    print(f"-------------------------------------------------------")
    
    # Run waitress
    serve(app, host=host, port=port, threads=6)

