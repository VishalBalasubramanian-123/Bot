"""Shared chunking: ~CHUNK_SIZE_TOKENS chunks with CHUNK_OVERLAP_TOKENS overlap.

Token counts are approximated from whitespace-separated words (1 token ≈ 0.75
words for English prose), which avoids loading a tokenizer just to split text.
"""
import hashlib

from assistant import config

WORDS_PER_TOKEN = 0.75


def chunk_words(text, size_words, overlap_words):
    """Split text into chunks of size_words words, each overlapping the previous by overlap_words."""
    words = text.split()
    if not words:
        return []

    step = size_words - overlap_words
    start = 0
    chunks = []
    while True:
        chunks.append(" ".join(words[start : start + size_words]))
        if start + size_words >= len(words):
            break
        start = start + step
    return chunks


def chunk_text(text, size_tokens=None, overlap_tokens=None):
    """Same as chunk_words, but sizes are in tokens and default to the .env settings."""
    if size_tokens is None:
        size_tokens = config.CHUNK_SIZE_TOKENS
    if overlap_tokens is None:
        overlap_tokens = config.CHUNK_OVERLAP_TOKENS

    size_words = max(1, int(size_tokens * WORDS_PER_TOKEN))
    overlap_words = int(overlap_tokens * WORDS_PER_TOKEN)
    return chunk_words(text, size_words, overlap_words)


def content_hash(text):
    hashed = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return hashed


if __name__ == "__main__":
    s = "what is the name of the boy in the story"
    assert chunk_words(s, 3, 2) == [
        "what is the", "is the name", "the name of", "name of the",
        "of the boy", "the boy in", "boy in the", "in the story",
    ]
    assert chunk_words(s, 4, 1) == ["what is the name", "name of the boy", "boy in the story"]
    assert chunk_words("hello world", 3, 2) == ["hello world"]
    assert chunk_words("", 3, 2) == []
    assert chunk_words("   ", 3, 2) == []
    assert chunk_text(s) == [s]  # 400 tokens ≈ 300 words, so one chunk
    assert len(content_hash("hi")) == 64
    assert content_hash("hi") == content_hash("hi") != content_hash("hi!")
    print("all chunking checks passed")
