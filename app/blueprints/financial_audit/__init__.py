from flask import Blueprint

financial_audit_bp = Blueprint('financial_audit', __name__)

from . import routes
