#!/usr/bin/env python3
"""Interactive PII config generator for pii-redact."""

import argparse
import random
import re
import sys
from pathlib import Path

import yaml


MIN_VARIATION_LENGTH = 3


# ============================================
# Scramble Helpers
# ============================================

def scramble(text: str) -> str:
    """Shuffle characters in a string, ensuring result differs from input."""
    if len(text) <= 1:
        return text
    chars = list(text)
    for _ in range(10):
        random.shuffle(chars)
        if chars != list(text):
            break
    return ''.join(chars)


def scramble_digits(digits: str) -> str:
    """Shuffle digits in a string, ensuring result doesn't start with 0."""
    if len(digits) <= 1:
        return digits
    chars = list(digits)
    for _ in range(20):
        random.shuffle(chars)
        if chars[0] != '0' and chars != list(digits):
            break
    # If still starts with 0 (e.g., all zeros), swap first 0 with first non-zero
    if chars[0] == '0':
        for i in range(1, len(chars)):
            if chars[i] != '0':
                chars[0], chars[i] = chars[i], chars[0]
                break
    return ''.join(chars)


# ============================================
# Variation Generators
# ============================================
# Each generator returns dict[str, str] mapping variation -> replacement.
# The replacement preserves the exact format of that variation.

def generate_name_variations(first: str, middle: str, last: str,
                             r_first: str, r_middle: str, r_last: str) -> dict[str, str]:
    """Generate name variations with format-matched replacements."""
    pairs = {}

    def add(value, replacement):
        if value and len(value) >= MIN_VARIATION_LENGTH:
            pairs[value] = replacement

    # Individual names
    add(first, r_first)
    if middle:
        add(middle, r_middle)
    add(last, r_last)

    if first and last:
        fi, rfi = first[0], r_first[0]

        # Two-name combos (with spaces)
        add(f"{first} {last}", f"{r_first} {r_last}")
        add(f"{last} {first}", f"{r_last} {r_first}")

        # No spaces
        add(f"{first}{last}", f"{r_first}{r_last}")
        add(f"{last}{first}", f"{r_last}{r_first}")

        # Initial forms
        add(f"{fi} {last}", f"{rfi} {r_last}")
        add(f"{fi}. {last}", f"{rfi}. {r_last}")
        add(f"{fi}{last}", f"{rfi}{r_last}")

        # Comma forms
        add(f"{last}, {first}", f"{r_last}, {r_first}")

    if first and middle and last:
        fi, rfi = first[0], r_first[0]
        mi, rmi = middle[0], r_middle[0]

        # Three-name combos (with spaces)
        add(f"{first} {middle} {last}", f"{r_first} {r_middle} {r_last}")
        add(f"{last} {first} {middle}", f"{r_last} {r_first} {r_middle}")
        add(f"{last} {middle} {first}", f"{r_last} {r_middle} {r_first}")

        # No spaces
        add(f"{first}{middle}{last}", f"{r_first}{r_middle}{r_last}")
        add(f"{last}{first}{middle}", f"{r_last}{r_first}{r_middle}")
        add(f"{last}{middle}{first}", f"{r_last}{r_middle}{r_first}")

        # Middle initial (with spaces)
        add(f"{first} {mi} {last}", f"{r_first} {rmi} {r_last}")
        add(f"{first} {mi}. {last}", f"{r_first} {rmi}. {r_last}")

        # Middle initial (no space before initial)
        add(f"{first}{mi} {last}", f"{r_first}{rmi} {r_last}")

        # Both initials
        add(f"{fi} {mi} {last}", f"{rfi} {rmi} {r_last}")
        add(f"{fi}. {mi}. {last}", f"{rfi}. {rmi}. {r_last}")
        add(f"{fi}{mi} {last}", f"{rfi}{rmi} {r_last}")
        add(f"{fi}.{mi}. {last}", f"{rfi}.{rmi}. {r_last}")

        # No spaces with initials
        add(f"{first}{mi}{last}", f"{r_first}{rmi}{r_last}")
        add(f"{fi}{mi}{last}", f"{rfi}{rmi}{r_last}")

        # Comma forms with middle
        add(f"{last}, {first} {middle}", f"{r_last}, {r_first} {r_middle}")
        add(f"{last}, {first} {mi}.", f"{r_last}, {r_first} {rmi}.")

    return dict(sorted(pairs.items()))


