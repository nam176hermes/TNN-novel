#!/usr/bin/env python3
"""Debug the translate_chapter function step by step."""

import sys
sys.path.insert(0, '.')

from app.config import settings
from app.translation.ollama_client import (
    _split_into_chunks,
    _pre_substitute_glossary_terms,
    _build_translation_prompt,
    _extract_translation_block,
    _postprocess_translation
)
from app.database.db import get_connection, load_glossary, load_glossary_names, get_last_summary, get_book_by_title
from app.translation.pre_translator import (
    build_lexicon_from_glossary,
    pretranslate,
    get_protected_spans,
    apply_protection_markers,
)
from app.translation.template_rules import TemplateEngine
from pathlib import Path
import requests
import time

# First paragraph only
para1 = """第一章 永夜

那一天太阳落下再也没有升起……

永夜，天地漆黑，似不可测的深渊要吞噬一切。白昼早已沦为过往，成为传说。
"""

print(f"Input: {len(para1)} characters")

# Setup like translate_chapter does
db_path = Path('data/pipeline.db')
book_title = "永夜"
chapter_title = "第一章 永夜"
chapter_number = 1
model = settings.ollama_model
host = settings.ollama_host
temperature = settings.ollama_temperature
chunk_size = settings.ollama_chunk_size
timeout = getattr(settings, 'ollama_timeout', 180)

book = get_book_by_title(db_path, book_title)
book_id = book["id"] if book else 0
glossary = load_glossary(db_path, book_id)
name_map = load_glossary_names(db_path, book_id)
previous_summary = get_last_summary(db_path, book_id) or ""

print(f"Glossary: {len(glossary)} terms")
print(f"Name map: {len(name_map)} names")

chunks = _split_into_chunks(para1, max_chars=chunk_size)
print(f"Split into {len(chunks)} chunks")
for i, chunk in enumerate(chunks):
    print(f"  Chunk {i+1}: {len(chunk)} chars")

# Build lexicon and template engine
lexicon = build_lexicon_from_glossary(glossary, name_map)
template_engine = TemplateEngine()
print(f"Lexicon built: {len(lexicon._combined)} combined entries")

# Process each chunk
translated_chunks = []
for i, chunk in enumerate(chunks):
    print(f"\n--- Processing chunk {i+1}/{len(chunks)} ---")
    
    # Protected spans
    protected_spans = get_protected_spans(chunk, name_map)
    print(f"Protected spans: {protected_spans}")
    
    # Template rules
    templated_chunk = template_engine.apply(chunk, lexicon=lexicon, protected_spans=protected_spans)
    print(f"After template rules: {len(templated_chunk)} chars")
    if templated_chunk != chunk:
        print(f"  Changed: {repr(templated_chunk[:100])}...")
    
    # Pre-substitute glossary
    processed_chunk = _pre_substitute_glossary_terms(templated_chunk, glossary)
    print(f"After glossary pre-sub: {len(processed_chunk)} chars")
    if processed_chunk != templated_chunk:
        print(f"  Changed: {repr(processed_chunk[:100])}...")
    
    # Build prompt
    prev_suffix = chunks[i-2] if i >= 2 else ""
    prompt = _build_translation_prompt(
        chunk=processed_chunk,
        book_title=book_title,
        chapter_title=chapter_title,
        glossary=glossary,
        previous_summary=previous_summary,
        name_map=name_map,
        previous_chunk_suffix=prev_suffix,
        character_memory="",  # simplified
        previous_translated_tail="",  # simplified
    )
    print(f"Prompt length: {len(prompt)} chars")
    
    # Call Ollama
    print("Calling Ollama...")
    start = time.time()
    try:
        resp = requests.post(
            f"{host}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": temperature},
            },
            timeout=timeout,
        )
        elapsed = time.time() - start
        print(f"Ollama responded in {elapsed:.2f}s, status: {resp.status_code}")
        resp.raise_for_status()
        data = resp.json()
        raw_output = data.get("response", "").strip()
        print(f"Raw output: {len(raw_output)} chars")
        if len(raw_output) > 200:
            print(f"  Preview: {repr(raw_output[:200])}...")
        
        # Extract and postprocess
        translation_part = _extract_translation_block(raw_output)
        print(f"After extraction: {len(translation_part)} chars")
        translation_part = _postprocess_translation(translation_part)
        print(f"After postprocess: {len(translation_part)} chars")
        
        translated_chunks.append(translation_part)
        print(f"Chunk {i+1} done")
        
    except Exception as e:
        print(f"ERROR: {e}")
        break

print(f"\n=== Final translation ===")
final = "\n\n".join(translated_chunks)
print(final)