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
- **Output verification** - Re-checks every output through base64, quoted-printable, percent-encoding, gzip and more, so PII hidden inside encoded content is reported instead of silently missed
- **Pipeline-friendly exit codes** - Non-zero when PII survives, so a failed redaction can be caught by a script rather than only by reading the console
- **Detailed reports** - JSON report of all replacements made

## Installation

Not on PyPI — install straight from GitHub. Requires Python 3.10+ and `git`.

**With pipx** (recommended — isolated environment, command on your `PATH`):

```bash
pipx install git+https://github.com/ivivek/pii_redact_cli.git
```

**With pip**, into a virtual environment:

```bash
python3 -m venv ~/.venvs/pii-redact
~/.venvs/pii-redact/bin/pip install git+https://github.com/ivivek/pii_redact_cli.git

# (Optional) Add an alias to ~/.bashrc for global access
echo "alias pii-redact='$HOME/.venvs/pii-redact/bin/pii-redact'" >> ~/.bashrc
source ~/.bashrc
```

Either way the command is `pii-redact`, and everything it needs — including the
sample config — is bundled, so no repo checkout is required to use it.

**Pin to a specific tag or branch** by appending `@ref`:

```bash
pipx install "git+https://github.com/ivivek/pii_redact_cli.git@v0.1.0"
```

**Updating and removing.** The installed package is named `pii-redact`, which is
what pip and pipx track it as:

```bash
pipx install --force git+https://github.com/ivivek/pii_redact_cli.git   # update
pipx uninstall pii-redact                                              # remove
```

### From a clone (for development)

```bash
git clone https://github.com/ivivek/pii_redact_cli.git
cd pii_redact_cli

python3 -m venv venv
./venv/bin/pip install -e .

echo "alias pii-redact='$(pwd)/venv/bin/pii-redact'" >> ~/.bashrc
source ~/.bashrc
```

## Quick Start

First you need a config file mapping your PII values to their replacements.
There are two ways to create one — pick whichever fits how you like to work.

**Option A — Interactive wizard** (recommended for thorough coverage):

```bash
pii-redact init
```

The wizard walks you through each PII type — names, phone numbers, emails,
Aadhar, credit cards, PAN, bank accounts, IFSC, MICR, dates of birth, and
custom text — then auto-generates all format variations with scrambled
replacement values. Use this when you want every format a value can appear in
covered without hand-writing them.