def generate_phone_variations(digits: str, cc: str, r_digits: str) -> dict[str, str]:
    """Generate phone variations with format-matched replacements."""
    pairs = {}

    def add(value, replacement):
        pairs[value] = replacement

    # --- No grouping ---
    add(digits, r_digits)
    add(f"0{digits}", f"0{r_digits}")

    # With country code, no separator
    add(f"{cc}{digits}", f"{cc}{r_digits}")
    add(f"+{cc}{digits}", f"+{cc}{r_digits}")
    add(f"0{cc}{digits}", f"0{cc}{r_digits}")

    # With country code, separator
    for sep in [' ', '-']:
        add(f"+{cc}{sep}{digits}", f"+{cc}{sep}{r_digits}")
        add(f"{cc}{sep}{digits}", f"{cc}{sep}{r_digits}")

    # --- Grouped: 5+5 ---
    if len(digits) == 10:
        h1, h2 = digits[:5], digits[5:]
        rh1, rh2 = r_digits[:5], r_digits[5:]

        for sep in [' ', '-', '.']:
            add(f"{h1}{sep}{h2}", f"{rh1}{sep}{rh2}")

        # 5+5 with country code prefix
        for prefix, rprefix in [(f"+{cc}", f"+{cc}"), (cc, cc)]:
            for psep in [' ', '-']:
                for dsep in [' ', '-']:
                    add(f"{prefix}{psep}{h1}{dsep}{h2}",
                        f"{rprefix}{psep}{rh1}{dsep}{rh2}")

        # 5+5 with leading 0
        for dsep in [' ', '-']:
            add(f"0{dsep}{h1}{dsep}{h2}", f"0{dsep}{rh1}{dsep}{rh2}")

    # --- Grouped: 3+3+4 ---
    if len(digits) == 10:
        p1, p2, p3 = digits[:3], digits[3:6], digits[6:]
        rp1, rp2, rp3 = r_digits[:3], r_digits[3:6], r_digits[6:]

        for sep in [' ', '-', '.']:
            add(f"{p1}{sep}{p2}{sep}{p3}", f"{rp1}{sep}{rp2}{sep}{rp3}")

        # Parenthesized area code
        add(f"({p1}) {p2}-{p3}", f"({rp1}) {rp2}-{rp3}")
        add(f"({p1}) {p2} {p3}", f"({rp1}) {rp2} {rp3}")
        add(f"({p1}){p2}-{p3}", f"({rp1}){rp2}-{rp3}")
        add(f"({p1}){p2}{p3}", f"({rp1}){rp2}{rp3}")

        # 3+3+4 with country code
        for prefix, rprefix in [(f"+{cc}", f"+{cc}"), (cc, cc)]:
            for psep in [' ', '-']:
                for dsep in [' ', '-']:
                    add(f"{prefix}{psep}{p1}{dsep}{p2}{dsep}{p3}",
                        f"{rprefix}{psep}{rp1}{dsep}{rp2}{dsep}{rp3}")

    return dict(sorted(pairs.items()))


def generate_email_variations(email: str, r_email: str) -> dict[str, str]:
    """Generate email variations with format-matched replacements."""
    pairs = {}

    pairs[email] = r_email

    if '@' not in email or '@' not in r_email:
        return pairs

    local, domain = email.rsplit('@', 1)
    r_local, r_domain = r_email.rsplit('@', 1)

    # [at] / (at) variations
    pairs[f"{local}[at]{domain}"] = f"{r_local}[at]{r_domain}"
    pairs[f"{local} [at] {domain}"] = f"{r_local} [at] {r_domain}"
    pairs[f"{local}(at){domain}"] = f"{r_local}(at){r_domain}"
    pairs[f"{local} (at) {domain}"] = f"{r_local} (at) {r_domain}"

    # [dot] in domain
    if '.' in domain:
        domain_b = domain.replace('.', '[dot]')
        r_domain_b = r_domain.replace('.', '[dot]')
        pairs[f"{local}@{domain_b}"] = f"{r_local}@{r_domain_b}"
        pairs[f"{local}[at]{domain_b}"] = f"{r_local}[at]{r_domain_b}"
        pairs[f"{local} [at] {domain_b}"] = f"{r_local} [at] {r_domain_b}"

    return dict(sorted(pairs.items()))


