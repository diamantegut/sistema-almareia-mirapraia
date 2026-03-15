from flask import Blueprint

assets_bp = Blueprint('assets', __name__)

from . import routes