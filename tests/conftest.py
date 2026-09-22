import os
from unittest.mock import patch

# src/config.py calls load_dotenv(override=True) and raises on missing keys at import
# time. Neutralise it so tests never read the real .env, then seed placeholders: every
# LLM is mocked in the tests, so nothing reaches a real API.
with patch("dotenv.load_dotenv", lambda *args, **kwargs: False):
    os.environ["OPENAI_API_KEY"] = "test-placeholder-not-a-real-key"
    os.environ["LANGFUSE_SECRET_KEY"] = ""
    os.environ["LANGFUSE_PUBLIC_KEY"] = ""
    import src.config  # noqa: F401  - imported here so the patch applies to its load_dotenv
