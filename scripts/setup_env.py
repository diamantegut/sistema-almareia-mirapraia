import json
import os
import sys
import argparse

# Constants
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NGROK_CONFIG_PATH = os.path.join(BASE_DIR, 'data', 'ngrok_config.json')
SETTINGS_PATH = os.path.join(BASE_DIR, 'data', 'settings.json')
SYSTEM_CONFIG_PATH = os.path.join(BASE_DIR, 'system_config.json')

def update_system_config(port):
    if not os.path.exists(SYSTEM_CONFIG_PATH):
        print(f"[WARN] {SYSTEM_CONFIG_PATH} not found.")
        return

    try:
        with open(SYSTEM_CONFIG_PATH, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        config['server_port'] = int(port)
        
        with open(SYSTEM_CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=4)
        print(f"[SUCCESS] Updated system_config.json port to {port}.")
    except Exception as e:
        print(f"[ERROR] Failed to update system_config.json: {e}")

def update_ngrok_config(env, port, domain, guest_domain=None):
    if not os.path.exists(NGROK_CONFIG_PATH):
        print(f"[WARN] {NGROK_CONFIG_PATH} not found.")
        return

    try:
        with open(NGROK_CONFIG_PATH, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        if env not in config:
            print(f"[ERROR] Environment '{env}' not found in ngrok_config.json.")
            return

        # Update port for the environment
        config[env]['port'] = int(port)

        # Update staff tunnel domain (other tunnels, including 'menu', keep fixed domains/ports)
        modified = False
        for tunnel in config[env]['tunnels']:
            if tunnel['name'] == 'staff':
                if tunnel.get('domain') != domain:
                    tunnel['domain'] = domain
                    modified = True
                    print(f"[FIX] Updated {env} 'staff' tunnel domain to {domain}")
            elif tunnel['name'] == 'guest_portal' and guest_domain:
                if tunnel.get('domain') != guest_domain:
                    tunnel['domain'] = guest_domain
                    modified = True
                    print(f"[FIX] Updated {env} 'guest_portal' tunnel domain to {guest_domain}")
        
        if modified or config[env]['port'] != int(port):
            with open(NGROK_CONFIG_PATH, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=4)
            print(f"[SUCCESS] Updated ngrok_config.json for {env}.")
        else:
            print(f"[OK] ngrok_config.json for {env} is already correct.")

    except Exception as e:
        print(f"[ERROR] Failed to update ngrok_config.json: {e}")

def update_settings(domain):
    if not os.path.exists(SETTINGS_PATH):
        print(f"[WARN] {SETTINGS_PATH} not found.")
        return

    try:
        with open(SETTINGS_PATH, 'r', encoding='utf-8') as f:
            settings = json.load(f)
            
        target_url = f"https://{domain}"
        
        if settings.get('external_access_link') != target_url:
             print(f"[FIX] Updating settings 'external_access_link' to {target_url}")
             settings['external_access_link'] = target_url
             with open(SETTINGS_PATH, 'w', encoding='utf-8') as f:
                json.dump(settings, f, indent=4)
             print("[SUCCESS] Settings updated.")
        else:
            print("[OK] Settings configuration is correct.")
            
    except Exception as e:
        print(f"[ERROR] Failed to update settings.json: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Setup environment configuration.')
    parser.add_argument('--env', choices=['development', 'production'], help='Environment (development/production)')
    parser.add_argument('--port', required=True, type=int, help='Server port')
    parser.add_argument('--domain', help='Ngrok domain')
    parser.add_argument('--guest-domain', help='Ngrok guest domain')
    parser.add_argument(
        '--no-ngrok',
        action='store_true',
        help='Atualiza apenas a porta em system_config.json, sem alterar ngrok_config/settings'
    )

    args = parser.parse_args()

    print(f"--- Atualizando configuracao de porta (Port: {args.port}) ---")
    update_system_config(args.port)

    if not args.no_ngrok:
        if not args.env or not args.domain:
            print("[ERROR] --env e --domain sao obrigatorios quando o ngrok deve ser atualizado.")
            sys.exit(1)

        print(f"--- Atualizando configuracao do NGROK ({args.env.upper()}, Domain: {args.domain}) ---")
        update_ngrok_config(args.env, args.port, args.domain, args.guest_domain)
        update_settings(args.domain)

    print("---------------------------------------------------------------")
