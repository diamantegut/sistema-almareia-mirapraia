from flask import Blueprint

menu_bp = Blueprint('menu', __name__)

from . import routes