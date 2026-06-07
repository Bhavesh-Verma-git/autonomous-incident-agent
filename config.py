import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# --- LLM Settings ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "llama-3.3-70b-versatile")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2") # Used locally by sentence-transformers

# --- Agent Behavior ---
CONFIDENCE_THRESHOLD = float(os.getenv("CONFIDENCE_THRESHOLD", "0.7"))
MAX_LOG_LINES = int(os.getenv("MAX_LOG_LINES", "50"))

# --- Database & Storage Paths ---
CHROMA_PERSIST_DIR = os.getenv("CHROMA_PERSIST_DIR", "./memory/chroma_db")
CHROMA_COLLECTION_NAME = os.getenv("CHROMA_COLLECTION_NAME", "past_incidents")
SQLITE_DB_PATH = os.getenv("SQLITE_DB_PATH", "./memory/checkpoints.db")

# --- Observability (Langfuse) ---
LANGFUSE_PUBLIC_KEY = os.getenv("LANGFUSE_PUBLIC_KEY", "")
LANGFUSE_SECRET_KEY = os.getenv("LANGFUSE_SECRET_KEY", "")
LANGFUSE_HOST = os.getenv("LANGFUSE_HOST", "http://localhost:3000")

# --- API Layer ---
API_HOST  = os.getenv("API_HOST", "0.0.0.0")
API_PORT  = int(os.getenv("API_PORT", "8000"))
API_DEBUG = os.getenv("API_DEBUG", "True").lower() in ("true", "1", "t")
API_KEY   = os.getenv("API_KEY", "")  # Secret password for all protected endpoints

