import os
import re
import unicodedata
from typing import Dict, Optional, Tuple
import httpx


PROMPT_INJECTION_PATTERNS = [
    r"ignora\s+(todas\s+las\s+)?instrucciones",
    r"olvida\s+(todas\s+las\s+)?instrucciones",
    r"ignore\s+(all\s+)?(previous\s+)?instructions",
    r"forget\s+(all\s+)?(previous\s+)?instructions",
    r"system\s*prompt",
    r"actua\s+como\s+(un\s+)?hacker",
    r"modo\s+desarrollador",
    r"developer\s+mode",
    r"jailbreak",
    r"dan\s+mode",
    r"revela\s+tu\s+prompt",
    r"muestrame\s+las\s+claves",
    r"drop\s+table",
    r"union\s+select",
    r"bypass\s+security",
]

UNSAFE_CONTENT_PATTERNS = [
    (r"(lavado\s+de\s+dinero|evasion\s+fiscal|clonar\s+tarjeta|fraude\s+bancario)", "S2: Financial Crime & Fraud"),
    (r"(fabricar\s+explosivos|armas\s+de\s+fuego|ataque\s+violento|matar\s+a)", "S1: Violent Crimes"),
    (r"(suicidio|autolesion|cortarme\s+las\s+venas)", "S11: Self-Harm"),
    (r"(robar\s+identidad|phishing\s+bancario|vaciar\s+cuenta\s+ajena)", "S6: Cybercrime & Identity Theft"),
]


def _normalize_text(text: str) -> str:
    lowered = (text or "").lower().strip()
    decomposed = unicodedata.normalize("NFD", lowered)
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


def is_prompt_injection(user_text: str) -> Tuple[bool, Optional[str]]:
    """Layer 1 (Prompt Guard): Fast heuristic and structural jailbreak detection."""
    normalized = _normalize_text(user_text)
    for pattern in PROMPT_INJECTION_PATTERNS:
        if re.search(pattern, normalized):
            return True, f"Prompt Guard blocked potential instruction override ({pattern})"
    return False, None


def check_llama_guard(text: str, stage: str = "input") -> Tuple[bool, Optional[str]]:
    """
    Layer 2 (Llama Guard): Policy safety evaluation on user input or assistant output.
    Uses heuristic taxonomy checks first and optional remote Llama Guard model when configured.
    """
    normalized = _normalize_text(text)
    for pattern, category in UNSAFE_CONTENT_PATTERNS:
        if re.search(pattern, normalized):
            return False, f"Llama Guard ({stage}) flagged unsafe content under category [{category}]"

    enable_remote = os.getenv("ENABLE_REMOTE_LLAMA_GUARD", "false").lower() == "true"
    groq_api_key = os.getenv("GROQ_API_KEY", "").strip()
    if enable_remote and groq_api_key:
        guard_model = os.getenv("LLAMA_GUARD_MODEL", "meta-llama/llama-guard-4-12b")
        try:
            with httpx.Client(timeout=4.0) as client:
                resp = client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {groq_api_key}"},
                    json={
                        "model": guard_model,
                        "messages": [{"role": "user", "content": text}],
                        "temperature": 0.0,
                        "max_tokens": 32,
                    },
                )
                if resp.status_code == 200:
                    verdict = resp.json()["choices"][0]["message"]["content"].strip().lower()
                    if verdict.startswith("unsafe"):
                        return False, f"Llama Guard ({stage}) model verdict: {verdict}"
        except Exception:
            pass

    return True, None


def evaluate_input_safety(user_text: str) -> Dict[str, Optional[str]]:
    injected, inject_reason = is_prompt_injection(user_text)
    if injected:
        return {
            "safe": False,
            "layer": "Prompt Guard (Layer 1)",
            "reason": inject_reason,
            "safe_reply": (
                "Por motivos de seguridad bancaria y protección de datos, no puedo procesar "
                "instrucciones destinadas a modificar las reglas del sistema o vulnerar controles."
            ),
        }

    is_safe, guard_reason = check_llama_guard(user_text, stage="input")
    if not is_safe:
        return {
            "safe": False,
            "layer": "Llama Guard (Layer 2 - Input)",
            "reason": guard_reason,
            "safe_reply": (
                "Tu solicitud no puede ser procesada porque infringe nuestras políticas de "
                "seguridad financiera y prevención de ilícitos."
            ),
        }

    return {"safe": True, "layer": None, "reason": None, "safe_reply": None}


def evaluate_output_safety(assistant_reply: str) -> Dict[str, Optional[str]]:
    is_safe, guard_reason = check_llama_guard(assistant_reply, stage="output")
    if not is_safe:
        return {
            "safe": False,
            "layer": "Llama Guard (Layer 2 - Output)",
            "reason": guard_reason,
            "safe_reply": (
                "La respuesta generada fue bloqueada preventivamente por nuestros controles "
                "de cumplimiento financiero."
            ),
        }
    return {"safe": True, "layer": None, "reason": None, "safe_reply": None}
