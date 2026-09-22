from functools import lru_cache

from langchain_openai import ChatOpenAI

from src.config import config


@lru_cache(maxsize=None)
def get_llm(model: str) -> ChatOpenAI:
    return ChatOpenAI(model=model, api_key=config.OPENAI_API_KEY)
