"""Utility helpers for loading the onboarding-agent instruction file."""
from functools import lru_cache
import json
import os
from typing import Dict, Any

BASE_DIR = os.path.dirname(__file__)
ONBOARDING_INSTRUCTION_FILE = os.path.join(BASE_DIR, "onboarding-instructions.json")


@lru_cache(maxsize=1)
def _load_onboarding_instructions() -> Dict[str, Any]:
    with open(ONBOARDING_INSTRUCTION_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def get_onboarding_assistant_instructions() -> str:
    data = _load_onboarding_instructions()
    return data.get("prompts", {}).get("assistant", "")


def get_onboarding_greeting_instructions() -> str:
    data = _load_onboarding_instructions()
    return data.get("prompts", {}).get("greeting", "")
