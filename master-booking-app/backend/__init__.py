import html
import re


def escape_text(text: str | None) -> str | None:
    """Remove HTML tags and escape text for safe storage/display."""
    if not text:
        return text
    clean = re.sub(r'<[^>]*>', '', text)
    return html.escape(clean)