"""
Configuration loader and validator for PII redaction tool.
"""

import yaml
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class PIIField:
    """Represents a single PII field with its value and replacement."""
    name: str
    value: str
    replacement: str
    min_partial_length: int = 3

    def __post_init__(self):
        if not self.value:
            raise ValueError(f"PII field '{self.name}' must have a non-empty value")
        if not self.replacement:
            raise ValueError(f"PII field '{self.name}' must have a non-empty replacement")


@dataclass
class Config:
    """Configuration for the PII redaction tool."""
    pii_fields: list[PIIField] = field(default_factory=list)
    default_min_partial_length: int = 3
    case_sensitive: bool = False

    @classmethod
    def from_yaml(cls, path: Path) -> "Config":
        """Load configuration from a YAML file."""
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")

        with open(path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)

        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Config":
        """Create configuration from a dictionary."""
        if not data:
            raise ValueError("Config file is empty")

        # Extract settings
        settings = data.get('settings', {})
        default_min_partial_length = settings.get('default_min_partial_length', 3)
        case_sensitive = settings.get('case_sensitive', False)

        # Extract PII fields
        pii_data = data.get('pii', {})
        if not pii_data:
            raise ValueError("Config must contain 'pii' section with at least one field")

        pii_fields = []
        for name, field_data in pii_data.items():
            if isinstance(field_data, dict):
                pii_fields.append(PIIField(
                    name=name,
                    value=str(field_data.get('value', '')),
                    replacement=str(field_data.get('replacement', '')),
                    min_partial_length=field_data.get('min_partial_length', default_min_partial_length)
                ))
            else:
                raise ValueError(f"PII field '{name}' must be a dictionary with 'value' and 'replacement' keys")

        return cls(
            pii_fields=pii_fields,
            default_min_partial_length=default_min_partial_length,
            case_sensitive=case_sensitive
        )

    def validate(self) -> list[str]:
        """Validate configuration and return list of warnings."""
        warnings = []

        # Check for duplicate values
        seen_values = {}
        for pii_field in self.pii_fields:
            lower_value = pii_field.value.lower()
            if lower_value in seen_values:
                warnings.append(
                    f"Duplicate PII value '{pii_field.value}' in fields "
                    f"'{seen_values[lower_value]}' and '{pii_field.name}'"
                )
            seen_values[lower_value] = pii_field.name

        # Check for very short values
        for pii_field in self.pii_fields:
            if len(pii_field.value) < 3:
                warnings.append(
                    f"PII field '{pii_field.name}' has very short value '{pii_field.value}' "
                    f"which may cause many false positives"
                )

        return warnings
