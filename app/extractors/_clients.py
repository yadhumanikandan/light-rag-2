from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

from app.config import ANTHROPIC_API_KEY, OPENAI_API_KEY

CLAUDE_MODEL = "claude-sonnet-4-6"
OCR_MODEL = "gpt-5"

claude = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
openai = AsyncOpenAI(api_key=OPENAI_API_KEY)
