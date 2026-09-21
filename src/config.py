import os

from dotenv import load_dotenv

load_dotenv(override=True)  # Load environment variables from .env file

class Config:
    def __init__(self):
        self.OPENAI_API_KEY = self.get_required("OPENAI_API_KEY")

        # Optional: Langfuse tracing. Left unset -> tracing stays disabled.
        self.LANGFUSE_SECRET_KEY = self.get_required("LANGFUSE_SECRET_KEY")
        self.LANGFUSE_PUBLIC_KEY = self.get_required("LANGFUSE_PUBLIC_KEY")
        self.LANGFUSE_HOST = self.get_optional("LANGFUSE_HOST", "https://cloud.langfuse.com")

    @staticmethod
    def get_required(key: str) -> str:
        value = os.environ.get(key)
        if value is None:
            raise ValueError(f"Missing required configuration: {key}")
        return value

    @staticmethod
    def get_optional(key: str, default: str | None = None) -> str | None:
        return os.environ.get(key, default)

config = Config()