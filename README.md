# PII Redact

A command-line tool for redacting Personally Identifiable Information (PII) from files before sharing with third parties, online tools, or support teams.

Unlike generic PII detection tools that use pattern matching or NLP to find *any* PII, this tool lets you define *your specific* PII values and their replacements. This gives you precise control over what gets redacted and ensures consistent replacements across all your files.

## Features

- **Exact match replacement** - Replace your specific PII values (name, email, phone, etc.) with fake values
- **Partial match detection** - Detects when your PII appears as part of larger strings (e.g., "JohnDoe123") and prompts for confirmation
- **Case preservation** - Maintains original casing ("JOHN" → "MIKE", "john" → "mike")
- **Multiple file formats** - Supports plain text (.txt, .log), JSON, and YAML files
- **Glob patterns** - Process multiple files at once (`logs/**/*.log`)
- **Interactive mode** - Review partial matches with surrounding context before deciding
- **Dry-run mode** - Preview changes without modifying files
- **Detailed reports** - JSON report of all replacements made

## Installation

```bash
# Clone the repository
git clone https://github.com/ivivek/pii_redact_cli.git
cd pii_redact_cli

# Create virtual environment and install
python3 -m venv venv
./venv/bin/pip install -e .

# Add alias to run from anywhere (add to ~/.bashrc or ~/.zshrc)
echo "alias pii_redact='$(pwd)/venv/bin/pii_redact'" >> ~/.bashrc
source ~/.bashrc
```

### Default Config

Set up a default config file so you don't need to specify `--config` every time:

```bash
mkdir -p ~/.config/pii_redact
cp sample_config.yaml ~/.config/pii_redact/config.yaml
# Edit with your actual PII values
```

## Quick Start

1. **Edit the default config** with your actual PII values (`~/.config/pii_redact/config.yaml`):
   ```yaml
   pii:
     first_name:
       value: "John"          # Your actual name
       replacement: "Mike"    # Fake replacement

     email:
       value: "john@gmail.com"
       replacement: "user@example.com"

     phone:
       value: "555-123-4567"
       replacement: "555-000-0000"

   settings:
     case_sensitive: false
   ```

2. **Run the tool** from any directory:
   ```bash
   pii_redact debug.log
   ```

3. **Share the redacted file** (`debug_redacted.log`) safely.

## Usage

```bash
# Basic usage - uses default config (~/.config/pii_redact/config.yaml)
pii_redact input.log

# Use a specific config file
pii_redact input.log --config my_pii.yaml

# Process multiple files with glob pattern
pii_redact "logs/**/*.log"

# Specify output file (single file only)
pii_redact input.log --output clean.log

# Preview changes without modifying files
pii_redact input.log --dry-run

# Skip interactive prompts (exact matches only)
pii_redact input.log --no-interactive

# Disable colored output
pii_redact input.log --no-color

# Customize context lines shown for partial matches
pii_redact input.log --context-lines 3

# Specify report output path
pii_redact input.log --report report.json
```

## Configuration

The config file uses YAML format with two main sections:

### PII Fields

Define each PII field with:
- `value` - Your actual PII value to find
- `replacement` - The fake value to replace it with
- `min_partial_length` (optional) - Minimum characters for partial matching (default: 3)

```yaml
pii:
  # Basic identity
  first_name:
    value: "John"
    replacement: "Mike"
    min_partial_length: 3

  last_name:
    value: "Smith"
    replacement: "Jones"

  full_name:
    value: "John Smith"
    replacement: "Mike Jones"

  # Contact info
  email:
    value: "john.smith@gmail.com"
    replacement: "user@example.com"

  phone:
    value: "+1-555-123-4567"
    replacement: "+1-555-000-0000"

  # Government IDs
  ssn:
    value: "123-45-6789"
    replacement: "XXX-XX-XXXX"

  aadhaar:
    value: "1234 5678 9012"
    replacement: "XXXX XXXX XXXX"

  pan:
    value: "ABCDE1234F"
    replacement: "XXXXX0000X"

  # Financial
  credit_card:
    value: "4111-1111-1111-1111"
    replacement: "XXXX-XXXX-XXXX-XXXX"

  # Custom fields - add any field you need
  employee_id:
    value: "EMP12345"
    replacement: "EMPXXXXX"

  api_key:
    value: "sk_live_abc123"
    replacement: "sk_live_REDACTED"
```

### Settings

