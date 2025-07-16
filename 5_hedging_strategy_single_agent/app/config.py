import os
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
DEFAULT_MODEL  = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
