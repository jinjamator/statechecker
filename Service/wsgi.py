""" WSGI entry point for gunicorn (app.wsgi is upstream's, for mod_wsgi) """
import logging, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app
from app.models.utils import setup_logger

setup_logger(logging.getLogger("app"), quiet=True, stdout=True)
for name in ["app.models.aci.tools"]:
    logging.getLogger(name).setLevel(logging.INFO)

application = create_app("config.py")
