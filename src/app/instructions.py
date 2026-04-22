"""Utility helpers for loading and accessing assistant instructions."""
from functools import lru_cache
import json
import os
from typing import Dict, Any

BASE_DIR = os.path.dirname(__file__)
INSTRUCTION_FILE = os.path.join(os.path.dirname(BASE_DIR), "app/instructions.json")
DEFAULT_LANGUAGE = "english"


@lru_cache(maxsize=1)
def _load_instructions() -> Dict[str, Any]:
    with open(INSTRUCTION_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _language_key(language: str) -> str:
    return (language or DEFAULT_LANGUAGE).strip().lower()


def get_instruction_bundle(language: str) -> Dict[str, Any]:
    root_data = _load_instructions()
    # Support v2 schema with nested "languages" key
    languages_data = root_data.get("languages", root_data)
    
    key = _language_key(language)
    return languages_data.get(key) or languages_data.get(DEFAULT_LANGUAGE, {})


def get_assistant_instructions(language: str) -> str:
    bundle = get_instruction_bundle(language)
    # Support both old flat structure and new nested structure for backward compatibility if needed
    if "prompts" in bundle:
        return bundle.get("prompts", {}).get("assistant", "")
    return bundle.get("router", "")


def get_entrypoint_instructions(language: str) -> str:
    bundle = get_instruction_bundle(language)
    if "prompts" in bundle:
        return bundle.get("prompts", {}).get("greeting", "")
    return bundle.get("greeting", "")


def get_turn_guidance_config(language: str) -> Dict[str, Any]:
    bundle = get_instruction_bundle(language)
    return bundle.get("turn_guidance", {})
