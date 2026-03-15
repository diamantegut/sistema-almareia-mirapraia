from flask import Blueprint

quality_bp = Blueprint('quality', __name__)

from . import routes