def generate_aadhar_variations(digits: str, r_digits: str) -> dict[str, str]:
    """Generate Aadhar variations with format-matched replacements."""
    pairs = {}

    g1, g2, g3 = digits[:4], digits[4:8], digits[8:]
    rg1, rg2, rg3 = r_digits[:4], r_digits[4:8], r_digits[8:]

    # Full number
    pairs[digits] = r_digits
    pairs[f"{g1} {g2} {g3}"] = f"{rg1} {rg2} {rg3}"
    pairs[f"{g1}-{g2}-{g3}"] = f"{rg1}-{rg2}-{rg3}"

    # Masked: last 4 visible
    for mask in ['X', '*']:
        m4 = mask * 4
        m8 = mask * 8
        pairs[f"{m4} {m4} {g3}"] = f"{m4} {m4} {rg3}"
        pairs[f"{m4}-{m4}-{g3}"] = f"{m4}-{m4}-{rg3}"
        pairs[f"{m8}{g3}"] = f"{m8}{rg3}"

    # Masked: first 4 visible
    for mask in ['X', '*']:
        m4 = mask * 4
        m8 = mask * 8
        pairs[f"{g1} {m4} {m4}"] = f"{rg1} {m4} {m4}"
        pairs[f"{g1}-{m4}-{m4}"] = f"{rg1}-{m4}-{m4}"
        pairs[f"{g1}{m8}"] = f"{rg1}{m8}"

    return dict(sorted(pairs.items()))


def generate_credit_card_variations(digits: str, r_digits: str) -> dict[str, str]:
    """Generate credit card variations with format-matched replacements."""
    pairs = {}

    g1, g2, g3, g4 = digits[:4], digits[4:8], digits[8:12], digits[12:]
    rg1, rg2, rg3, rg4 = r_digits[:4], r_digits[4:8], r_digits[8:12], r_digits[12:]

    # Full number
    pairs[digits] = r_digits
    pairs[f"{g1} {g2} {g3} {g4}"] = f"{rg1} {rg2} {rg3} {rg4}"
    pairs[f"{g1}-{g2}-{g3}-{g4}"] = f"{rg1}-{rg2}-{rg3}-{rg4}"

    # Masked: last 4 visible
    for mask in ['X', '*']:
        m4 = mask * 4
        m12 = mask * 12
        pairs[f"{m4} {m4} {m4} {g4}"] = f"{m4} {m4} {m4} {rg4}"
        pairs[f"{m4}-{m4}-{m4}-{g4}"] = f"{m4}-{m4}-{m4}-{rg4}"
        pairs[f"{m12}{g4}"] = f"{m12}{rg4}"

    # Masked: first 4 visible
    for mask in ['X', '*']:
        m4 = mask * 4
        m12 = mask * 12
        pairs[f"{g1} {m4} {m4} {m4}"] = f"{rg1} {m4} {m4} {m4}"
        pairs[f"{g1}-{m4}-{m4}-{m4}"] = f"{rg1}-{m4}-{m4}-{m4}"
        pairs[f"{g1}{m12}"] = f"{rg1}{m12}"

    return dict(sorted(pairs.items()))


# ============================================
# Input Helpers
# ============================================

def prompt(message: str, required: bool = False, validator=None) -> str:
    """Get input from user with optional validation."""
    while True:
        try:
            value = input(message).strip()
        except EOFError:
            return ""

        if not value and not required:
            return ""
        if not value and required:
            print("  This field is required.")
            continue
        if validator:
            error = validator(value)
            if error:
                print(f"  {error}")
                continue
        return value


def prompt_yes_no(message: str) -> bool:
    """Ask a yes/no question."""
    while True:
        try:
            value = input(f"{message} (y/n): ").strip().lower()
        except EOFError:
            return False
        if value in ('y', 'yes'):
            return True
        if value in ('n', 'no'):
            return False
        print("  Please enter 'y' or 'n'.")


