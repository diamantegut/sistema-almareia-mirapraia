import os
import re
import sys
from flask import Flask
from collections import defaultdict

# Add app to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app

def analyze_template(file_path, app_endpoints):
    errors = []
    warnings = []
    
    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()
        lines = content.split('\n')
        
    # 1. Jinja2 Block Balance
    blocks = re.findall(r'{%\s*block\s+(\w+)\s*%}', content)
    endblocks = re.findall(r'{%\s*endblock\s*%}', content)
    if len(blocks) != len(endblocks):
        errors.append(f"Mismatched blocks: {len(blocks)} blocks vs {len(endblocks)} endblocks")
        
    ifs = re.findall(r'{%\s*if\s+.*?%}', content)
    endifs = re.findall(r'{%\s*endif\s*%}', content)
    if len(ifs) != len(endifs):
        errors.append(f"Mismatched ifs: {len(ifs)} ifs vs {len(endifs)} endifs")
        
    fors = re.findall(r'{%\s*for\s+.*?%}', content)
    endfors = re.findall(r'{%\s*endfor\s*%}', content)
    if len(fors) != len(endfors):
        errors.append(f"Mismatched fors: {len(fors)} fors vs {len(endfors)} endfors")

    # 2. Check url_for endpoints
    # Pattern: url_for('endpoint', ...) or url_for("endpoint", ...)
    url_fors = re.findall(r"url_for\(['\"]([\w\.]+)['\"]", content)
    for endpoint in url_fors:
        if endpoint != 'static' and endpoint not in app_endpoints:
            # Check if it's a dynamic part (unlikely in simple string, but possible)
            errors.append(f"Invalid endpoint in url_for: '{endpoint}'")

    # 3. Check for static files existence (Basic)
    # Pattern: filename='img/logo.png'
    static_refs = re.findall(r"filename=['\"](.*?)['\"]", content)
    static_folder = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'app', 'static')
    
    for ref in static_refs:
        # Ignore variables
        if '{{' in ref or '}}' in ref:
            continue
            
        full_path = os.path.join(static_folder, ref.replace('/', os.sep))
        if not os.path.exists(full_path):
            # Try removing query params if any
            if '?' in full_path:
                full_path = full_path.split('?')[0]
                if os.path.exists(full_path):
                    continue
            warnings.append(f"Missing static file: {ref}")

    # 4. Check for deprecated or problematic HTML tags
    if '<center>' in content:
        warnings.append("Usage of deprecated <center> tag")
    if '<font' in content:
        warnings.append("Usage of deprecated <font> tag")
        
    return errors, warnings

def main():
    print("Starting Template Audit...")
    
    # Initialize App to get endpoints
    try:
        app = create_app()
        app_endpoints = set([rule.endpoint for rule in app.url_map.iter_rules()])
        # Manually add some that might be missing or dynamic
        app_endpoints.add('static')
        print(f"Loaded {len(app_endpoints)} application endpoints.")
    except Exception as e:
        print(f"Error loading app: {e}")
        app_endpoints = set()
    
    with open('valid_endpoints_dump.txt', 'w', encoding='utf-8') as f_eps:
        for ep in sorted(list(app_endpoints)):
            f_eps.write(f"{ep}\n")
            
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    templates_dir = os.path.join(base_dir, 'app', 'templates')
    
    results = {}
    
    for root, dirs, files in os.walk(templates_dir):
        for file in files:
            if file.endswith('.html'):
                file_path = os.path.join(root, file)
                rel_path = os.path.relpath(file_path, templates_dir)
                
                errors, warnings = analyze_template(file_path, app_endpoints)
                
                if errors or warnings:
                    results[rel_path] = {'errors': errors, 'warnings': warnings}

    with open('audit_report_raw.txt', 'w', encoding='utf-8') as f_out:
        f_out.write("=== AUDIT RESULTS ===\n\n")
        f_out.write(f"Loaded {len(app_endpoints)} application endpoints.\n")
        
        if not results:
            f_out.write("No major issues found.\n")
        else:
            for file, issues in results.items():
                if issues['errors'] or issues['warnings']:
                    f_out.write(f"File: {file}\n")
                    for err in issues['errors']:
                        f_out.write(f"  [ERROR] {err}\n")
                    for warn in issues['warnings']:
                        f_out.write(f"  [WARN]  {warn}\n")
                    f_out.write("-" * 40 + "\n")

if __name__ == "__main__":
    main()
