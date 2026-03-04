from __future__ import annotations

import json
import re
from typing import Any

import requests


class GroqKeywordRefiner:
    API_URL = "https://api.groq.com/openai/v1/chat/completions"

    def __init__(
        self,
        api_key: str,
        model: str = "llama-3.3-70b-versatile",
        timeout_seconds: int = 20,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self._cache: dict[tuple[str, int], list[str]] = {}

    @staticmethod
    def _dedupe(values: list[str], original: str, limit: int) -> list[str]:
        deduped: list[str] = []
        seen = {original.strip().lower()}
        for value in values:
            keyword = value.strip()
            normalized = keyword.lower()
            if not keyword or normalized in seen:
                continue
            seen.add(normalized)
            deduped.append(keyword)
            if len(deduped) >= limit:
                break
        return deduped

    @staticmethod
    def _extract_json_keywords(content: str) -> list[str]:
        try:
            payload = json.loads(content)
            if isinstance(payload, dict) and isinstance(payload.get("keywords"), list):
                return [str(item) for item in payload["keywords"]]
        except json.JSONDecodeError:
            pass

        json_block = re.search(r"\{.*\}", content, re.DOTALL)
        if json_block:
            try:
                payload = json.loads(json_block.group(0))
                if isinstance(payload, dict) and isinstance(payload.get("keywords"), list):
                    return [str(item) for item in payload["keywords"]]
            except json.JSONDecodeError:
                pass

        return [chunk.strip() for chunk in re.split(r"[,\n]", content) if chunk.strip()]

    def refine(self, base_keyword: str, expansion_limit: int = 3) -> list[str]:
        cache_key = (base_keyword.lower().strip(), expansion_limit)
        if cache_key in self._cache:
            return self._cache[cache_key]

        if not self.api_key or expansion_limit <= 0:
            return []

        payload: dict[str, Any] = {
            "model": self.model,
            "temperature": 0.2,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You generate concise LinkedIn job search expansions. "
                        "Return strict JSON only, with this shape: {\"keywords\": [\"...\"]}."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Expand this search phrase into up to {expansion_limit} distinct high-signal "
                        f"LinkedIn keyword phrases: {base_keyword}"
                    ),
                },
            ],
            "response_format": {"type": "json_object"},
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            response = requests.post(
                self.API_URL,
                headers=headers,
                json=payload,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            response_payload = response.json()
            content = str(response_payload["choices"][0]["message"]["content"])
            raw_keywords = self._extract_json_keywords(content)
        except Exception:
            return []

        expansions = self._dedupe(raw_keywords, original=base_keyword, limit=expansion_limit)
        self._cache[cache_key] = expansions
        return expansions
