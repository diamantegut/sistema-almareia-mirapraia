import json
import os
import sys

# Constants
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NGROK_CONFIG_PATH = os.path.join(BASE_DIR, 'data', 'ngrok_config.json')
SETTINGS_PATH = os.path.join(BASE_DIR, 'data', 'settings.json')
TARGET_DOMAIN = "syrupy-jaliyah-intracranial.ngrok-free.dev"
TARGET_TUNNEL_NAME = "staff"

def check_and_fix_ngrok_config():
    if not os.path.exists(NGROK_CONFIG_PATH):
        print(f"[WARN] {NGROK_CONFIG_PATH} not found.")
        return

    try:
        with open(NGROK_CONFIG_PATH, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        modified = False
        
        # Check both environments
        for env in ['development', 'production']:
            if env in config and 'tunnels' in config[env]:
                for tunnel in config[env]['tunnels']:
                    if tunnel['name'] == TARGET_TUNNEL_NAME:
                        if tunnel.get('domain') != TARGET_DOMAIN:
                            print(f"[FIX] Updating {env} '{TARGET_TUNNEL_NAME}' tunnel domain to {TARGET_DOMAIN}")
                            tunnel['domain'] = TARGET_DOMAIN
                            modified = True
        
        if modified:
            with open(NGROK_CONFIG_PATH, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=4)
            print("[SUCCESS] Ngrok configuration updated.")
        else:
            print("[OK] Ngrok configuration is correct.")
            
    except Exception as e:
        print(f"[ERROR] Failed to check/fix ngrok config: {e}")

def check_and_fix_settings():
    if not os.path.exists(SETTINGS_PATH):
        return

    try:
        with open(SETTINGS_PATH, 'r', encoding='utf-8') as f:
            settings = json.load(f)
            
        modified = False
        target_url = f"https://{TARGET_DOMAIN}"
        
        if settings.get('external_access_link') != target_url:
             print(f"[FIX] Updating settings 'external_access_link' to {target_url}")
             settings['external_access_link'] = target_url
             modified = True
             
        if modified:
            with open(SETTINGS_PATH, 'w', encoding='utf-8') as f:
                json.dump(settings, f, indent=4)
            print("[SUCCESS] Settings updated.")
        else:
            print("[OK] Settings configuration is correct.")
            
    except Exception as e:
        print(f"[ERROR] Failed to check/fix settings: {e}")

if __name__ == "__main__":
    print("--- Verifying Ngrok Configuration ---")
    check_and_fix_ngrok_config()
    check_and_fix_settings()
    print("-------------------------------------")
