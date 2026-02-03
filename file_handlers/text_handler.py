"""
Handler for plain text files.
"""

from pathlib import Path


class TextHandler:
    """Handles reading and writing plain text files."""

    EXTENSIONS = {'.txt', '.log', '.text', '.md', '.csv', '.tsv'}

    @staticmethod
    def can_handle(path: Path) -> bool:
        """Check if this handler can process the given file."""
        # Handle common text extensions
        if path.suffix.lower() in TextHandler.EXTENSIONS:
            return True
        # Handle files with no extension (often logs)
        if not path.suffix:
            return True
        return False

    @staticmethod
    def read(path: Path) -> str:
        """Read text content from file."""
        # Try different encodings
        encodings = ['utf-8', 'utf-8-sig', 'latin-1', 'cp1252']

        for encoding in encodings:
            try:
                with open(path, 'r', encoding=encoding) as f:
                    return f.read()
            except UnicodeDecodeError:
                continue

        # Last resort: read with errors='replace'
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            return f.read()

    @staticmethod
    def write(path: Path, content: str) -> None:
        """Write text content to file."""
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)

    @staticmethod
    def get_output_path(input_path: Path, suffix: str = "_redacted") -> Path:
        """Generate output path for redacted file."""
        stem = input_path.stem
        ext = input_path.suffix
        return input_path.parent / f"{stem}{suffix}{ext}"
