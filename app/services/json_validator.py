import json
import os
import logging

logger = logging.getLogger(__name__)

SCHEMAS = {
    'cashier_sessions': {
        'type': 'list',
        'item_schema': {
            'required': ['id', 'user', 'opened_at', 'status', 'transactions'],
            'types': {
                'id': str,
                'user': str,
                'status': str,
                'transactions': list
            }
        }
    },
    'menu_items': {
        'type': 'list',
        'item_schema': {
            'required': ['id', 'name', 'price'],
            'types': {
                'id': str,
                'name': str,
                # price can be float or int, handled in logic
            }
        }
    },
    'products': {
        'type': 'list',
        'item_schema': {
            'required': ['id', 'name', 'unit'],
            'types': {
                'id': str,
                'name': str,
                'unit': str
            }
        }
    }
}

def validate_json_file(file_path, schema_name):
    """
    Validates a JSON file against a simple schema.
    Returns (is_valid, message).
    """
    if not os.path.exists(file_path):
        return True, "File does not exist (skipped)"

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        return False, f"Invalid JSON syntax: {str(e)}"
    except Exception as e:
        return False, f"Error reading file: {str(e)}"

    schema = SCHEMAS.get(schema_name)
    if not schema:
        return True, "No schema defined for this type"

    if schema['type'] == 'list':
        if not isinstance(data, list):
            return False, "Root element must be a list"
        
        item_schema = schema.get('item_schema')
        if item_schema:
            required = item_schema.get('required', [])
            types = item_schema.get('types', {})
            
            for idx, item in enumerate(data):
                if not isinstance(item, dict):
                     return False, f"Item at index {idx} is not a dictionary"
                
                for field in required:
                    if field not in item:
                        return False, f"Item at index {idx} (ID: {item.get('id', 'unknown')}) missing required field: '{field}'"
                
                for field, expected_type in types.items():
                    if field in item and item[field] is not None:
                        if not isinstance(item[field], expected_type):
                            # Allow int for float requirement
                            if expected_type == float and isinstance(item[field], int):
                                continue
                            return False, f"Item at index {idx} (ID: {item.get('id', 'unknown')}) field '{field}' expected {expected_type.__name__}, got {type(item[field]).__name__}"

    return True, "Validation successful"
