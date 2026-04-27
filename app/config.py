from dotenv import load_dotenv
import os

load_dotenv()

OPENAI_API_KEY    = os.getenv("OPENAI_API_KEY")
DEEPSEEK_API_KEY  = os.getenv("DEEPSEEK_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
RAG_STORAGE_DIR  = os.getenv("RAG_STORAGE_DIR", "rag_storage")

# NAS / SMB share where KYC documents are archived
NAS_SERVER   = os.getenv("NAS_SERVER",   "192.168.0.5")
NAS_USER     = os.getenv("NAS_USER",     "RTCR002")
NAS_PASSWORD = os.getenv("NAS_PASSWORD", "Taamul@876")
NAS_SHARE    = os.getenv("NAS_SHARE",    "BANKS")