**Option B — Start from the sample config** (recommended if you'd rather hand-edit):

```bash
pii-redact init --sample
pii-redact init --sample -c my_pii.yaml    # or choose your own path
```

This writes a fully commented config pre-filled with example values across ~30
common PII types (identity, contact, address, US and India government IDs,
financial, usernames, IP addresses). Open it, swap the example values for your
own, and delete the entries you don't need. Use this when you want to see the
whole config format at a glance.

The sample ships inside the package, so `--sample` works on any install with no
repo checkout. If you have the repo cloned, it's the same file as
[`pii_redact/sample_config.yaml`](pii_redact/sample_config.yaml).

**Then redact:**

```bash
pii-redact debug.log
```

Both `init` and the redactor default to the same config path
(`~/.config/pii_redact/pii_config.yaml`), so a config created by `init` is
picked up with no `-c` flag. Pass `-c` on both commands to use another path.

Finally, **share the redacted file** (`debug_redacted.log`) safely.

> **Note:** `init` and `init --sample` create a config from scratch, so they warn
> and ask for confirmation before replacing an existing one. To extend a config
> you already have rather than replace it, use `pii-redact init --add`.

## Usage

### Config Generator

```bash
# Full interactive wizard — generates config with all PII type variations
pii-redact init

# Use a custom config path
pii-redact init -c my_pii.yaml

# Write the bundled sample config to edit by hand (skips the wizard)
pii-redact init --sample
pii-redact init --sample -c my_pii.yaml

# Add one more PII entry to an existing config
pii-redact init --add
pii-redact init --add -c my_pii.yaml
```

`--sample` and `--add` are mutually exclusive; with neither, `init` runs the wizard.
All `init` forms default to `~/.config/pii_redact/pii_config.yaml` — the same path
the redactor reads — and create parent directories as needed. `init` and
`init --sample` warn and ask before replacing an existing config; `--add` extends
it in place.

The `init` wizard walks you through each PII type:
- **Names** — first, middle, last name. Generates permutations (first-last, last-first, initials, comma-separated, concatenated, etc.)
- **Phone numbers** — digits and country code. Generates variations with/without country code prefix, 5+5 and 3+3+4 groupings, space/dash/dot separators
- **Email** — generates `[at]`/`(at)`/`[dot]` obfuscated variants
- **Aadhar** — 12-digit number with 4-4-4 grouping, masked variants (first/last 4 visible)
- **Credit Card** — 16-digit number with 4-4-4-4 grouping, masked variants
- **PAN Card** — 10-character alphanumeric
- **Bank Account** — variable-length account number
- **IFSC Code** — 11-character bank branch code
- **MICR Code** — 9-digit cheque code
- **Date of Birth** — generates ~22 format variations (DD/MM/YYYY, YYYY-MM-DD, "15 Jan 1990", etc.)
- **Custom Text** — any free-form text value and its replacement

Each variation gets a **format-matched replacement** — the replacement preserves the
exact structure of that variation. Defaults are auto-scrambled from your input; you
can accept them or type your own (must match the original length).

**Privacy note:** The generated config uses anonymized keys (`text_1_v1`, `text_2_v1`, etc.)
so the file itself doesn't reveal what type of PII each entry represents.

### Redacting Files

```bash
# Basic usage - single file (default config: ~/.config/pii_redact/pii_config.yaml)
pii-redact input.log

# Multiple files
pii-redact file1.log file2.log file3.log

# Shell wildcard - all .log files in current directory
pii-redact *.log

# Mixed patterns
pii-redact *.log *.txt

# Quoted glob for recursive matching
pii-redact "logs/**/*.log"

# Use a custom config file
pii-redact input.log -c my_pii.yaml

# Specify output file (single file only)
pii-redact input.log --output clean.log

# Preview changes without modifying files
pii-redact input.log --dry-run

# Handle partial/probable matches without prompting
pii-redact input.log --partial all         # Replace all partial matches
pii-redact input.log --partial none        # Skip all partial matches
pii-redact input.log --no-interactive      # Same as --partial none

# Disable colored output
pii-redact input.log --no-color

# Customize context lines shown for partial matches
pii-redact input.log --context-lines 3

# Generate a JSON report (not created by default)
pii-redact input.log --report                  # Auto-named: <output>_report.json
pii-redact input.log --report report.json      # Custom report path

# Also fail when part of a file could not be inspected at all
pii-redact input.eml --strict

# Skip the verification pass (not recommended)
pii-redact input.log --no-verify
```

## Verification

Matching runs against a file's literal bytes. Anything that encodes text on the
way in — a base64 or quoted-printable MIME part in an `.eml`, a percent-encoded
query string in an access log, an HTML entity, a gzipped payload — hides that
text from the matcher. The redaction still reports a replacement count, and
grepping the output for your PII still finds nothing, so the obvious sanity
check confirms a file is clean when it is not.

After redacting, the tool decodes its own output every way it knows how and
re-runs matching over each decoded view. Anything still recoverable is reported
as a failure:

```
  Output: order_redacted.eml
  Replacements: 5 (exact: 5, partial: 0)

  VERIFICATION FAILED - configured PII survives in the output:
    - text_1_v1: 1 occurrence(s) after decoding: base64
    - text_2_v1: 1 occurrence(s) after decoding: quoted-printable
  Do not share this file.
```

Field names are shown, values never are — the config key identifies the entry
without printing the PII to your terminal or CI log.

Content that cannot be searched as text at all (a PDF attachment, a
zip-backed `.docx`, a compressed blob) is reported separately, so a clean
result never quietly stands in for "nothing was looked at":

```
Warning: not inspected (base64, 3990 bytes): PDF document -- its contents cannot be searched as text
  Verification: no PII recoverable from the parts that could be read
```

This is a safety net, not a redactor: it tells you an encoded file was not
fully cleaned, it does not clean it. To actually redact encoded content, decode
it to text first and run the tool on that.

### Exit codes

| Code | Meaning |
|------|---------|
| `0` | Every output verified clean |
| `1` | Could not start: bad arguments, or missing/invalid config |
| `2` | Verification failed — configured PII is still recoverable from an output |
| `3` | One or more files could not be processed |
| `4` | Content could not be inspected (`--strict` only) |

```bash
pii-redact export.eml --no-interactive || echo "not safe to share"
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

To skip this prompt, use `--partial all` (replace all) or `--partial none` (skip all).

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

```

### JSON Report (opt-in via `--report`)

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

3. **Use `init` to auto-generate variations** instead of manually listing each format:
   ```bash
   pii-redact init
   ```
   This generates all format variations automatically for names, phones, cards, dates, and more.

4. **Test with dry-run first** - Always preview changes before modifying files:
   ```bash
   pii-redact important.log --dry-run
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
- **Encoded content is detected, not redacted** - Verification tells you when configured PII survives inside a base64 or quoted-printable part; it does not rewrite that part. Treat a non-zero exit as "do not share", not as a warning to skim past
- **A clean verification only covers what could be read** - Binary and compressed content is reported as uninspected; use `--strict` to make that fail the run

## Contributing

Contributions are welcome! Please feel free to submit issues and pull requests.

## License

MIT License - See [LICENSE](LICENSE) for details.
