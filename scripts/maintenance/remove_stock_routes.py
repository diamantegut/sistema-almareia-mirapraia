import os

APP_PATH = r"f:\Sistema Almareia Mirapraia\app.py"

START_MARKER = "@app.route('/api/stock/consumption/<product_name>')"
END_MARKER = "return jsonify({'success': False, 'message': str(e)})"
# The END_MARKER is the last line of update_min_stock_bulk.
# But "return jsonify({'success': False, 'message': str(e)})" might be common.
# I should find the specific one.

def remove_block():
    with open(APP_PATH, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        
    start_idx = -1
    for i, line in enumerate(lines):
        if START_MARKER in line:
            start_idx = i
            break
            
    if start_idx == -1:
        print("Start marker not found")
        return

    # Find the end of update_min_stock_bulk
    # It ends before "@app.route('/department/log')"
    
    end_idx = -1
    for i in range(start_idx, len(lines)):
        if "@app.route('/department/log')" in lines[i]:
            end_idx = i
            break
            
    if end_idx == -1:
        print("End marker not found")
        return
        
    print(f"Removing lines {start_idx} to {end_idx}")
    
    # Remove the block
    new_lines = lines[:start_idx] + lines[end_idx:]
    
    with open(APP_PATH, 'w', encoding='utf-8') as f:
        f.writelines(new_lines)
        
    print("Block removed.")

if __name__ == "__main__":
    remove_block()
