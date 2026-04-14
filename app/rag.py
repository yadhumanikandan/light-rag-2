import asyncio
import numpy as np
from lightrag import LightRAG, QueryParam
from lightrag.llm.openai import openai_complete_if_cache
from lightrag.utils import EmbeddingFunc
from app.config import DEEPSEEK_API_KEY, OPENAI_API_KEY, RAG_STORAGE_DIR


async def deepseek_complete(
    prompt, system_prompt=None, history_messages=[], **kwargs
):
    # DeepSeek does not support OpenAI structured outputs (completions.parse()).
    # LightRAG triggers this via keyword_extraction=True, which internally sets
    # response_format=<PydanticModel>. We disable that flag so openai_complete_if_cache
    # falls back to completions.create(); DeepSeek's prompts still ask for JSON
    # so the response content will be valid JSON without schema enforcement.
    kwargs.pop("keyword_extraction", None)
    kwargs.pop("response_format", None)
    return await openai_complete_if_cache(
        "deepseek-chat",
        prompt,
        system_prompt=system_prompt,
        history_messages=history_messages,
        api_key=DEEPSEEK_API_KEY,
        base_url="https://api.deepseek.com",
        **kwargs,
    )


async def openai_embed(texts):
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    response = await client.embeddings.create(
        model="text-embedding-3-small",
        input=texts,
    )
    return np.array([item.embedding for item in response.data])


def get_rag_instance():
    rag = LightRAG(
        working_dir=RAG_STORAGE_DIR,
        llm_model_func=deepseek_complete,
        embedding_func=EmbeddingFunc(
            embedding_dim=1536,
            max_token_size=8192,
            func=openai_embed,
        ),
    )
    return rag


# Singleton instance
_rag_instance = None


def get_rag():
    global _rag_instance
    if _rag_instance is None:
        _rag_instance = get_rag_instance()
    return _rag_instance


async def init_rag():
    """Must be called once at app startup to initialize LightRAG storages."""
    rag = get_rag()
    await rag.initialize_storages()
    return rag
