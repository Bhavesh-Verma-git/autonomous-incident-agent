"""
agents/security.py — Input validation and guardrails for the AIRP pipeline.

Two layers of protection:
  1. SecurityGuard  — blocks prompt injections and sanitizes input
  2. relevance_check — blocks off-topic descriptions (searches, questions,
                       commands) before they ever reach the LLM
"""

import re


# ── Layer 1: Prompt Injection Guard ──────────────────────────────────────────

class SecurityGuard:
    """
    Centralized security module to protect against prompt injections
    and sanitize user input before it reaches the LLM.
    """

    # Classic injection patterns
    MALICIOUS_PATTERNS = [
        r"ignore\s+all\s+(previous\s+)?instructions",
        r"system\s+prompt\s*:",
        r"you\s+are\s+now\s+a",
        r"forget\s+(all\s+)?previous\s+rules",
        r"jailbreak",
        r"override\s+instructions",
        r"act\s+as\s+(if\s+you\s+are|an?\s+)",   # "act as a DAN"
        r"disregard\s+(your\s+)?training",
        r"new\s+instructions\s*:",
        r"###\s*(instruction|system|prompt)",       # markdown-style injection
        r"\[system\]",                              # bracketed injection
        r"(respond|reply)\s+only\s+in",
    ]

    @classmethod
    def sanitize(cls, text: str) -> str:
        """
        Sanitize untrusted input by escaping < > so the attacker
        cannot escape the <untrusted_input> tags in the LLM prompt.
        """
        if not text:
            return ""
        return text.replace("<", "&lt;").replace(">", "&gt;")

    @classmethod
    def detect_injection(cls, text: str) -> bool:
        """Return True if a known injection pattern is found."""
        if not text:
            return False
        text_lower = text.lower()
        for pattern in cls.MALICIOUS_PATTERNS:
            if re.search(pattern, text_lower):
                return True
        return False

    @classmethod
    def check_and_sanitize(cls, text: str, max_length: int = 2000) -> str:
        """
        Main validation pipeline for untrusted alert description input.
        Raises ValueError on injection or excessive length.
        Returns sanitized string otherwise.
        """
        if not text:
            return ""

        if len(text) > max_length:
            raise ValueError(
                f"Description is too long ({len(text)} chars). "
                f"Maximum allowed is {max_length} characters."
            )

        if cls.detect_injection(text):
            raise ValueError(
                "Security violation: Description contains instructions that "
                "look like a prompt injection attempt. Please describe the "
                "actual incident symptoms instead."
            )

        return cls.sanitize(text)


# ── Layer 2: Relevance / Topic Guard ─────────────────────────────────────────

class RelevanceGuard:
    """
    Rejects descriptions that are clearly NOT incident reports.

    Examples of bad inputs this blocks:
      - "search the problem in production"
      - "what is wrong with my service?"
      - "find the error"
      - "google database connection"
      - "help me debug this"
      - "tell me why the service is slow"
      - A single word like "broken"

    A valid incident description MUST:
      - Be at least 20 characters long
      - Describe a symptom, error, metric, or event (not a command/question)
    """

    # Patterns that indicate a command or search rather than a symptom
    COMMAND_PATTERNS = [
        r"^\s*(search|find|google|look\s+up|check|debug|investigate)\s",
        r"^\s*(what|why|how|when|where|who)\s+(is|are|was|were|did|do|does|can|should)\b",
        r"^\s*(help|please|tell\s+me|explain|describe|show\s+me)\b",
        r"^\s*(fix|resolve|solve|repair)\s+the\b",
        r"\?\s*$",          # ends with a question mark → it's a question
        r"^[a-zA-Z\s]{1,15}$",  # too short / single-word description
    ]

    # At least one of these technical keywords should appear in a real incident
    INCIDENT_KEYWORDS = [
        "error", "exception", "fail", "crash", "timeout", "latency", "slow",
        "spike", "cpu", "memory", "disk", "down", "unavailable", "5xx", "4xx",
        "500", "503", "alert", "incident", "outage", "degraded", "high",
        "connection", "pool", "oom", "killed", "restart", "pod", "node",
        "deploy", "rollback", "database", "db", "queue", "lag", "delay",
        "traffic", "request", "response", "throughput", "drop",
        "p99", "p95", "saturation", "throttl", "circuit", "breaker",
    ]

    @classmethod
    def is_command_or_question(cls, text: str) -> bool:
        """Return True if the description reads as a command/question, not a symptom."""
        text_stripped = text.strip()
        text_lower = text_stripped.lower()
        for pattern in cls.COMMAND_PATTERNS:
            if re.search(pattern, text_lower):
                return True
        return False

    @classmethod
    def has_incident_signal(cls, text: str) -> bool:
        """Return True if the text contains at least one technical incident keyword."""
        text_lower = text.lower()
        return any(kw in text_lower for kw in cls.INCIDENT_KEYWORDS)

    @classmethod
    def validate(cls, description: str) -> None:
        """
        Validate that the description looks like an actual incident alert.
        Raises ValueError with a user-friendly message if the check fails.
        """
        if not description or len(description.strip()) < 20:
            raise ValueError(
                "Description is too short. Please provide at least 20 characters "
                "describing the alert symptoms (e.g., 'High latency on /checkout, "
                "p99 spiked to 5s, DB CPU at 98%')."
            )

        if cls.is_command_or_question(description):
            raise ValueError(
                "The description looks like a search query or question rather than "
                "an incident alert. Please describe the actual symptoms you are "
                "observing (e.g., error messages, metric spikes, service outages)."
            )

        if not cls.has_incident_signal(description):
            raise ValueError(
                "The description does not appear to contain incident-related "
                "information. Please include technical details such as error "
                "messages, latency figures, CPU/memory readings, or service names."
            )
