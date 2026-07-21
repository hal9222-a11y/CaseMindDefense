import os

APP_NAME = "CaseMind Defense"
APP_VERSION = "0.15.0"

BACKEND_BASE_URL = os.getenv("CASEMIND_BACKEND_URL", "http://127.0.0.1:8000")
# The analysis pages (Timeline, Contradictions, Insights) scan every chunk of the
# case; on a large phone dump (200k+ items) a cold load is 5-20s, and a 15s ceiling
# made the first load fail with "server unavailable". 60s covers it. Fast pages
# (status, evidence, persons) return in well under a second regardless.
REQUEST_TIMEOUT = int(os.getenv("CASEMIND_REQUEST_TIMEOUT", "60"))
