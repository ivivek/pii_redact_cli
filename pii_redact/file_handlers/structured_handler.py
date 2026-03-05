"""
Handlers for structured files (JSON, YAML).
"""

import json
import re
from pathlib import Path
from typing import Any

import yaml


class StructuredHandler:
    """Base class for structured file handlers."""

    @staticmethod
    def redact_structure(data: Any, redact_func) -> Any:
        """
        Recursively traverse and redact PII in a data structure.
        redact_func: function that takes a string and returns redacted string.
        """
        if isinstance(data, dict):
            return {
                StructuredHandler.redact_structure(k, redact_func):
                StructuredHandler.redact_structure(v, redact_func)
                for k, v in data.items()
            }
        elif isinstance(data, list):
            return [StructuredHandler.redact_structure(item, redact_func) for item in data]
        elif isinstance(data, str):
            return redact_func(data)
        else:
            # Numbers, booleans, None - return as-is
            return data


class JSONHandler:
    """Handles reading and writing JSON files."""

    EXTENSIONS = {'.json'}

    @staticmethod
    def can_handle(path: Path) -> bool:
        """Check if this handler can process the given file."""
        return path.suffix.lower() in JSONHandler.EXTENSIONS

    @staticmethod
    def read(path: Path) -> tuple[str, Any]:
        """
        Read JSON file and return both raw text and parsed structure.
        Returns: (raw_text, parsed_data)
        """
        with open(path, 'r', encoding='utf-8') as f:
            raw_text = f.read()

        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in {path}: {e}")

        return raw_text, data

    @staticmethod
    def write(path: Path, data: Any, indent: int = 2) -> None:
        """Write data to JSON file."""
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=indent, ensure_ascii=False)

    @staticmethod
    def get_output_path(input_path: Path, suffix: str = "_redacted") -> Path:
        """Generate output path for redacted file."""
        stem = input_path.stem
        ext = input_path.suffix
        return input_path.parent / f"{stem}{suffix}{ext}"


class YAMLHandler:
    """Handles reading and writing YAML files."""

    EXTENSIONS = {'.yaml', '.yml'}

    @staticmethod
    def can_handle(path: Path) -> bool:
        """Check if this handler can process the given file."""
        return path.suffix.lower() in YAMLHandler.EXTENSIONS

    @staticmethod
    def read(path: Path) -> tuple[str, Any]:
        """
        Read YAML file and return both raw text and parsed structure.
        Returns: (raw_text, parsed_data)
        """
        with open(path, 'r', encoding='utf-8') as f:
            raw_text = f.read()

        try:
            data = yaml.safe_load(raw_text)
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML in {path}: {e}")

        return raw_text, data

    @staticmethod
    def write(path: Path, data: Any, default_flow_style: bool = False) -> None:
        """Write data to YAML file."""
        with open(path, 'w', encoding='utf-8') as f:
            yaml.dump(data, f, default_flow_style=default_flow_style, allow_unicode=True, sort_keys=False)

    @staticmethod
    def get_output_path(input_path: Path, suffix: str = "_redacted") -> Path:
        """Generate output path for redacted file."""
        stem = input_path.stem
        ext = input_path.suffix
        return input_path.parent / f"{stem}{suffix}{ext}"
