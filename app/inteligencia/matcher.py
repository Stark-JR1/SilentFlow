from __future__ import annotations

import re
import unicodedata
from collections import Counter

from app.intelligence.scoring import calculate_rule_score


STOPWORDS = {
    "a", "as", "ao", "aos", "com", "da", "das", "de", "do", "dos", "e", "em", "na", "nas", "no", "nos",
    "o", "os", "para", "por", "pra", "pro", "um", "uma", "umas", "uns",
    "eireli", "instituicao", "ltda", "me", "pag", "pagamento", "pix", "sa", "s a", "s.a", "ltda",
    "transferencia", "transacao", "debito", "credito", "valor", "total", "parcial",
}


def normalize_description(text: str) -> str:
    if not text:
        return ""
    
    # Convert to lowercase and normalize unicode
    value = unicodedata.normalize("NFKD", text.strip().lower())
    value = value.encode("ascii", "ignore").decode("utf-8")
    
    # Remove special characters but keep numbers
    value = re.sub(r"[^a-z0-9\s]", " ", value)
    
    # Remove extra whitespace
    value = re.sub(r"\s+", " ", value).strip()
    
    # Remove common transaction prefixes/suffixes
    value = re.sub(r"\b\d{2}/\d{2}\b", "", value)  # dates like 01/01
    value = re.sub(r"\b\d+\.\d{2}\b", "", value)   # amounts like 123.45
    
    return value.strip()


def tokenize_description(text: str) -> list[str]:
    normalized = normalize_description(text)
    tokens = normalized.split()
    
    # Filter tokens
    filtered = []
    for token in tokens:
        if len(token) > 1 and token not in STOPWORDS:
            # Remove numbers that are likely transaction IDs
            if not re.match(r"^\d+$", token) or len(token) <= 3:
                filtered.append(token)
    
    return filtered


def token_similarity(a: str, b: str) -> float:
    tokens_a = set(tokenize_description(a))
    tokens_b = set(tokenize_description(b))

    if not tokens_a or not tokens_b:
        return 0.0

    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b

    # Jaccard similarity
    jaccard = len(intersection) / len(union) if union else 0.0

    # Bonus for exact matches
    if a.strip() == b.strip():
        jaccard = min(jaccard + 0.3, 1.0)

    # Bonus for partial substring matches
    for token_a in tokens_a:
        for token_b in tokens_b:
            if token_a in token_b or token_b in token_a:
                jaccard = min(jaccard + 0.1, 1.0)
                break

    return round(jaccard, 3)


def build_cluster_key(text: str) -> str:
    tokens = tokenize_description(text)
    if not tokens:
        return "unknown"

    counts = Counter(tokens)
    most_common = counts.most_common(2)
    if len(most_common) == 1:
        return most_common[0][0]

    return "_".join(sorted([most_common[0][0], most_common[1][0]]))


def rank_rules(input_description: str, rules: list[dict], min_similarity: float = 0.5) -> list[dict]:
    ranked: list[dict] = []

    for rule in rules:
        rule_description = rule.get("normalized_description", "")
        similarity = token_similarity(input_description, rule_description)
        if similarity < min_similarity:
            continue

        score = calculate_rule_score(rule, similarity)
        ranked.append({
            "rule": rule,
            "score": score,
            "similarity": similarity,
        })

    ranked.sort(key=lambda item: (item["score"], item["similarity"]), reverse=True)
    return ranked[:3]
