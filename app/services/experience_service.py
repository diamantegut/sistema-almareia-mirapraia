import json
import os
import uuid
from datetime import datetime
from PIL import Image
from flask import current_app

DATA_DIR = os.path.join('data')
EXPERIENCES_FILE = os.path.join(DATA_DIR, 'guest_experiences.json')
LAUNCHED_EXPERIENCES_FILE = os.path.join(DATA_DIR, 'launched_experiences.json')

class ExperienceService:
    @staticmethod
    def _load_data():
        if not os.path.exists(EXPERIENCES_FILE):
            return []
        try:
            with open(EXPERIENCES_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading experiences: {e}")
            return []

    @staticmethod
    def _save_data(data):
        try:
            with open(EXPERIENCES_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"Error saving experiences: {e}")
            return False

    @staticmethod
    def _load_launched_data():
        if not os.path.exists(LAUNCHED_EXPERIENCES_FILE):
            return []
        try:
            with open(LAUNCHED_EXPERIENCES_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading launched experiences: {e}")
            return []

    @staticmethod
    def _save_launched_data(data):
        try:
            with open(LAUNCHED_EXPERIENCES_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"Error saving launched experiences: {e}")
            return False

    @staticmethod
    def get_all_experiences(only_active=False):
        data = ExperienceService._load_data()
        if only_active:
            return [e for e in data if e.get('active', True)]
        return data

    @staticmethod
    def get_experience_by_id(exp_id):
        data = ExperienceService._load_data()
        for e in data:
            if e['id'] == exp_id:
                return e
        return None

    @staticmethod
    def _parse_money(value):
        if not value:
            return 0.0
        if isinstance(value, (int, float)):
            return float(value)
        # String cleanup
        value = str(value).replace('R$', '').strip()
        
        if ',' in value:
            # If comma exists, it's the decimal separator (PT-BR)
            # Remove all dots (thousands) and replace comma with dot
            value = value.replace('.', '').replace(',', '.')
        elif '.' in value:
            # No comma. Check if dot is thousands or decimal.
            # Heuristic: if last part has 3 digits, assume thousands (1.200)
            parts = value.split('.')
            if len(parts) > 1 and len(parts[-1]) == 3:
                value = value.replace('.', '')
            # else assume decimal (1.50)
            
        try:
            return float(value)
        except ValueError:
            return 0.0

    @staticmethod
    def _validate_commission(data):
        supplier = ExperienceService._parse_money(data.get('supplier_price'))
        guest = ExperienceService._parse_money(data.get('guest_price'))
        sales = ExperienceService._parse_money(data.get('sales_commission'))
        hotel = ExperienceService._parse_money(data.get('hotel_commission'))
        
        if supplier < 0 or guest < 0:
            return False, "Preços não podem ser negativos."

        expected = guest - supplier
        
        # Check distribution
        if (sales + hotel) > (expected + 0.01):
             return False, f"A soma das comissões (R$ {sales+hotel:.2f}) excede a Comissão Esperada (R$ {expected:.2f})."
             
        if sales < 0 or hotel < 0:
             return False, "Comissões não podem ser negativas."
             
        return True, None

    @staticmethod
    def create_experience(data):
        # Validate Commission Logic
        is_valid, error_msg = ExperienceService._validate_commission(data)
        if not is_valid:
            raise ValueError(error_msg)

        experiences = ExperienceService._load_data()
        
        # Calculate expected commission for consistency
        supplier_val = ExperienceService._parse_money(data.get('supplier_price'))
        guest_val = ExperienceService._parse_money(data.get('guest_price'))
        expected_val = guest_val - supplier_val if guest_val > supplier_val else 0.0
        
        new_experience = {
            'id': str(uuid.uuid4()),
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat(),
            'type': data.get('type'),
            'name': data.get('name'),
            'description': data.get('description'),
            'duration': data.get('duration'),
            'min_people': int(data.get('min_people', 1)),
            'max_people': int(data.get('max_people', 1)),
            'images': data.get('images', []), # List of filenames
            'video': data.get('video'), # Video filename (optional)
            'active': data.get('active', True),
            'price': data.get('price', ''), # Optional display price
            
            # Internal Info - Save as strings but normalized if possible? 
            # For now, keep as received to avoid formatting issues in UI if not needed.
            # But maybe we should normalize for report consistency?
            # Let's keep as is, but validation ensures they are parseable.
            'supplier_name': data.get('supplier_name', ''),
            'supplier_phone': data.get('supplier_phone', ''),
            'supplier_price': data.get('supplier_price', ''),
            'guest_price': data.get('guest_price', ''),
            'expected_commission': f"{expected_val:.2f}", # Save calculated value
            'sales_commission': data.get('sales_commission', ''),
            'hotel_commission': data.get('hotel_commission', '')
        }
        
        experiences.append(new_experience)
        if ExperienceService._save_data(experiences):
            return new_experience
        return None

    @staticmethod
    def update_experience(exp_id, data):
        # Validate Commission Logic if prices provided
        # We need to merge with existing data to validate correctly if partial update?
        # But update usually sends all fields from form.
        # Let's assume data contains all fields from form.
        
        is_valid, error_msg = ExperienceService._validate_commission(data)
        if not is_valid:
            raise ValueError(error_msg)

        experiences = ExperienceService._load_data()
        for e in experiences:
            if e['id'] == exp_id:
                e['updated_at'] = datetime.now().isoformat()
                if 'type' in data: e['type'] = data['type']
                if 'name' in data: e['name'] = data['name']
                if 'description' in data: e['description'] = data['description']
                if 'duration' in data: e['duration'] = data['duration']
                if 'min_people' in data: e['min_people'] = int(data['min_people'])
                if 'max_people' in data: e['max_people'] = int(data['max_people'])
                if 'price' in data: e['price'] = data['price']
                if 'images' in data: e['images'] = data['images'] # Replace or append logic handled by caller
                if 'video' in data: e['video'] = data['video']
                if 'active' in data: e['active'] = bool(data['active'])
                
                # Internal Info Updates
                if 'supplier_name' in data: e['supplier_name'] = data['supplier_name']
                if 'supplier_phone' in data: e['supplier_phone'] = data['supplier_phone']
                if 'supplier_price' in data: e['supplier_price'] = data['supplier_price']
                if 'guest_price' in data: e['guest_price'] = data['guest_price']
                
                # Recalculate expected commission if prices change
                if 'guest_price' in data or 'supplier_price' in data:
                    s_val = ExperienceService._parse_money(e.get('supplier_price'))
                    g_val = ExperienceService._parse_money(e.get('guest_price'))
                    exp_val = g_val - s_val if g_val > s_val else 0.0
                    e['expected_commission'] = f"{exp_val:.2f}"
                elif 'expected_commission' in data: 
                    # Fallback if prices didn't change but expected passed (shouldn't happen with new logic)
                    # But better to always calculate if we have prices.
                    pass 

                if 'sales_commission' in data: e['sales_commission'] = data['sales_commission']
                if 'hotel_commission' in data: e['hotel_commission'] = data['hotel_commission']
                
                ExperienceService._save_data(experiences)
                return e
        return None

    @staticmethod
    def delete_experience(exp_id):
        experiences = ExperienceService._load_data()
        new_list = [e for e in experiences if e['id'] != exp_id]
        if len(new_list) != len(experiences):
            ExperienceService._save_data(new_list)
            return True
        return False

    @staticmethod
    def toggle_active(exp_id):
        experiences = ExperienceService._load_data()
        for e in experiences:
            if e['id'] == exp_id:
                e['active'] = not e.get('active', True)
                ExperienceService._save_data(experiences)
                return e['active']
        return None

    @staticmethod
    def launch_experience(data):
        """
        Lança uma experiência para um hóspede.
        data deve conter:
        - experience_id
        - guest_name
        - room_number
        - collaborator_name (quem vendeu)
        - scheduled_date (data e hora agendada)
        - date (opcional, default now)
        - notes (opcional)
        """
        launches = ExperienceService._load_launched_data()
        
        exp = ExperienceService.get_experience_by_id(data.get('experience_id'))
        if not exp:
            return None
            
        launch_record = {
            'id': str(uuid.uuid4()),
            'launched_at': datetime.now().isoformat(),
            'scheduled_date': data.get('scheduled_date', ''),
            'experience_id': exp['id'],
            'experience_name': exp['name'],
            'supplier_name': exp.get('supplier_name', ''),
            'guest_name': data.get('guest_name'),
            'room_number': data.get('room_number'),
            'collaborator_name': data.get('collaborator_name'),
            'notes': data.get('notes', ''),
            
            # Freeze financial values at time of launch
            'supplier_price': exp.get('supplier_price', ''),
            'guest_price': exp.get('guest_price', ''),
            'sales_commission': exp.get('sales_commission', ''),
            'hotel_commission': exp.get('hotel_commission', '')
        }
        
        launches.append(launch_record)
        if ExperienceService._save_launched_data(launches):
            return launch_record
        return None

    @staticmethod
    def get_unique_collaborators():
        launches = ExperienceService._load_launched_data()
        collaborators = set()
        for l in launches:
            name = l.get('collaborator_name')
            if name:
                collaborators.add(name)
        return sorted(list(collaborators))


    @staticmethod
    def get_launched_experiences(filters=None):
        launches = ExperienceService._load_launched_data()
        if not filters:
            return launches
            
        filtered = []
        for l in launches:
            # Filter by date range
            if filters.get('start_date') and filters.get('end_date'):
                launch_date = datetime.fromisoformat(l['launched_at']).date()
                start = datetime.strptime(filters['start_date'], '%Y-%m-%d').date()
                end = datetime.strptime(filters['end_date'], '%Y-%m-%d').date()
                if not (start <= launch_date <= end):
                    continue
                    
            # Filter by collaborator
            if filters.get('collaborator') and filters['collaborator'].lower() not in l.get('collaborator_name', '').lower():
                continue
                
            # Filter by supplier
            if filters.get('supplier') and filters['supplier'].lower() not in l.get('supplier_name', '').lower():
                continue
                
            filtered.append(l)
            
        # Sort by date desc
        filtered.sort(key=lambda x: x['launched_at'], reverse=True)
        return filtered

    @staticmethod
    def toggle_commission_paid(launch_id):
        launches = ExperienceService._load_launched_data()
        found = False
        new_status = False
        
        for l in launches:
            if l['id'] == launch_id:
                l['commission_paid'] = not l.get('commission_paid', False)
                if l['commission_paid']:
                    l['commission_paid_at'] = datetime.now().isoformat()
                else:
                    l.pop('commission_paid_at', None)
                new_status = l['commission_paid']
                found = True
                break
        
        if found:
            ExperienceService._save_launched_data(launches)
            return new_status
        return None


    @staticmethod
    def process_video(file):
        """
        Save uploaded video file.
        Returns filename or None.
        """
        if not file or not file.filename:
            return None
            
        upload_folder = os.path.join(current_app.static_folder, 'uploads', 'experiences')
        os.makedirs(upload_folder, exist_ok=True)
        
        try:
            ext = os.path.splitext(file.filename)[1].lower()
            if ext not in ['.mp4', '.mov', '.webm']:
                return None
                
            filename = f"vid_{uuid.uuid4().hex}{ext}"
            filepath = os.path.join(upload_folder, filename)
            
            file.save(filepath)
            return filename
        except Exception as e:
            print(f"Error processing video {file.filename}: {e}")
            return None

    @staticmethod
    def process_images(files):
        """
        Process uploaded images: resize, compress, save.
        Returns list of filenames.
        """
        saved_filenames = []
        upload_folder = os.path.join(current_app.static_folder, 'uploads', 'experiences')
        os.makedirs(upload_folder, exist_ok=True)
        
        for file in files:
            if file and file.filename:
                try:
                    # Generate safe filename
                    ext = os.path.splitext(file.filename)[1].lower()
                    if ext not in ['.jpg', '.jpeg', '.png', '.webp']:
                        continue
                        
                    filename = f"{uuid.uuid4().hex}{ext}"
                    filepath = os.path.join(upload_folder, filename)
                    
                    # Open and compress
                    img = Image.open(file)
                    
                    # Convert RGBA to RGB if needed
                    if img.mode in ('RGBA', 'P'):
                        img = img.convert('RGB')
                        
                    # Resize if too large (max 1920px width)
                    if img.width > 1920:
                        ratio = 1920 / img.width
                        new_height = int(img.height * ratio)
                        img = img.resize((1920, new_height), Image.Resampling.LANCZOS)
                        
                    # Save with compression
                    img.save(filepath, optimize=True, quality=85)
                    saved_filenames.append(filename)
                except Exception as e:
                    print(f"Error processing image {file.filename}: {e}")
                    
        return saved_filenames
