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

# --- Execution Strategy (Free Tier vs Paid) ---
EXECUTION_MODE = os.getenv("EXECUTION_MODE", "sequential")  # "sequential" or "parallel"
DELAY_BETWEEN_NODES = int(os.getenv("DELAY_BETWEEN_NODES", "2"))
DELAY_BETWEEN_INCIDENTS = int(os.getenv("DELAY_BETWEEN_INCIDENTS", "15"))

# --- Model Failover Router ---
class ModelRouter:
    MODEL_PRIORITY = [
        {"provider": "groq",   "model": "llama-3.3-70b-versatile"}, # Primary
        {"provider": "openai", "model": "gpt-4o-mini"},           # Fallback
    ]
    
    def __init__(self):
        self.current_index = 0
        self.session_failures = {}
        self.model_usage_counts = {
            "groq/llama-3.3-70b-versatile": 0,
            "openai/gpt-4o-mini": 0,
        }
        self.rate_limit_switches = 0
    
    def select_model(self, difficulty: str) -> dict:
        """Select a model configuration based on incident difficulty and fallback state.
        - "hard" primary: OpenAI. Fallback: Groq.
        - otherwise primary: Groq. Fallback: OpenAI.
        """
        # If current_index > 0, we are in fallback mode
        in_fallback = (self.current_index > 0)
        
        if difficulty.lower() == "hard":
            return self.MODEL_PRIORITY[0] if in_fallback else self.MODEL_PRIORITY[1]
        else:
            return self.MODEL_PRIORITY[1] if in_fallback else self.MODEL_PRIORITY[0]

    def get_llm(self, difficulty: str = "easy", output_schema=None):
        from langchain_groq import ChatGroq
        from langchain_openai import ChatOpenAI
        from langchain_google_genai import ChatGoogleGenerativeAI
        from pydantic import SecretStr
        
        # Choose model based on difficulty (hard -> fallback, else primary)
        current_config = self.select_model(difficulty)
        provider = current_config["provider"]
        model = current_config["model"]
        full_model_name = f"{provider}/{model}"
        
        self.model_usage_counts[full_model_name] = self.model_usage_counts.get(full_model_name, 0) + 1
        
        if provider == "groq":
            llm = ChatGroq(model=model, temperature=0.1, api_key=SecretStr(GROQ_API_KEY), max_tokens=2048, max_retries=0)
        elif provider == "openai":
            llm = ChatOpenAI(model=model, temperature=0.1, api_key=SecretStr(OPENAI_API_KEY), max_tokens=2048, max_retries=0)
        else:
            raise ValueError(f"Unknown provider: {provider}")
        
        if output_schema:
            return llm.with_structured_output(output_schema)
        return llm
    
    def on_rate_limit(self):
        import traceback
        current_config = self.MODEL_PRIORITY[self.current_index]
        current_model = f"{current_config['provider']}/{current_config['model']}"
        self.session_failures[current_model] = "Rate Limited"
        self.rate_limit_switches += 1
        
        self.current_index += 1
        if self.current_index >= len(self.MODEL_PRIORITY):
            print(f"[ROUTER] All models exhausted. Sleeping 60s for rate limit resets...")
            import time
            time.sleep(60)
            self.current_index = 0
            
        next_config = self.MODEL_PRIORITY[self.current_index]
        next_model = f"{next_config['provider']}/{next_config['model']}"
        print(f"[ROUTER] {current_model} rate limited")
        print(f"[ROUTER] Switching to: {next_model}")
    
    def on_success(self):
        pass
        
    def reset(self):
        self.current_index = 0

import threading
llm_api_lock = threading.Lock()

def get_llm_with_fallback(router: ModelRouter, prompt=None, output_schema=None, difficulty: str = "easy"):
    """
    Wraps an LLM call with automatic failover and a global lock to prevent burst limits.
    Usage: response = get_llm_with_fallback(router).invoke(prompt) 
    """
    import groq
    import openai
    import google.api_core.exceptions
    import time
    
    # Infinite retry loop
    while True:
        try:
            with llm_api_lock:
                current_config = router.select_model(difficulty)
                current_model = f"{current_config['provider']}/{current_config['model']}"
                
                llm = router.get_llm(difficulty=difficulty, output_schema=output_schema)
                
                if prompt is not None:
                    result = llm.invoke(prompt)
                else:
                    result = llm
                
                # Add a 2 second delay inside the lock to ensure Groq never gets hit >30 RPM
                time.sleep(2)
                return result
            
        except groq.RateLimitError as e:
            print(f"[ROUTER] Rate limit on {current_model} -> switching")
            router.on_rate_limit()
        except openai.RateLimitError as e:
            print(f"[ROUTER] Rate limit on {current_model} -> switching")
            router.on_rate_limit()
        except Exception as e:
            # Langchain might wrap the API errors
            err_str = str(e).lower()
            safe_e = str(e).encode('ascii', 'replace').decode('ascii')
            if "429" in err_str or "rate limit" in err_str or "quota" in err_str or "resource exhausted" in err_str:
                print(f"[ROUTER] Rate limit (wrapped) on {current_model}: {safe_e} -> switching")
                router.on_rate_limit()
            else:
                # If it's not a rate limit, raise it to let tenacity handle it
                raise
    