def strip_non_digits(value: str) -> str:
    """Remove all non-digit characters from a string."""
    return re.sub(r'\D', '', value)


def validate_digits(value: str, expected_length: int, label: str):
    """Return a validator function for digit-only input with expected length."""
    def validator(v):
        cleaned = strip_non_digits(v)
        if not cleaned:
            return "Please enter digits only."
        if len(cleaned) != expected_length:
            return f"{label} must be exactly {expected_length} digits (got {len(cleaned)})."
        return None
    return validator


def validate_length(expected_length: int, label: str):
    """Return a validator that checks string length matches expected."""
    def validator(v):
        if len(v) != expected_length:
            return f"{label} must be exactly {expected_length} characters (got {len(v)})."
        return None
    return validator


def validate_digit_length(expected_length: int, label: str):
    """Return a validator that strips non-digits then checks length and leading zero."""
    def validator(v):
        cleaned = strip_non_digits(v)
        if not cleaned:
            return "Please enter digits only."
        if len(cleaned) != expected_length:
            return f"{label} must be exactly {expected_length} digits (got {len(cleaned)})."
        if cleaned[0] == '0':
            return f"{label} must not start with 0."
        return None
    return validator


def print_variation_pairs(pairs: dict[str, str], label: str):
    """Display generated variation -> replacement pairs."""
    max_val_len = max(len(v) for v in pairs)
    print(f"\n  Generated {len(pairs)} variations for {label}:")
    for value, replacement in pairs.items():
        print(f"    {value:<{max_val_len}}  ->  {replacement}")
    print()


# ============================================
# Collectors (interactive input for each PII type)
# ============================================

def collect_single_name(num: int):
    """Collect one name entry interactively."""
    first = prompt("Enter first name (or press Enter to skip): ")
    if not first:
        return None

    middle = prompt("Enter middle name (or press Enter to skip): ")
    last = prompt("Enter last name (or press Enter to skip): ")

    if not first and not last:
        print("  Need at least a first or last name.")
        return None

    # Ask for replacement parts with scrambled defaults
    def_r_first = scramble(first) if first else ""
    def_r_middle = scramble(middle) if middle else ""
    def_r_last = scramble(last) if last else ""

    print(f"\n  Replacement name parts (press Enter for scrambled default):")
    r_first = prompt(
        f"    Replacement first name (default: {def_r_first}): ",
        validator=validate_length(len(first), "Replacement first name"),
    ) or def_r_first
    if middle:
        r_middle = prompt(
            f"    Replacement middle name (default: {def_r_middle}): ",
            validator=validate_length(len(middle), "Replacement middle name"),
        ) or def_r_middle
    else:
        r_middle = ""
    if last:
        r_last = prompt(
            f"    Replacement last name (default: {def_r_last}): ",
            validator=validate_length(len(last), "Replacement last name"),
        ) or def_r_last
    else:
        r_last = ""

    pairs = generate_name_variations(first, middle, last, r_first, r_middle, r_last)
    label = f"NAME_{num}"
    print_variation_pairs(pairs, label)

    return {'type': 'name', 'num': num, 'label': label, 'pairs': pairs}


def collect_single_phone(num: int):
    """Collect one phone number entry interactively."""
    raw = prompt("Enter phone number (or press Enter to skip): ")
    if not raw:
        return None

    digits = strip_non_digits(raw)
    if not digits:
        print("  No digits found in input.")
        return None

    cc_raw = prompt("Enter country code (e.g., 91 for India, 1 for US): ", required=True)
    cc = strip_non_digits(cc_raw)

    def_r_digits = scramble_digits(digits)
    r_digits = prompt(
        f"Replacement digits (default: {def_r_digits}): ",
        validator=validate_digit_length(len(digits), "Replacement phone"),
    ) or def_r_digits
    r_digits = strip_non_digits(r_digits)

    pairs = generate_phone_variations(digits, cc, r_digits)
    label = f"PHONE_{num}"
    print_variation_pairs(pairs, label)

    return {'type': 'phone', 'num': num, 'label': label, 'pairs': pairs}


