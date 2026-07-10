import os

APP_NAME = "CaseMind Defense"
APP_VERSION = "0.15.0"

BACKEND_BASE_URL = os.getenv("CASEMIND_BACKEND_URL", "http://127.0.0.1:8000")
REQUEST_TIMEOUT = int(os.getenv("CASEMIND_REQUEST_TIMEOUT", "15"))
