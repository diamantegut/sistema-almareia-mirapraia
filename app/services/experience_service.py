import json
import os
import uuid
from datetime import datetime
from PIL import Image
from flask import current_app

DATA_DIR = os.path.join('data')
EXPERIENCES_FILE = os.path.join(DATA_DIR, 'guest_experiences.json')

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
    def create_experience(data):
        experiences = ExperienceService._load_data()
        
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
            'active': True,
            'price': data.get('price', '') # Optional
        }
        
        experiences.append(new_experience)
        if ExperienceService._save_data(experiences):
            return new_experience
        return None

    @staticmethod
    def update_experience(exp_id, data):
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