def collect_single_email(num: int):
    """Collect one email entry interactively."""
    email = prompt("Enter email address (or press Enter to skip): ")
    if not email:
        return None

    if '@' not in email:
        print("  Invalid email (must contain @).")
        return None

    local, domain = email.rsplit('@', 1)
    def_r_email = f"{scramble(local)}@{domain}"

    def validate_email_length(v):
        if '@' not in v:
            return "Replacement must be a valid email (must contain @)."
        r_local, _ = v.rsplit('@', 1)
        if len(r_local) != len(local):
            return f"Local part must be exactly {len(local)} characters (got {len(r_local)})."
        return None

    r_email = prompt(
        f"Replacement email (default: {def_r_email}): ",
        validator=validate_email_length,
    ) or def_r_email

    pairs = generate_email_variations(email, r_email)
    label = f"EMAIL_{num}"
    print_variation_pairs(pairs, label)

    return {'type': 'email', 'num': num, 'label': label, 'pairs': pairs}


def collect_single_aadhar(num: int):
    """Collect one Aadhar number entry interactively."""
    raw = prompt("Enter Aadhar number (12 digits, or press Enter to skip): ",
                 validator=lambda v: validate_digits(v, 12, "Aadhar")(v) if v else None)
    if not raw:
        return None

    digits = strip_non_digits(raw)
    def_r_digits = scramble_digits(digits)
    r_digits = prompt(
        f"Replacement digits (default: {def_r_digits}): ",
        validator=validate_digit_length(12, "Replacement Aadhar"),
    ) or def_r_digits
    r_digits = strip_non_digits(r_digits)

    pairs = generate_aadhar_variations(digits, r_digits)
    label = f"AADHAR_{num}"
    print_variation_pairs(pairs, label)

    return {'type': 'aadhar', 'num': num, 'label': label, 'pairs': pairs}


def collect_single_credit_card(num: int):
    """Collect one credit card number entry interactively."""
    raw = prompt("Enter credit card number (16 digits, or press Enter to skip): ",
                 validator=lambda v: validate_digits(v, 16, "Credit card")(v) if v else None)
    if not raw:
        return None

    digits = strip_non_digits(raw)
    def_r_digits = scramble_digits(digits)
    r_digits = prompt(
        f"Replacement digits (default: {def_r_digits}): ",
        validator=validate_digit_length(16, "Replacement credit card"),
    ) or def_r_digits
    r_digits = strip_non_digits(r_digits)

    pairs = generate_credit_card_variations(digits, r_digits)
    label = f"CARD_{num}"
    print_variation_pairs(pairs, label)

    return {'type': 'card', 'num': num, 'label': label, 'pairs': pairs}


# ============================================
# Config I/O
# ============================================

def get_max_number(pii_dict: dict, type_prefix: str) -> int:
    """Find the highest entry number for a given type prefix in existing config."""
    max_num = 0
    pattern = re.compile(rf'^{re.escape(type_prefix)}_(\d+)_v\d+$')
    for key in pii_dict:
        m = pattern.match(key)
        if m:
            max_num = max(max_num, int(m.group(1)))
    return max_num


def count_entries(pii_dict: dict, type_prefix: str) -> int:
    """Count distinct entry numbers for a type (e.g., name_1 and name_2 = 2)."""
    nums = set()
    pattern = re.compile(rf'^{re.escape(type_prefix)}_(\d+)_v\d+$')
    for key in pii_dict:
        m = pattern.match(key)
        if m:
            nums.add(int(m.group(1)))
    return len(nums)


def entries_to_pii_dict(entries: list[dict]) -> dict:
    """Convert collector entries to a flat pii dict for YAML output."""
    pii = {}
    for entry in entries:
        type_prefix = entry['type']
        num = entry['num']
        pairs = entry['pairs']
        for i, (variation, replacement) in enumerate(pairs.items(), 1):
            key = f"{type_prefix}_{num}_v{i}"
            pii[key] = {
                'value': variation,
                'replacement': replacement,
            }
    return pii


def escape_yaml_value(s: str) -> str:
    """Escape a string for safe inclusion in double-quoted YAML."""
    return s.replace('\\', '\\\\').replace('"', '\\"')


