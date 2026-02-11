import os
import sys
import json
import socket
import time
import logging
from pyngrok import ngrok, conf

# Add parent directory to path to import app services if needed
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Logging configuration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("scripts/ngrok_manager.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("NgrokManager")

CONFIG_FILE = "data/ngrok_config.json"

def is_port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('localhost', port)) == 0

def load_config():
    if not os.path.exists(CONFIG_FILE):
        logger.error(f"Config file {CONFIG_FILE} not found.")
        return None
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading config: {e}")
        return None

def start_tunnels(env="development"):
    config = load_config()
    if not config or env not in config:
        logger.error(f"Environment {env} not found in config.")
        return

    env_config = config[env]
    port = env_config['port']

    logger.info(f"Checking if port {port} is active...")
    if not is_port_in_use(port):
        logger.warning(f"Port {port} is NOT active. Ensure the Flask server is running on this port.")
        # We continue anyway as the server might be started right after
    else:
        logger.info(f"Port {port} is active.")

    try:
        # Kill any existing tunnels to avoid conflicts
        # logger.info("Killing existing ngrok tunnels...")
        # ngrok.kill()
        logger.info("Skipping ngrok.kill() to preserve existing tunnels (per user request).")
        
        active_tunnels = []
        
        for tunnel_cfg in env_config['tunnels']:
            name = tunnel_cfg['name']
            domain = tunnel_cfg['domain']
            desc = tunnel_cfg['description']
            
            logger.info(f"Starting tunnel '{name}' ({desc}) -> {domain} on port {port}...")
            try:
                tunnel = ngrok.connect(port, domain=domain, name=name)
                logger.info(f" [OK] {name} active: {tunnel.public_url}")
                active_tunnels.append({
                    "name": name,
                    "url": tunnel.public_url,
                    "domain": domain,
                    "description": desc,
                    "status": "active",
                    "timestamp": time.strftime('%Y-%m-%d %H:%M:%S')
                })
            except Exception as e:
                logger.error(f" [FAILED] {name}: {e}")
                active_tunnels.append({
                    "name": name,
                    "error": str(e),
                    "domain": domain,
                    "description": desc,
                    "status": "failed",
                    "timestamp": time.strftime('%Y-%m-%d %H:%M:%S')
                })

        # Save current status to a file for the dashboard
        with open("data/ngrok_status.json", "w", encoding="utf-8") as f:
            json.dump({
                "environment": env,
                "port": port,
                "last_update": time.strftime('%Y-%m-%d %H:%M:%S'),
                "tunnels": active_tunnels
            }, f, indent=4)
            
        logger.info("All tunnels processed. Ngrok is running in the background.")
        
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Stopping ngrok manager...")
            ngrok.kill()
        logger.info("Keep this script running to maintain tunnels (if not using autostart).")
        
        # Keep alive loop
        while True:
            time.sleep(60)
            
    except KeyboardInterrupt:
        logger.info("Shutting down ngrok manager...")
        ngrok.kill()
    except Exception as e:
        logger.error(f"Critical error in Ngrok Manager: {e}")

if __name__ == "__main__":
    env = "development"
    if len(sys.argv) > 1:
        env = sys.argv[1]
    
    start_tunnels(env)
