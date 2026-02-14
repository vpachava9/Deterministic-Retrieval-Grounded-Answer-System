# query_quality_gate.py

import re


def is_query_quality_ok(query_text: str, config: dict) -> bool:
    """
    Lightweight lexical quality gate.

    Purpose:
    - Block keyboard smash
    - Block junk / random strings
    - Block extremely short or meaningless queries

    This is NOT semantic.
    This is a safety + abuse prevention gate.
    """

    q = query_text.strip()

    # Empty or whitespace
    if not q:
        return False

    # Minimum character length
    if len(q) < config["thresholds"]["min_query_chars"]:
        return False

    # Tokenize on alphanumeric words
    tokens = re.findall(r"[A-Za-z0-9]+", q)

    # Minimum token count
    if len(tokens) < config["thresholds"]["min_query_tokens"]:
        return False

    # Alphabetic token ratio
    alpha_tokens = [t for t in tokens if re.search(r"[A-Za-z]", t)]
    alpha_ratio = len(alpha_tokens) / max(len(tokens), 1)

    if alpha_ratio < config["thresholds"]["min_alpha_token_ratio"]:
        return False

    # Reject long repeated characters (aaaaaa, 111111, etc)
    if re.search(r"(.)\1{5,}", q):
        return False

    return True
