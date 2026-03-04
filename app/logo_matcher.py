from __future__ import annotations

import re
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import urlparse

import requests


_STOP_WORDS = {
    "inc",
    "llc",
    "ltd",
    "limited",
    "pty",
    "corp",
    "corporation",
    "company",
    "co",
    "group",
    "holdings",
    "international",
    "solutions",
    "technologies",
    "technology",
    "the",
    "and",
}

_SOURCE_WEIGHTS = {
    "clearbit": 0.09,
    "clearbit-domain": 0.07,
    "duckduckgo-favicon": 0.03,
    "google-favicon": 0.02,
}

_FILETYPE_WEIGHTS = {
    "svg": 0.08,
    "png": 0.05,
    "webp": 0.05,
    "jpg": 0.04,
    "jpeg": 0.04,
    "ico": 0.01,
    "unknown": 0.0,
}


def _normalize_text(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
    tokens = [token for token in cleaned.split() if token and token not in _STOP_WORDS]
    return " ".join(tokens)


def _token_set(value: str) -> set[str]:
    return set(_normalize_text(value).split())


def _domain_label(domain: str) -> str:
    value = domain.strip().lower()
    if not value:
        return ""
    return value.split(".")[0]


def _filename_from_url(url: str) -> str:
    path = urlparse(url).path
    if not path:
        return ""
    return Path(path).name


def _filetype_from_filename(filename: str, source: str) -> str:
    filetype = Path(filename).suffix.lower().replace(".", "") if filename else ""
    if filetype:
        return filetype
    if source.startswith("clearbit"):
        return "png"
    return "unknown"


def _similarity_score(target_norm: str, target_tokens: set[str], candidate_norm: str, candidate_tokens: set[str]) -> float:
    if not target_norm or not candidate_norm:
        return 0.0

    if target_norm == candidate_norm:
        return 1.0

    ratio = SequenceMatcher(None, target_norm, candidate_norm).ratio()
    compact_ratio = SequenceMatcher(None, target_norm.replace(" ", ""), candidate_norm.replace(" ", "")).ratio()

    overlap = 0.0
    if target_tokens and candidate_tokens:
        overlap = len(target_tokens & candidate_tokens) / max(len(target_tokens), len(candidate_tokens), 1)

    containment_bonus = 0.0
    if len(target_norm) >= 4 and (target_norm in candidate_norm or candidate_norm in target_norm):
        containment_bonus = 0.08

    return min(1.0, max(ratio, compact_ratio * 0.98, overlap * 1.02) + containment_bonus)


class LogoMatcher:
    CLEARBIT_ENDPOINT = "https://autocomplete.clearbit.com/v1/companies/suggest"

    def __init__(self, allow_external_lookup: bool = True, request_timeout: int = 6) -> None:
        self.allow_external_lookup = allow_external_lookup
        self.request_timeout = request_timeout
        self._cache: dict[str, dict | None] = {}
        self._session = requests.Session()

    def _score_candidate(
        self,
        company_norm: str,
        company_tokens: set[str],
        candidate_name: str,
        domain: str,
        filename: str,
        source: str,
    ) -> float:
        candidate_norm = _normalize_text(candidate_name)
        candidate_tokens = _token_set(candidate_name)

        name_score = _similarity_score(company_norm, company_tokens, candidate_norm, candidate_tokens)

        domain_norm = _normalize_text(_domain_label(domain))
        domain_tokens = _token_set(_domain_label(domain))
        domain_score = _similarity_score(company_norm, company_tokens, domain_norm, domain_tokens)

        filename_base = Path(filename).stem if filename else ""
        file_norm = _normalize_text(filename_base)
        file_tokens = _token_set(filename_base)
        file_score = _similarity_score(company_norm, company_tokens, file_norm, file_tokens)

        filetype = _filetype_from_filename(filename, source)
        source_weight = _SOURCE_WEIGHTS.get(source, 0.0)
        filetype_weight = _FILETYPE_WEIGHTS.get(filetype, 0.0)

        score = (
            0.58 * name_score
            + 0.2 * domain_score
            + 0.12 * file_score
            + source_weight
            + filetype_weight
        )
        return min(1.0, score)

    def _search_external_candidates(self, company_name: str, company_norm: str, company_tokens: set[str]) -> list[dict]:
        if not self.allow_external_lookup:
            return []

        try:
            response = self._session.get(
                self.CLEARBIT_ENDPOINT,
                params={"query": company_name},
                timeout=self.request_timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception:
            return []

        if not isinstance(payload, list):
            return []

        candidates: list[dict] = []
        seen_urls: set[str] = set()

        for row in payload[:10]:
            if not isinstance(row, dict):
                continue

            name = str(row.get("name", "")).strip() or company_name
            domain = str(row.get("domain", "")).strip().lower()
            logo_url = str(row.get("logo", "")).strip()
            if not logo_url and domain:
                logo_url = f"https://logo.clearbit.com/{domain}"

            if logo_url and logo_url not in seen_urls:
                seen_urls.add(logo_url)
                filename = _filename_from_url(logo_url) or domain or name
                score = self._score_candidate(
                    company_norm=company_norm,
                    company_tokens=company_tokens,
                    candidate_name=name,
                    domain=domain,
                    filename=filename,
                    source="clearbit",
                )
                candidates.append(
                    {
                        "name": name,
                        "shortname": _domain_label(domain) or _normalize_text(name).replace(" ", "-"),
                        "url": logo_url,
                        "score": round(score, 3),
                        "source": "clearbit",
                        "filetype": _filetype_from_filename(filename, "clearbit"),
                        "filename": filename,
                        "domain": domain,
                    }
                )

            if domain:
                clearbit_domain_logo = f"https://logo.clearbit.com/{domain}"
                if clearbit_domain_logo not in seen_urls:
                    seen_urls.add(clearbit_domain_logo)
                    filename = _filename_from_url(clearbit_domain_logo) or domain
                    score = self._score_candidate(
                        company_norm=company_norm,
                        company_tokens=company_tokens,
                        candidate_name=name,
                        domain=domain,
                        filename=filename,
                        source="clearbit-domain",
                    )
                    candidates.append(
                        {
                            "name": name,
                            "shortname": _domain_label(domain),
                            "url": clearbit_domain_logo,
                            "score": round(score, 3),
                            "source": "clearbit-domain",
                            "filetype": _filetype_from_filename(filename, "clearbit-domain"),
                            "filename": filename,
                            "domain": domain,
                        }
                    )

                duckduckgo_icon = f"https://icons.duckduckgo.com/ip3/{domain}.ico"
                if duckduckgo_icon not in seen_urls:
                    seen_urls.add(duckduckgo_icon)
                    filename = _filename_from_url(duckduckgo_icon) or f"{domain}.ico"
                    score = self._score_candidate(
                        company_norm=company_norm,
                        company_tokens=company_tokens,
                        candidate_name=name,
                        domain=domain,
                        filename=filename,
                        source="duckduckgo-favicon",
                    )
                    candidates.append(
                        {
                            "name": name,
                            "shortname": _domain_label(domain),
                            "url": duckduckgo_icon,
                            "score": round(score, 3),
                            "source": "duckduckgo-favicon",
                            "filetype": _filetype_from_filename(filename, "duckduckgo-favicon"),
                            "filename": filename,
                            "domain": domain,
                        }
                    )

                google_icon = f"https://www.google.com/s2/favicons?domain={domain}&sz=64"
                if google_icon not in seen_urls:
                    seen_urls.add(google_icon)
                    filename = _filename_from_url(google_icon) or f"{domain}.png"
                    score = self._score_candidate(
                        company_norm=company_norm,
                        company_tokens=company_tokens,
                        candidate_name=name,
                        domain=domain,
                        filename=filename,
                        source="google-favicon",
                    )
                    candidates.append(
                        {
                            "name": name,
                            "shortname": _domain_label(domain),
                            "url": google_icon,
                            "score": round(score, 3),
                            "source": "google-favicon",
                            "filetype": _filetype_from_filename(filename, "google-favicon"),
                            "filename": filename,
                            "domain": domain,
                        }
                    )

        return candidates

    def match_company(self, company_name: str) -> dict | None:
        normalized = _normalize_text(company_name)
        if not normalized:
            return None

        if normalized in self._cache:
            return self._cache[normalized]

        tokens = set(normalized.split())
        external_candidates = self._search_external_candidates(
            company_name=company_name,
            company_norm=normalized,
            company_tokens=tokens,
        )

        best_result: dict | None = None
        best_score = 0.0
        for candidate in external_candidates:
            candidate_score = float(candidate.get("score", 0.0))
            if candidate_score > best_score:
                best_score = candidate_score
                best_result = candidate

        if not best_result or best_score < 0.58:
            self._cache[normalized] = None
            return None

        self._cache[normalized] = best_result
        return best_result
