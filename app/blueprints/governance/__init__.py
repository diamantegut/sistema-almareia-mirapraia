from flask import Blueprint

governance_bp = Blueprint('governance', __name__)

from . import routes
