from flask import Blueprint

guest_portal_bp = Blueprint('guest_portal', __name__)

from . import routes