import re
import os

APP_PATH = r"f:\Sistema Almareia Mirapraia\app.py"

FUNCTIONS_TO_REMOVE = [
    'change_password',
    'forgot_password',
    'admin_reset_password_action'
]

def remove_functions():
    with open(APP_PATH, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    new_lines = []
    
    func_starts = {}
    for i, line in enumerate(lines):
        for func in FUNCTIONS_TO_REMOVE:
            if re.match(r'^def\s+' + re.escape(func) + r'\s*\(', line):
                func_starts[func] = i

    blocks_to_remove = [] # (start_idx, end_idx)
    
    for func, start_idx in func_starts.items():
        # Trace back to find decorators
        curr = start_idx - 1
        while curr >= 0:
            l = lines[curr].strip()
            if l.startswith('@'):
                curr -= 1
            elif l == '' or l.startswith('#'):
                 curr -= 1
            else:
                break
        block_start = curr + 1
        
        # Trace forward to find end of function
        curr = start_idx + 1
        while curr < len(lines):
            l = lines[curr]
            if l.strip() != '' and not l.strip().startswith('#'):
                if not l.startswith(' ') and not l.startswith('\t'):
                    if l.startswith('def ') or l.startswith('@') or l.startswith('class ') or l.startswith('if __name__'):
                        break
            curr += 1
            
        block_end = curr
        blocks_to_remove.append((block_start, block_end))

    blocks_to_remove.sort()
    
    merged_blocks = []
    if blocks_to_remove:
        curr_start, curr_end = blocks_to_remove[0]
        for start, end in blocks_to_remove[1:]:
            if start < curr_end:
                curr_end = max(curr_end, end)
            else:
                merged_blocks.append((curr_start, curr_end))
                curr_start, curr_end = start, end
        merged_blocks.append((curr_start, curr_end))
    
    current_line = 0
    for start, end in merged_blocks:
        if start > current_line:
            new_lines.extend(lines[current_line:start])
        current_line = max(current_line, end)
    
    if current_line < len(lines):
        new_lines.extend(lines[current_line:])

    with open(APP_PATH, 'w', encoding='utf-8') as f:
        f.writelines(new_lines)
        
    print(f"Removed {len(merged_blocks)} blocks covering {len(func_starts)} functions.")
    for f in func_starts:
        print(f"Removed: {f}")

if __name__ == "__main__":
    remove_functions()
