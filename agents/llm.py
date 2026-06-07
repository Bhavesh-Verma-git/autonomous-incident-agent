"""
agents/llm.py — LLM initialisation helpers with multi-provider fallbacks.

Centralises all LLM creation so nodes never hardcode model names.
Includes fallback routing: Groq Llama -> Groq Mixtral -> Gemini -> OpenAI
to handle rate limits or API outages invisibly.
"""

from typing import Any
from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import SecretStr
import config


def get_llm(temperature: float = 0.1):
    """
    Return a ChatGroq instance pointing to the Groq Cloud API,
    with automatic fallbacks to other models and providers.
    """
    if not config.GROQ_API_KEY:
        raise ValueError("GROQ_API_KEY is missing! Please set it in your .env file.")

    # We want a very precise, non-creative model for investigations.
    # Llama 3 is highly capable at 0 temperature.
    primary_llm = ChatGroq(
        model="llama3-70b-8192",
        temperature=temperature,
        api_key=SecretStr(config.GROQ_API_KEY),
        max_tokens=2048,
    )

    fallbacks: list[BaseChatModel] = []

    # Fallback 1: Groq Mixtral (in case Llama is overloaded or hits a specific model rate limit)
    fallbacks.append(
        ChatGroq(
            model="llama-3.1-8b-instant",
            temperature=temperature,
            api_key=SecretStr(config.GROQ_API_KEY),
            max_tokens=2048,
        )
    )

    # Fallback 2: Gemini (in case the entire Groq API is down/rate-limited)
    if getattr(config, "GEMINI_API_KEY", None):
        fallbacks.append(
            ChatGoogleGenerativeAI(
                model="gemini-1.5-flash",
                temperature=temperature,
                api_key=SecretStr(config.GEMINI_API_KEY),
                max_tokens=2048,
            )
        )

    # Fallback 3: OpenAI GPT-4o
    if getattr(config, "OPENAI_API_KEY", None):
        fallbacks.append(
            ChatOpenAI(
                model="gpt-4o",
                temperature=temperature,
                api_key=SecretStr(config.OPENAI_API_KEY),
                max_tokens=2048,
            )
        )

    # LangChain automatically catches errors (like RateLimitError) and tries the next model
    return primary_llm.with_fallbacks(fallbacks)


def get_structured_llm(output_schema):
    """
    Return an LLM bound to a Pydantic schema using with_structured_output.
    Applies fallbacks properly for structured output as well.
    """
    if not config.GROQ_API_KEY:
        raise ValueError("GROQ_API_KEY is missing! Please set it in your .env file.")

    primary_llm = ChatGroq(
        model="llama3-70b-8192",
        temperature=0.1,
        api_key=SecretStr(config.GROQ_API_KEY),
        max_tokens=2048,
    ).with_structured_output(output_schema)

    fallbacks: list[Any] = []

    # Fallback 1: Groq Mixtral
    fallbacks.append(
        ChatGroq(
            model="llama-3.1-8b-instant",
            temperature=0.1,
            api_key=SecretStr(config.GROQ_API_KEY),
            max_tokens=2048,
        ).with_structured_output(output_schema)
    )

    # Fallback 2: Google Gemini Pro
    if getattr(config, "GEMINI_API_KEY", None):
        fallbacks.append(
            ChatGoogleGenerativeAI(
                model="gemini-1.5-pro",
                temperature=0.1,
                api_key=SecretStr(config.GEMINI_API_KEY),
                max_tokens=2048,
            ).with_structured_output(output_schema)
        )

    # Fallback 3: OpenAI
    if getattr(config, "OPENAI_API_KEY", None):
        fallbacks.append(
            ChatOpenAI(
                model="gpt-4o",
                temperature=0.1,
                api_key=SecretStr(config.OPENAI_API_KEY),
                max_tokens=2048,
            ).with_structured_output(output_schema)
        )

    return primary_llm.with_fallbacks(fallbacks)
