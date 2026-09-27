"""
Language control and safety module for RIT NEXUS.
Enforces strict English-only generation, CJK detection, and single-retry safety fallback.
"""
from typing import Optional
import re
import os
import requests

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")

ENGLISH_SYSTEM_INSTRUCTION = (
    "You are RIT NEXUS, an academic assistant for MSRIT students.\n"
    "Respond in English unless the user explicitly asks for another language.\n"
    "Never switch languages automatically.\n"
    "Do not output Chinese, Japanese, Korean, Hindi, Kannada, or any other language unless the user explicitly requests that language.\n"
    "If the user writes in English, respond entirely in English.\n"
    "Keep technical terminology in English.\n"
    "Do not translate an English academic question into another language."
)

# CJK Ideographs, Hiragana, Katakana, Hangul, Bopomofo
CJK_REGEX = re.compile(r'[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\uac00-\ud7af\u3100-\u312f]')


def contains_cjk(text: str, threshold: int = 2) -> bool:
    """Detect if text contains unexpected CJK characters above threshold."""
    if not text:
        return False
    matches = CJK_REGEX.findall(text)
    return len(matches) >= threshold


def inject_english_instruction(prompt: str) -> str:
    """Prepend standard English system instruction if not already present."""
    if "Respond in English unless the user explicitly asks" in prompt:
        return prompt
    return f"{ENGLISH_SYSTEM_INSTRUCTION}\n\n{prompt}"


def safe_qwen_generate(
    prompt: str,
    deterministic_fallback: str = "",
    timeout: int = 180,
    model: Optional[str] = None,
    options: Optional[dict] = None
) -> str:
    """
    Execute local Ollama generation with strict English enforcement and CJK safety check.
    If CJK is detected, executes exactly one retry with an emergency English-only directive.
    If retry also produces CJK or fails, uses deterministic fallback.
    """
    target_model = model or OLLAMA_MODEL
    full_prompt = inject_english_instruction(prompt)

    payload = {"model": target_model, "prompt": full_prompt, "stream": False}
    if options:
        payload["options"] = options

    try:
        resp = requests.post(
            OLLAMA_URL,
            json=payload,
            timeout=timeout
        )
        if resp.status_code != 200:
            return deterministic_fallback

        ans = resp.json().get("response", "").strip()
        if not ans:
            return deterministic_fallback

        # Check for CJK corruption
        if not contains_cjk(ans):
            return ans

        # CJK detected: Attempt exactly 1 retry with strict override
        print("[Language Safety] Unexpected CJK characters detected in Qwen output. Retrying once with strict English instruction...")
        retry_prompt = (
            f"{ENGLISH_SYSTEM_INSTRUCTION}\n\n"
            "CRITICAL: The previous response contained non-English or Chinese characters. "
            "You MUST generate this response 100% entirely in clear, natural English. "
            "Do NOT include any Chinese, Japanese, Korean, or non-English characters whatsoever.\n\n"
            f"{prompt}"
        )
        retry_payload = {"model": target_model, "prompt": retry_prompt, "stream": False}
        if options:
            retry_payload["options"] = options
        retry_resp = requests.post(
            OLLAMA_URL,
            json=retry_payload,
            timeout=timeout
        )
        if retry_resp.status_code == 200:
            retry_ans = retry_resp.json().get("response", "").strip()
            if retry_ans and not contains_cjk(retry_ans):
                return retry_ans

        # If retry still contains CJK or fails, use deterministic fallback
        print("[Language Safety] CJK persisted after retry. Falling back to English response.")
        return deterministic_fallback or "An explanation is currently being processed. Please ask a follow-up or check the reference materials."

    except Exception as e:
        print(f"[Language Safety] Ollama call failed: {e}")
        return deterministic_fallback
