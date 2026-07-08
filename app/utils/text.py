"""Text/path utility helpers."""


def safe_book_name(book: str) -> str:
    """Return filesystem-safe book name.

    Keeps alphanumeric chars plus '.', '_' and '-'. Replaces everything else
    with underscore. Works for Vietnamese/Chinese alphanumeric Unicode too.
    """
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in book)
