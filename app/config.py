from dotenv import load_dotenv
import os

load_dotenv()

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
RAG_STORAGE_DIR = os.getenv("RAG_STORAGE_DIR", "./rag_storage")
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "./uploads")
DOCUMENTS_DIR = os.getenv("DOCUMENTS_DIR", "./documents")
