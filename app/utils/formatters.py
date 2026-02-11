import unicodedata

def normalize_text(text):
    if not text:
        return ""
    return unicodedata.normalize('NFKD', text).encode('ASCII', 'ignore').decode('utf-8').lower()

def parse_br_currency(val):
    if not val: return 0.0
    if isinstance(val, (float, int)): return float(val)
    val = str(val).strip()
    
    # Clean currency symbols and spaces
    val = val.replace('R$', '').replace(' ', '')
    
    # If comma is present, assume BR format (1.000,00)
    if ',' in val:
        val_clean = val.replace('.', '').replace(',', '.')
        try:
            return float(val_clean)
        except ValueError:
            return 0.0
    else:
        # No comma, try parsing as standard float (handling 19.90 correctly)
        try:
            return float(val)
        except ValueError:
            return 0.0
