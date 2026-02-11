import re
import os

APP_PATH = r"f:\Sistema Almareia Mirapraia\app.py"

FUNCTIONS_TO_REMOVE = [
    'menu_management',
    'config_categories',
    'delete_menu_item',
    'get_product_history',
    'list_menu_backups',
    'restore_menu_backup_route',
    'create_manual_backup',
    'diff_menu_backup',
    'toggle_menu_item_active',
    'flavor_config',
    'flavor_config_toggle_simple',
    'flavor_config_update_product_limit',
    'flavor_config_add_group',
    'flavor_config_delete_group',
    'flavor_config_add_item',
    'flavor_config_delete_item'
]

def remove_functions():
    with open(APP_PATH, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    new_lines = []
    skip = False
    
    # Identify start lines of functions
    func_starts = {}
    for i, line in enumerate(lines):
        for func in FUNCTIONS_TO_REMOVE:
            if re.match(r'^\s*def\s+' + func + r'\s*\(', line):
                func_starts[func] = i
    
    # We need to find the "route" decorator block preceding the function
    # Go backwards from def to find @app.route
    
    blocks_to_remove = [] # (start_idx, end_idx)
    
    sorted_starts = sorted(func_starts.items(), key=lambda x: x[1])
    
    for func, start_idx in sorted_starts:
        # Trace back to find decorators
        curr = start_idx - 1
        while curr >= 0:
            l = lines[curr].strip()
            if l.startswith('@'):
                curr -= 1
            else:
                break
        block_start = curr + 1
        
        # Trace forward to find end of function
        # The end is the start of the next top-level def or @
        # But we need to be careful about indentation.
        # Simplest heuristic: Read until next line that starts with non-whitespace and is NOT a comment or empty, 
        # and looks like a new function definition or decorator or class.
        
        curr = start_idx + 1
        while curr < len(lines):
            l = lines[curr]
            if l.strip() == '' or l.strip().startswith('#'):
                curr += 1
                continue
            
            # If line starts with non-whitespace
            if not l.startswith(' ') and not l.startswith('\t'):
                # Check if it's a new definition
                if l.startswith('def ') or l.startswith('@') or l.startswith('class ') or l.startswith('if __name__'):
                    break
            curr += 1
            
        block_end = curr
        blocks_to_remove.append((block_start, block_end))

    # Merge overlapping blocks and sort
    blocks_to_remove.sort()
    
    # Construct new content
    current_line = 0
    for start, end in blocks_to_remove:
        if start > current_line:
            new_lines.extend(lines[current_line:start])
        current_line = max(current_line, end)
    
    if current_line < len(lines):
        new_lines.extend(lines[current_line:])

    with open(APP_PATH, 'w', encoding='utf-8') as f:
        f.writelines(new_lines)
        
    print(f"Removed {len(blocks_to_remove)} blocks.")

if __name__ == "__main__":
    remove_functions()
