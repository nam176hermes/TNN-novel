from __future__ import annotations

import re
from typing import List

def split_text_for_tts(text: str, max_chars: int = 2000) -> List[str]:
    """Split Vietnamese text into chunks suitable for TTS, respecting sentence boundaries."""
    # Normalize whitespace
    text = " ".join(text.split())
    # Split by sentence endings (. ! ?) followed by space or end of string
    sentences = re.split(r'(?<=[.!?])\s+', text)
    chunks: List[str] = []
    current = ""
    for sent in sentences:
        # If adding this sentence exceeds max_chars and we have current, store current
        if len(current) + len(sent) + 1 > max_chars and current:
            chunks.append(current.strip())
            current = sent
        else:
            if current:
                current += " " + sent
            else:
                current = sent
    if current:
        chunks.append(current.strip())
    return chunks
