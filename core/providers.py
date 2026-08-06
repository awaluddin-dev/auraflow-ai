import os
from typing import Optional
from langchain_core.language_models.chat_models import BaseChatModel
from core.logger import get_logger
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent.parent / ".env")

logger = get_logger("providers")


def _load_gemini(model: str) -> Optional[BaseChatModel]:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return None
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(model=model, google_api_key=api_key)
    except Exception as e:
        logger.warning("Gemini load failed: %s", e)
        return None


def _load_openai(model: str) -> Optional[BaseChatModel]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
    try:
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=model, api_key=api_key)
    except Exception as e:
        logger.warning("OpenAI load failed: %s", e)
        return None


def _load_claude(model: str) -> Optional[BaseChatModel]:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    try:
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(model=model, api_key=api_key)
    except Exception as e:
        logger.warning("Claude load failed: %s", e)
        return None


def _load_groq(model: str) -> Optional[BaseChatModel]:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return None
    try:
        from langchain_groq import ChatGroq
        return ChatGroq(model=model, api_key=api_key)
    except Exception as e:
        logger.warning("Groq load failed: %s", e)
        return None


def _load_azure_openai(model: str) -> Optional[BaseChatModel]:
    api_key = os.getenv("AZURE_OPENAI_API_KEY")
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-01")
    if not api_key or not endpoint:
        return None
    try:
        from langchain_openai import AzureChatOpenAI
        return AzureChatOpenAI(
            azure_deployment=model,
            azure_endpoint=endpoint,
            api_key=api_key,
            api_version=api_version,
        )
    except Exception as e:
        logger.warning("Azure OpenAI load failed: %s", e)
        return None

def _load_custom(model: str) -> Optional[BaseChatModel]:
    """
    OpenAI-compatible custom endpoint.
    Works for: Ollama, OpenRouter, vLLM, LocalAI, atau provider apapun
    yang implement OpenAI chat completions API spec.

    Env vars:
        CUSTOM_LLM_BASE_URL  — required, e.g. http://localhost:11434/v1
        CUSTOM_LLM_API_KEY   — optional, pakai "ollama" jika tidak ada auth
        CUSTOM_LLM_MODEL     — override model name
    """
    base_url = os.getenv("CUSTOM_LLM_BASE_URL")
    if not base_url:
        return None
    try:
        from langchain_openai import ChatOpenAI
        api_key = os.getenv("CUSTOM_LLM_API_KEY", "custom")  # placeholder jika tidak ada auth
        return ChatOpenAI(
            model=model,
            base_url=base_url,
            api_key=api_key,
        )
    except Exception as e:
        logger.warning("Custom endpoint load failed: %s", e)
        return None

# Registry: urutan ini adalah fallback priority
PROVIDER_REGISTRY = {
    "gemini":       (_load_gemini,       "gemini-3.5-flash"),
    "openai":       (_load_openai,       "gpt-4o-mini"),
    "claude":       (_load_claude,       "claude-haiku-4-5-20251001"),
    "groq":         (_load_groq,         "openai/gpt-oss-20b"),
    "azure_openai": (_load_azure_openai, "gpt-4o-mini"),
    "custom":       (_load_custom,       "claude-opus-4-8"),
}


class LLMRouter:
    """
    Resolves LLM provider with fallback chain.
    Priority order is read from env: LLM_PROVIDER_ORDER=gemini,groq,openai
    Falls back to next available if current provider fails or has no API key.
    """

    def __init__(self):
        self._chain: list[tuple[str, BaseChatModel]] = []
        self._build_chain()

    def _build_chain(self):
        raw = os.getenv("LLM_PROVIDER_ORDER", "custom,gemini,groq,openai,claude,azure_openai")
        order = [p.strip() for p in raw.split(",")]

        for provider_name in order:
            if provider_name not in PROVIDER_REGISTRY:
                logger.warning("Unknown provider in LLM_PROVIDER_ORDER: %s", provider_name)
                continue

            loader, default_model = PROVIDER_REGISTRY[provider_name]
            model = os.getenv(f"{provider_name.upper()}_MODEL", default_model)
            instance = loader(model)

            if instance:
                self._chain.append((provider_name, instance))
                logger.info("Provider loaded: %s (model: %s)", provider_name, model)
            else:
                # Pesan berbeda untuk custom vs provider lain
                if provider_name == "custom":
                    logger.info("Provider skipped (no CUSTOM_LLM_BASE_URL): %s", provider_name)
                else:
                    logger.info("Provider skipped (no API key): %s", provider_name)  

        if not self._chain:
            raise RuntimeError("No LLM provider available. Set at least one API key in .env")

        logger.info(
            "Fallback chain: %s",
            " -> ".join(name for name, _ in self._chain)
        )

    def invoke(self, prompt: str) -> str:
        last_error = None

        for provider_name, llm in self._chain:
            try:
                logger.debug("Invoking provider: %s", provider_name)
                result = llm.invoke(prompt)
                content = result.content
                if isinstance(content, list):
                    extracted_text = ""
                    for item in content:
                        if isinstance(item, dict) and "text" in item:
                            extracted_text += item["text"]
                        elif isinstance(item, str):
                            extracted_text += item
                    return extracted_text.strip()
                else:
                    return str(content).strip()
            except Exception as e:
                logger.warning("Provider %s failed: %s", provider_name, e)
                last_error = e
                continue

        raise RuntimeError(f"All providers failed. Last error: {last_error}")