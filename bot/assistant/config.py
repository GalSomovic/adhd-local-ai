import os
from zoneinfo import ZoneInfo

MATRIX_HOMESERVER = os.environ["MATRIX_HOMESERVER"]
MATRIX_USER = os.environ["MATRIX_USER"]
MATRIX_PASSWORD = os.environ["MATRIX_PASSWORD"]
OWNER_MXID = os.environ["OWNER_MXID"]

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://ollama:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3:4b-instruct-2507-q4_K_M")

PUSHOVER_TOKEN = os.environ["PUSHOVER_TOKEN"]
PUSHOVER_USER = os.environ["PUSHOVER_USER"]

DATA_DIR = os.environ.get("DATA_DIR", "/data")
TZ = ZoneInfo(os.environ.get("TZ", "Asia/Jerusalem"))

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REFRESH_TOKEN = os.environ.get("GOOGLE_REFRESH_TOKEN", "")
BRIEF_TIME = os.environ.get("BRIEF_TIME", "07:00")

DEFAULT_WINDOW_MINUTES = int(os.environ.get("DEFAULT_WINDOW_MINUTES", "30"))
ALARM_RETRY_SECONDS = int(os.environ.get("ALARM_RETRY_SECONDS", "30"))
ALARM_EXPIRE_SECONDS = int(os.environ.get("ALARM_EXPIRE_SECONDS", "600"))
