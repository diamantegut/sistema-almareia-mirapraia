import os
import qrcode
import qrcode.image.svg

# Define paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_IMG_DIR = os.path.join(BASE_DIR, 'app', 'static', 'img')
ROOT_DIR = BASE_DIR

# Ensure directory exists
os.makedirs(STATIC_IMG_DIR, exist_ok=True)

# URL to encode
url = 'https://hospedes.almareia.mirapraia.ngrok.app/fila'

# Create QR Code factory (SVG Path Image for better vector quality)
factory = qrcode.image.svg.SvgPathImage

# Generate QR Code
img = qrcode.make(url, image_factory=factory)

# Save to static/img
static_path = os.path.join(STATIC_IMG_DIR, 'qr_fila.svg')
img.save(static_path)

# Save to root for easy access
root_path = os.path.join(ROOT_DIR, 'qrcode_fila.svg')
img.save(root_path)

print(f"QR Code (Vector SVG) para Fila gerado com sucesso!")
print(f"Arquivos salvos em:")
print(f"1. {static_path}")
print(f"2. {root_path}")