```yaml
settings:
  # Minimum characters for partial match detection (default: 3)
  default_min_partial_length: 3

  # Case-sensitive matching (default: false)
  # When false: "John", "john", "JOHN" all match
  case_sensitive: false
```

## How It Works

### Exact Matches

The tool finds standalone occurrences of your PII values and replaces them:

```
Before: User John Smith logged in from john.smith@gmail.com
After:  User Mike Jones logged in from user@example.com
```

Case is preserved based on the original text:
- "John" → "Mike"
- "john" → "mike"
- "JOHN" → "MIKE"

### Partial Matches

When your PII appears as part of a larger word/token, the tool flags it as a "probable match":

```
Found probable match: "JohnSmithDev" contains "John" (line 45)

    43: Starting process...
    44: Connecting to server
  > 45: User JohnSmithDev logged in
    46: Session started

Replace probable matches? [a]ll / [n]one / [s]elect:
```

You can then choose to:
- `a` - Replace all probable matches
- `n` - Skip all probable matches
- `s` - Select specific matches by number (e.g., "1,3,5")

### Overlap Handling

When PII values overlap (e.g., "john" within "john.smith@gmail.com"), the longer match takes precedence. The email is replaced as a whole, not with "john" separately replaced within it.

## Output

### Redacted Files

Output files are created with `_redacted` suffix:
- `input.log` → `input_redacted.log`
- `data.json` → `data_redacted.json`

### Console Summary

```
Processing: debug.log

  Exact matches found and replaced:
    - first_name: 12 occurrence(s)
    - email: 3 occurrence(s)
    - phone: 1 occurrence(s)

  Found 2 probable match(es)

  Output: debug_redacted.log
  Replacements: 16 (exact: 16, partial: 0)

Summary
=======
  Files processed: 1
  Total exact replacements: 16
  Total probable replacements: 0
  Total probable skipped: 2
  Total replacements: 16

Report saved: debug_redacted_report.json
```

### JSON Report

A detailed report is saved for each run:

```json
{
  "started_at": "2024-01-15T10:30:45.123456",
  "completed_at": "2024-01-15T10:30:46.789012",
  "config_file": "my_pii.yaml",
  "summary": {
    "total_files": 1,
    "total_exact_replacements": 16,
    "total_partial_replaced": 0,
    "total_partial_skipped": 2,
    "total_replacements": 16
  },
  "files": [
    {
      "input_file": "debug.log",
      "output_file": "debug_redacted.log",
      "exact_matches": {
        "first_name": 12,
        "email": 3,
        "phone": 1
      },
      "partial_matches": {
        "first_name": 2
      },
      "partial_replaced": {},
      "partial_skipped": {
        "first_name": 2
      }
    }
  ]
}
```

## Supported File Types

| Extension | Handler | Notes |
|-----------|---------|-------|
| `.txt`, `.log`, `.md`, `.csv` | Text | Line-by-line processing |
| `.json` | JSON | Preserves structure, redacts keys and values |
| `.yaml`, `.yml` | YAML | Preserves structure, redacts keys and values |
| (no extension) | Text | Treated as plain text |

## Tips

1. **Order matters for overlapping values** - Define longer/more specific values before shorter ones (e.g., "John Smith" before "John")

2. **Use min_partial_length wisely** - Short values like "Li" or "123" can cause many false positives. Set higher thresholds:
   ```yaml
   zip_code:
     value: "12345"
     replacement: "00000"
     min_partial_length: 5  # Require full match
   ```

3. **Include variations** - Add entries for different formats of the same data:
   ```yaml
   phone_with_country:
     value: "+1-555-123-4567"
     replacement: "+1-555-000-0000"
   phone_without_country:
     value: "555-123-4567"
     replacement: "555-000-0000"
   ```

4. **Test with dry-run first** - Always preview changes before modifying files:
   ```bash
   pii_redact important.log --dry-run
   ```

5. **Keep your config file secure** - It contains your actual PII! Add it to `.gitignore`:
   ```
   my_pii.yaml
   *_pii.yaml
   ```

## Security Considerations

- **Config files contain real PII** - Never commit your personal config to version control
- **Redacted files may still contain PII** - Partial matches are only detected for alphanumeric PII; always review output
- **This is not a foolproof solution** - It only finds what you explicitly configure; novel PII formats won't be detected

## Contributing

Contributions are welcome! Please feel free to submit issues and pull requests.

## License

MIT License - See [LICENSE](LICENSE) for details.
