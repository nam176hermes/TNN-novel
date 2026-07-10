from __future__ import annotations

# Chapter endpoints live in books.py because routes are nested under /api/books/{book_id}/chapters.
from app.mobile_api.routers.books import router

__all__ = ["router"]