def write_config(pii_dict: dict, settings: dict, config_path: Path):
    """Write config file with section comments and nice formatting."""
    lines = [
        "# PII Redaction Config",
        "# Generated by: pii-redact init",
        "",
        "pii:",
    ]

    # Group keys by type and entry number
    # Key format: {type}_{num}_v{var_num}
    groups = {}
    key_pattern = re.compile(r'^(.+?)_(\d+)_v(\d+)$')
    ungrouped = []

    for key in pii_dict:
        m = key_pattern.match(key)
        if m:
            type_name, num, _ = m.group(1), int(m.group(2)), int(m.group(3))
            group_key = f"{type_name}_{num}"
            if group_key not in groups:
                groups[group_key] = []
            groups[group_key].append(key)
        else:
            ungrouped.append(key)

    # Sort groups by type order, then by number
    type_order = {'name': 0, 'phone': 1, 'email': 2, 'aadhar': 3, 'card': 4}

    def group_sort_key(group_key):
        parts = group_key.rsplit('_', 1)
        type_name = parts[0]
        num = int(parts[1]) if len(parts) > 1 else 0
        return (type_order.get(type_name, 99), num)

    type_labels = {
        'name': 'NAMES',
        'phone': 'PHONE NUMBERS',
        'email': 'EMAIL ADDRESSES',
        'aadhar': 'AADHAR NUMBERS',
        'card': 'CREDIT CARDS',
    }

    prev_type = None
    for group_key in sorted(groups.keys(), key=group_sort_key):
        type_name = group_key.rsplit('_', 1)[0]

        # Section header when type changes
        if type_name != prev_type:
            lines.append("")
            lines.append(f"  # {'=' * 44}")
            lines.append(f"  # {type_labels.get(type_name, type_name.upper())}")
            lines.append(f"  # {'=' * 44}")
            prev_type = type_name

        # Group label
        label = group_key.upper()
        lines.append(f"  # --- {label} ---")

        # Sort variations by var number
        var_keys = sorted(groups[group_key],
                          key=lambda k: int(key_pattern.match(k).group(3)))

        for key in var_keys:
            entry = pii_dict[key]
            value = escape_yaml_value(entry['value'])
            replacement = escape_yaml_value(entry['replacement'])
            lines.append(f"  {key}:")
            lines.append(f'    value: "{value}"')
            lines.append(f'    replacement: "{replacement}"')

    # Ungrouped entries (from hand-edited configs)
    if ungrouped:
        lines.append("")
        lines.append(f"  # {'=' * 44}")
        lines.append(f"  # OTHER")
        lines.append(f"  # {'=' * 44}")
        for key in sorted(ungrouped):
            entry = pii_dict[key]
            if isinstance(entry, dict):
                value = escape_yaml_value(str(entry.get('value', '')))
                replacement = escape_yaml_value(str(entry.get('replacement', '')))
                lines.append(f"  {key}:")
                lines.append(f'    value: "{value}"')
                lines.append(f'    replacement: "{replacement}"')
                if 'min_partial_length' in entry:
                    lines.append(f"    min_partial_length: {entry['min_partial_length']}")

    # Settings
    lines.append("")
    lines.append("settings:")
    lines.append(f"  default_min_partial_length: {settings.get('default_min_partial_length', 3)}")
    case_val = 'true' if settings.get('case_sensitive', False) else 'false'
    lines.append(f"  case_sensitive: {case_val}")
    lines.append("")

    config_path.write_text('\n'.join(lines), encoding='utf-8')


def load_existing_config(config_path: Path) -> tuple[dict, dict]:
    """Load existing config and return (pii_dict, settings_dict)."""
    if not config_path.exists():
        return {}, {'default_min_partial_length': 3, 'case_sensitive': False}

    with open(config_path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f) or {}

    pii = data.get('pii', {}) or {}
    settings = data.get('settings', {}) or {
        'default_min_partial_length': 3,
        'case_sensitive': False,
    }
    return pii, settings


# ============================================
# Main Commands
# ============================================

