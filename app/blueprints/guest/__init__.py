from flask import Blueprint

guest_bp = Blueprint('guest', __name__)

from . import routes