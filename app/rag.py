import numpy as np
from lightrag import LightRAG
from lightrag.llm.openai import openai_complete_if_cache
from lightrag.utils import EmbeddingFunc, TiktokenTokenizer, Tokenizer

from app.config import DEEPSEEK_API_KEY, OPENAI_API_KEY, RAG_STORAGE_DIR


async def deepseek_complete(
    prompt: str,
    system_prompt: str | None = None,
    history_messages: list[dict] | None = None,
    **kwargs,
) -> str:
    # LightRAG may forward kwargs not supported by DeepSeek chat completions.
    kwargs.pop("keyword_extraction", None)
    kwargs.pop("response_format", None)

    return await openai_complete_if_cache(
        "deepseek-chat",
        prompt,
        system_prompt=system_prompt,
        history_messages=history_messages or [],
        api_key=DEEPSEEK_API_KEY,
        base_url="https://api.deepseek.com",
        **kwargs,
    )


async def openai_complete(
    prompt: str,
    system_prompt: str | None = None,
    history_messages: list[dict] | None = None,
    **kwargs,
) -> str:
    kwargs.pop("keyword_extraction", None)
    kwargs.pop("response_format", None)

    return await openai_complete_if_cache(
        "gpt-4.1-mini",
        prompt,
        system_prompt=system_prompt,
        history_messages=history_messages or [],
        api_key=OPENAI_API_KEY,
        **kwargs,
    )


async def openai_embed(texts: list[str]) -> np.ndarray:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    response = await client.embeddings.create(
        model="text-embedding-3-small",
        input=texts,
    )
    return np.array([item.embedding for item in response.data])


async def noop_embed(texts: list[str]) -> np.ndarray:
    return np.zeros((len(texts), 1536), dtype=float)


class _SimpleTokenizerBackend:
    def encode(self, content: str) -> list[int]:
        return [ord(c) for c in content]

    def decode(self, tokens: list[int]) -> str:
        return "".join(chr(token) for token in tokens)


def _get_tokenizer():
    try:
        return TiktokenTokenizer("gpt-4o-mini")
    except Exception:
        # Keep maintenance workflows usable if tokenizer download is unavailable.
        return Tokenizer(model_name="simple", tokenizer=_SimpleTokenizerBackend())


def get_rag_instance() -> LightRAG:
    llm_model_func = deepseek_complete if DEEPSEEK_API_KEY else openai_complete
    embedding_func = openai_embed if OPENAI_API_KEY else noop_embed

    return LightRAG(
        working_dir=RAG_STORAGE_DIR,
        tokenizer=_get_tokenizer(),
        llm_model_func=llm_model_func,
        embedding_func=EmbeddingFunc(
            embedding_dim=1536,
            max_token_size=8192,
            func=embedding_func,
        ),
    )


_rag_instance: LightRAG | None = None


def get_rag() -> LightRAG:
    global _rag_instance
    if _rag_instance is None:
        _rag_instance = get_rag_instance()
    return _rag_instance


async def init_rag() -> LightRAG:
    rag = get_rag()
    await rag.initialize_storages()
    return rag
