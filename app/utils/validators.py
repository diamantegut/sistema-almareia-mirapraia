import re
from datetime import datetime
import html

def validate_required(value, field_name):
    """Validates if a required field is present and not empty."""
    if not value or str(value).strip() == "":
        return False, f"O campo '{field_name}' é obrigatório."
    return True, None

def validate_phone(phone):
    """Validates Brazilian phone number (with or without mask)."""
    if not phone: return True, None # Optional
    # Remove non-digits
    digits = re.sub(r'\D', '', str(phone))
    if len(digits) not in [10, 11]:
        return False, "Telefone inválido. Deve ter 10 ou 11 dígitos."
    return True, None

def validate_cpf(cpf):
    """Validates CPF (basic format check)."""
    if not cpf: return True, None # Optional
    digits = re.sub(r'\D', '', str(cpf))
    if len(digits) != 11:
        return False, "CPF inválido. Deve ter 11 dígitos."
    # Basic validation of repeated digits
    if len(set(digits)) == 1:
        return False, "CPF inválido."
    return True, None

def validate_email(email):
    """Validates email format."""
    if not email: return True, None # Optional
    if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
        return False, "E-mail inválido."
    return True, None

def sanitize_input(text):
    """Sanitizes input against XSS."""
    if not text: return ""
    # Use html.escape for robust escaping
    return html.escape(str(text))

def validate_date(date_str, fmt='%Y-%m-%d'):
    """Validates date format."""
    if not date_str: return False, "Data inválida."
    try:
        datetime.strptime(date_str, fmt)
        return True, None
    except ValueError:
        return False, f"Data deve estar no formato {fmt}."

def validate_room_number(room_num):
    """Validates room number format (1-999)."""
    if not room_num: return False, "Número do quarto obrigatório."
    try:
        r = int(room_num)
        if 1 <= r <= 999:
            return True, None
        else:
            return False, "Número do quarto fora do intervalo válido."
    except ValueError:
        return False, "Número do quarto inválido."
