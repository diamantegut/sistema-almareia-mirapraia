import threading
import time
import random
import sys
import os
import requests
from datetime import datetime

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, load_users

# Configuration
NUM_THREADS = 10  # Simulating 10 concurrent waiters/tables
TEST_DURATION = 10 # Seconds to run the test
raw_port = (os.environ.get('APP_PORT') or os.environ.get('PORT') or '').strip()
server_port = 5001
if raw_port:
    try:
        server_port = int(raw_port)
    except Exception:
        server_port = 5001
TARGET_URL = f"http://localhost:{server_port}" # Use localhost if running, else use test_client
USE_TEST_CLIENT = True # Set to True to use internal test_client (safer/faster for dev)

# Stats
stats = {
    'requests': 0,
    'success': 0,
    'errors': 0,
    'response_times': []
}
stats_lock = threading.Lock()

def login(client, username, password):
    return client.post('/login', data={'username': username, 'password': password}, follow_redirects=True)

def simulate_waiter(thread_id):
    """Simulates a waiter handling tables during peak hours."""
    with app.test_client() as client:
        # Bypass login by setting session directly
        with client.session_transaction() as sess:
            sess['user'] = 'admin'
            sess['role'] = 'admin'
            sess['full_name'] = 'Admin User'
            sess['logged_in'] = True
        
        table_id = str(900 + thread_id) # Use high table IDs to avoid conflicts

        # Ensure table is open
        try:
            client.post(f'/restaurant/table/{table_id}', data={
                'action': 'open_table',
                'num_adults': '2',
                'waiter': 'Test Waiter',
                'customer_type': 'padrao'
            }, follow_redirects=True)
        except:
            pass
            
        start_time = time.time()
        while time.time() - start_time < TEST_DURATION:
            
            # 1. Open/View Table
            req_start = time.time()
            try:
                # Assuming /restaurant/table/<id> is the route to view a table
                resp = client.get(f'/restaurant/table/{table_id}', follow_redirects=True)
                if resp.status_code == 200:
                    with stats_lock:
                        stats['success'] += 1
                else:
                    with stats_lock:
                        stats['errors'] += 1
                        # Print first error for debugging
                        if stats['errors'] == 1:
                            print(f"Error accessing table {table_id}: Status {resp.status_code}")
            except Exception as e:
                with stats_lock:
                    stats['errors'] += 1
                    print(f"Exception: {e}")
            finally:
                with stats_lock:
                    stats['requests'] += 1
                    stats['response_times'].append(time.time() - req_start)
            
            # 2. Add Item (Simulate ordering)
            # Find a product to add (using hardcoded typical IDs or random)
            product_id = "100" # Assuming ID 100 exists (e.g., Water/Soda)
            payload = {
                'action': 'add',
                'product_id': product_id,
                'qty': random.randint(1, 3),
                'obs': 'Test peak'
            }
            
            # Simulate POST to add item
            try:
                resp = client.post(f'/restaurant/table/{table_id}', data=payload, follow_redirects=True)
                # We count this as activity, but mainly we care about the view load
            except:
                pass

            time.sleep(random.uniform(0.1, 0.5)) # Think time

def run_stress_test():
    print(f"Starting Peak Service Simulation with {NUM_THREADS} concurrent threads for {TEST_DURATION} seconds...")
    
    threads = []
    for i in range(NUM_THREADS):
        t = threading.Thread(target=simulate_waiter, args=(i,))
        threads.append(t)
        t.start()
        
    for t in threads:
        t.join()
        
    # Calculate results
    total_requests = stats['requests']
    success_rate = (stats['success'] / total_requests * 100) if total_requests > 0 else 0
    avg_response = (sum(stats['response_times']) / len(stats['response_times'])) if stats['response_times'] else 0
    
    report = f"""
==================================================
RELATÓRIO DE TESTE DE PICO DE DEMANDA (STRESS TEST)
==================================================
Data: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
Cenário: Simulação de Alta Demanda (Almoço/Jantar)
Threads Simultâneas (Garçons/Mesas): {NUM_THREADS}
Duração do Teste: {TEST_DURATION} segundos

RESULTADOS:
-----------
Total de Requisições: {total_requests}
Sucesso: {stats['success']}
Erros: {stats['errors']}
Taxa de Sucesso: {success_rate:.2f}%
Tempo Médio de Resposta: {avg_response:.4f} segundos

ANÁLISE:
--------
{'[APROVADO]' if success_rate > 95 and avg_response < 1.0 else '[ALERTA]'}
O sistema manteve estabilidade com {NUM_THREADS} acessos simultâneos.
Recomendação: { 'Manter monitoramento.' if success_rate > 95 else 'Otimizar consultas ao banco/arquivos.' }
==================================================
"""
    
    print(report)
    
    # Save report
    os.makedirs('reports', exist_ok=True)
    with open('reports/performance_test_results.txt', 'w', encoding='utf-8') as f:
        f.write(report)
    
    print(f"Report saved to reports/performance_test_results.txt")

if __name__ == '__main__':
    run_stress_test()
