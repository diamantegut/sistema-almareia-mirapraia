from flask import Blueprint

restaurant_bp = Blueprint('restaurant', __name__)

from . import routes
