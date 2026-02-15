
import qrcode
import svgwrite
from svgwrite import cm, mm
import base64
from PIL import Image, ImageOps
import io
import os
import math

# Configuration
URL = "https://menu.mirapraia.ngrok.app"
OUTPUT_DIR = "design_output"

if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

# Helper to add QR Code to a group
def add_qr_to_group(dwg, group, size_cm, border=0):
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M, # Medium is enough without logo
        box_size=10,
        border=border,
    )
    qr.add_data(URL)
    qr.make(fit=True)
    
    modules = qr.get_matrix()
    module_count = len(modules)
    module_size = size_cm * 10 / module_count # size in mm
    
    for r in range(module_count):
        for c in range(module_count):
            if modules[r][c]:
                x = c * module_size
                y = r * module_size
                # Use rectangles instead of path to avoid validation issues
                group.add(dwg.rect(insert=(x, y), size=(module_size, module_size)))
    
    return module_count, module_size

# --- LASER DESIGN (Simple) ---
def generate_laser_svg(filename):
    dwg = svgwrite.Drawing(os.path.join(OUTPUT_DIR, filename), size=('100mm', '100mm'), profile='tiny')
    center = (50, 50) # Center of 100mm
    radius = 45 # 90mm diameter
    
    # 1. CUT LAYER (Red)
    dwg.add(dwg.circle(center=center, r=radius, stroke='red', fill='none', stroke_width=0.5))
    
    # 2. ENGRAVE LAYER (Black)
    qr_group = dwg.g(id="qr_code", fill='black')
    
    qr_size_cm = 6
    qr_subgroup = dwg.g()
    add_qr_to_group(dwg, qr_subgroup, qr_size_cm)
    
    # Center QR
    qr_offset_x = 50 - (qr_size_cm * 10 / 2)
    qr_offset_y = 50 - (qr_size_cm * 10 / 2)
    
    qr_subgroup['transform'] = f"translate({qr_offset_x},{qr_offset_y})"
    qr_group.add(qr_subgroup)
    
    dwg.add(qr_group)
    dwg.save()

# --- PRINT DESIGN (Simple) ---
def generate_print_svg(filename):
    dwg = svgwrite.Drawing(os.path.join(OUTPUT_DIR, filename), size=('100mm', '100mm'), profile='full')
    
    qr_group = dwg.g(id="qr_code", fill='#000000') # Pure black for print
    qr_size_cm = 8 # Larger for print file, scalable
    
    qr_subgroup = dwg.g()
    add_qr_to_group(dwg, qr_subgroup, qr_size_cm)
    
    # Center in 100mm canvas
    qr_offset_x = 50 - (qr_size_cm * 10 / 2)
    qr_offset_y = 50 - (qr_size_cm * 10 / 2)

    qr_subgroup['transform'] = f"translate({qr_offset_x},{qr_offset_y})"
    qr_group.add(qr_subgroup)
    
    dwg.add(qr_group)
    dwg.save()

print("Generating Simple Laser File...")
generate_laser_svg("laser_simple.svg")

print("Generating Simple Print File...")
generate_print_svg("print_simple.svg")

print("Done.")