def run_full_init(config_path: Path):
    """Run the full interactive config wizard."""
    print("\nPII Config Generator")
    print("=" * 40)

    if config_path.exists():
        if not prompt_yes_no(f"\n{config_path} already exists. Overwrite?"):
            print("Aborted.")
            return

    all_entries = []

    # Names
    print("\n--- Names ---")
    num = 1
    while True:
        entry = collect_single_name(num)
        if entry is None:
            break
        all_entries.append(entry)
        num += 1
        if not prompt_yes_no("Add another name?"):
            break

    # Phone numbers
    print("\n--- Phone Numbers ---")
    num = 1
    while True:
        entry = collect_single_phone(num)
        if entry is None:
            break
        all_entries.append(entry)
        num += 1
        if not prompt_yes_no("Add another phone number?"):
            break

    # Emails
    print("\n--- Email Addresses ---")
    num = 1
    while True:
        entry = collect_single_email(num)
        if entry is None:
            break
        all_entries.append(entry)
        num += 1
        if not prompt_yes_no("Add another email?"):
            break

    # Aadhar
    print("\n--- Aadhar Numbers ---")
    num = 1
    while True:
        entry = collect_single_aadhar(num)
        if entry is None:
            break
        all_entries.append(entry)
        num += 1
        if not prompt_yes_no("Add another Aadhar number?"):
            break

    # Credit cards
    print("\n--- Credit Cards ---")
    num = 1
    while True:
        entry = collect_single_credit_card(num)
        if entry is None:
            break
        all_entries.append(entry)
        num += 1
        if not prompt_yes_no("Add another credit card?"):
            break

    if not all_entries:
        print("\nNo PII entries collected. Config not written.")
        return

    pii_dict = entries_to_pii_dict(all_entries)
    settings = {'default_min_partial_length': 3, 'case_sensitive': False}
    write_config(pii_dict, settings, config_path)

    total_variations = sum(len(e['pairs']) for e in all_entries)
    print(f"\nConfig written to: {config_path}")
    print(f"Total: {len(all_entries)} PII entries, {total_variations} variations")


def run_add(config_path: Path):
    """Add a single PII entry to an existing (or new) config."""
    pii_dict, settings = load_existing_config(config_path)

    type_info = [
        ('1', 'name',   'Name',        collect_single_name),
        ('2', 'phone',  'Phone',       collect_single_phone),
        ('3', 'email',  'Email',       collect_single_email),
        ('4', 'aadhar', 'Aadhar',      collect_single_aadhar),
        ('5', 'card',   'Credit Card', collect_single_credit_card),
    ]

    print("\nWhat type of PII do you want to add?")
    for key, prefix, display_name, _ in type_info:
        existing = count_entries(pii_dict, prefix)
        suffix = f"  ({existing} existing)" if existing else ""
        print(f"  {key}. {display_name}{suffix}")

    choice = prompt("\nChoose (1-5): ", required=True)

    selected = None
    for key, prefix, display_name, collector in type_info:
        if choice == key:
            selected = (prefix, collector)
            break

    if not selected:
        print("Invalid choice.")
        return

    type_prefix, collector = selected
    next_num = get_max_number(pii_dict, type_prefix) + 1

    entry = collector(next_num)
    if entry is None:
        print("No entry collected.")
        return

    # Add new variations to existing pii dict
    new_entries = entries_to_pii_dict([entry])
    pii_dict.update(new_entries)

    write_config(pii_dict, settings, config_path)

    print(f"\nAdded {len(entry['pairs'])} variations for [{entry['label']}] to {config_path}")


def run_init(argv: list[str]):
    """Entry point for the init subcommand."""
    parser = argparse.ArgumentParser(
        prog='pii-redact init',
        description='Generate PII config file interactively.',
    )
    parser.add_argument(
        '--add',
        action='store_true',
        help='Add a single PII entry to an existing config instead of creating a new one',
    )
    parser.add_argument(
        '-c', '--config',
        default='pii_config.yaml',
        help='Config file path (default: pii_config.yaml)',
    )
    args = parser.parse_args(argv)

    config_path = Path(args.config)

    try:
        if args.add:
            run_add(config_path)
        else:
            run_full_init(config_path)
    except KeyboardInterrupt:
        print("\n\nAborted.")
        sys.exit(1)
