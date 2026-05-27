"""AURA API 层 — completions、router、streaming"""
from app.api.router import router, get_backend_for_model
from app.api.completions import chat_completion, initialize_aura
