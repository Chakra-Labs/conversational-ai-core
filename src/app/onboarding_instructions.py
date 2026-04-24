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


def _language_key(language: str) -> str:
    return (language or 'english').strip().lower()


def get_onboarding_instruction_bundle(language: str) -> Dict[str, Any]:
    root_data = _load_onboarding_instructions()
    languages_data = root_data.get("languages", {})
    key = _language_key(language)
    return languages_data.get(key) or 'english'


def get_onboarding_assistant_instructions(language: str) -> str:
    bundle = get_onboarding_instruction_bundle(language)
    return bundle.get("prompts", {}).get("assistant", "")


def get_onboarding_greeting_instructions(language: str) -> str:
    bundle = get_onboarding_instruction_bundle(language)
    return bundle.get("prompts", {}).get("greeting", "")
