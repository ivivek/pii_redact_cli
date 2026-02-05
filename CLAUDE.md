# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

PII Redact is a Python CLI tool for redacting specific personally identifiable information from files. Unlike generic PII detection tools, this uses user-defined exact values and replacements from a YAML config file.

## Commands

```bash
# Install (creates venv and installs package)
python3 -m venv venv
./venv/bin/pip install -e .

# Add alias to ~/.bashrc for global access
alias pii_redact='/path/to/pii_redact/venv/bin/pii_redact'

# Run the tool (uses default config at ~/.config/pii_redact/config.yaml)
pii_redact <input_file>
pii_redact file.log --config custom.yaml    # Use specific config
pii_redact file.log --dry-run               # Preview without modifying
pii_redact file.log --no-interactive        # Skip partial match prompts
pii_redact "logs/**/*.log"                  # Glob patterns for multiple files
```

No test suite or linting configuration exists currently.

## Architecture

**Entry Point:** `pii_redact.py` - CLI argument parsing and main orchestration

**Core Flow:**
1. `config.py` loads YAML config into `Config` and `PIIField` dataclasses
2. `matchers.py` finds exact matches (word boundaries) and partial matches (embedded in larger tokens)
3. `redactor.py` orchestrates processing, routes to appropriate file handler
4. `file_handlers/` contains format-specific handlers (text, JSON, YAML)
5. `reporters.py` tracks statistics and outputs results

**Key Design Decisions:**
- PII fields sorted by length (longest first) to handle overlapping values correctly
- Case preservation in replacements (JOHN → MIKE, john → mike)
- Exact matches: standalone words with boundaries; Partial matches: embedded in larger tokens, require user confirmation
- Position-based replacement in reverse order to preserve character positions
- Multi-encoding support for text files (UTF-8 → Latin-1 → CP1252 fallback)

## Config Format

Default location: `~/.config/pii_redact/config.yaml`

```yaml
pii:
  field_name:
    value: "actual_pii"
    replacement: "fake_value"
    min_partial_length: 3  # optional

settings:
  default_min_partial_length: 3
  case_sensitive: false
```

## Output

- Redacted files: `{filename}_redacted{extension}`
- JSON reports: timestamps, file stats, match counts
