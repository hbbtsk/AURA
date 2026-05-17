"""AURA API 层 — completions、router、streaming"""
from app.api.router import router, get_backend_for_model
from app.api.completions import chat_completion, initialize_aura
from app.api.streaming import _build_streaming_response, _handle_non_streaming_request, _handle_streaming_request
