"""
Matching logic for exact and partial PII matches.
"""

import re
from dataclasses import dataclass
from typing import Iterator

from config import PIIField


@dataclass
class Match:
    """Represents a match found in the text."""
    pii_field: PIIField
    start: int  # Start position in text
    end: int    # End position in text
    matched_text: str  # The actual text that was matched
    is_exact: bool  # True if exact match, False if partial/probable
    line_number: int = 0  # Line number (1-indexed)
    context_before: list[str] = None  # Lines before the match
    context_after: list[str] = None   # Lines after the match
    line_text: str = ""  # The full line containing the match

    def __post_init__(self):
        if self.context_before is None:
            self.context_before = []
        if self.context_after is None:
            self.context_after = []


class Matcher:
    """Finds exact and partial matches of PII in text."""

    def __init__(self, pii_fields: list[PIIField], case_sensitive: bool = False):
        self.pii_fields = pii_fields
        self.case_sensitive = case_sensitive

        # Sort fields by value length (longest first) to avoid partial replacement issues
        self.pii_fields_sorted = sorted(
            pii_fields,
            key=lambda f: len(f.value),
            reverse=True
        )

    def find_exact_matches(self, text: str) -> list[Match]:
        """Find all exact matches of PII values in text (standalone, not part of larger words)."""
        matches = []
        flags = 0 if self.case_sensitive else re.IGNORECASE

        for pii_field in self.pii_fields_sorted:
            pattern = re.escape(pii_field.value)

            for m in re.finditer(pattern, text, flags):
                # Check if this is a standalone match (not part of a larger word)
                # Character before should NOT be alphanumeric (or be start of string)
                # Character after should NOT be alphanumeric (or be end of string)
                start, end = m.start(), m.end()

                char_before = text[start - 1] if start > 0 else ''
                char_after = text[end] if end < len(text) else ''

                # For alphanumeric PII values, check word boundaries
                # For PII with special chars (emails, etc.), be more lenient
                is_alnum_pii = pii_field.value.replace(' ', '').isalnum()

                if is_alnum_pii:
                    # Strict word boundary check for names, IDs, etc.
                    before_ok = not char_before.isalnum() and char_before != '_'
                    after_ok = not char_after.isalnum() and char_after != '_'
                else:
                    # Looser check for emails, phone numbers, etc.
                    # Just ensure it's not embedded in a longer version of the same pattern
                    before_ok = not char_before.isalnum()
                    after_ok = not char_after.isalnum()

                if before_ok and after_ok:
                    matches.append(Match(
                        pii_field=pii_field,
                        start=start,
                        end=end,
                        matched_text=m.group(),
                        is_exact=True
                    ))

        # Remove matches that are fully contained within other matches
        # (e.g., "john" within "john.smith@gmail.com")
        matches = self._remove_overlapping_matches(matches)

        return matches

    def _remove_overlapping_matches(self, matches: list[Match]) -> list[Match]:
        """Remove matches that are fully contained within larger matches."""
        if not matches:
            return matches

        # Sort by start position, then by length (longer first)
        sorted_matches = sorted(matches, key=lambda m: (m.start, -(m.end - m.start)))

        result = []
        for match in sorted_matches:
            # Check if this match is contained within any existing match
            is_contained = False
            for existing in result:
                if match.start >= existing.start and match.end <= existing.end:
                    # This match is fully contained within an existing one
                    is_contained = True
                    break
            if not is_contained:
                result.append(match)

        return result

    def find_partial_matches(self, text: str, exact_matches: list[Match] = None) -> list[Match]:
        """
        Find partial/probable matches where PII value is part of a larger word/token.
        These are matches where the PII is embedded in something larger.
        """
        matches = []
        flags = 0 if self.case_sensitive else re.IGNORECASE

        # Build set of exact match ranges to avoid duplicates
        exact_ranges = []
        if exact_matches:
            exact_ranges = [(m.start, m.end) for m in exact_matches]

        for pii_field in self.pii_fields_sorted:
            # Skip non-alphanumeric PII (emails, phone numbers) - partial matching less useful
            if not pii_field.value.replace(' ', '').isalnum():
                continue

            # Skip if value is too short for partial matching
            if len(pii_field.value) < pii_field.min_partial_length:
                continue

            pattern = re.escape(pii_field.value)

            for m in re.finditer(pattern, text, flags):
                start, end = m.start(), m.end()

                # Check characters around the match
                char_before = text[start - 1] if start > 0 else ''
                char_after = text[end] if end < len(text) else ''

                # This is a partial match if it's connected to other alphanumeric chars
                has_alnum_before = char_before.isalnum() or char_before == '_'
                has_alnum_after = char_after.isalnum() or char_after == '_'

                if not (has_alnum_before or has_alnum_after):
                    # This is a standalone match, not partial
                    continue

                # Skip if this overlaps with an exact match
                overlaps_exact = False
                for ex_start, ex_end in exact_ranges:
                    if not (end <= ex_start or start >= ex_end):
                        overlaps_exact = True
                        break
                if overlaps_exact:
                    continue

                # Find the full token containing this match
                # Expand left
                token_start = start
                while token_start > 0 and (text[token_start - 1].isalnum() or text[token_start - 1] == '_'):
                    token_start -= 1

                # Expand right
                token_end = end
                while token_end < len(text) and (text[token_end].isalnum() or text[token_end] == '_'):
                    token_end += 1

                full_token = text[token_start:token_end]

                matches.append(Match(
                    pii_field=pii_field,
                    start=token_start,
                    end=token_end,
                    matched_text=full_token,
                    is_exact=False
                ))

        # Remove duplicates (same position, different PII fields - keep first)
        seen = set()
        unique_matches = []
        for m in matches:
            key = (m.start, m.end, m.matched_text)
            if key not in seen:
                seen.add(key)
                unique_matches.append(m)

        return unique_matches

    def add_line_context(self, text: str, matches: list[Match], context_lines: int = 2) -> None:
        """Add line number and surrounding context to matches."""
        lines = text.splitlines(keepends=True)

        # Build position-to-line mapping
        line_starts = []
        pos = 0
        for line in lines:
            line_starts.append(pos)
            pos += len(line)

        def get_line_number(position: int) -> int:
            """Get 1-indexed line number for a position."""
            for i, start in enumerate(line_starts):
                if i + 1 < len(line_starts):
                    if start <= position < line_starts[i + 1]:
                        return i + 1
                else:
                    if start <= position:
                        return i + 1
            return len(lines)

        for match in matches:
            line_num = get_line_number(match.start)
            match.line_number = line_num

            # Get the line text (strip newline)
            if 0 < line_num <= len(lines):
                match.line_text = lines[line_num - 1].rstrip('\n\r')

            # Get context before
            start_ctx = max(0, line_num - 1 - context_lines)
            match.context_before = [
                lines[i].rstrip('\n\r')
                for i in range(start_ctx, line_num - 1)
            ]

            # Get context after
            end_ctx = min(len(lines), line_num + context_lines)
            match.context_after = [
                lines[i].rstrip('\n\r')
                for i in range(line_num, end_ctx)
            ]


def apply_replacement(text: str, match: Match, preserve_case: bool = True) -> str:
    """
    Apply a single replacement to text.
    If preserve_case is True, tries to match the case pattern of the original.
    """
    original = match.matched_text
    replacement = match.pii_field.replacement

    if preserve_case and not match.is_exact:
        # For partial matches, we need to handle the surrounding text
        # Find where the PII value starts within the matched text
        pii_value = match.pii_field.value
        idx = original.lower().find(pii_value.lower())
        if idx >= 0:
            # Replace only the PII part, preserving surrounding text
            before = original[:idx]
            after = original[idx + len(pii_value):]
            matched_pii = original[idx:idx + len(pii_value)]

            # Apply case preservation to replacement
            case_adjusted = _adjust_case(replacement, matched_pii)
            replacement = before + case_adjusted + after
    elif preserve_case:
        replacement = _adjust_case(replacement, original)

    return text[:match.start] + replacement + text[match.end:]


def _adjust_case(replacement: str, original: str) -> str:
    """Adjust the case of replacement to match original's pattern."""
    if original.isupper():
        return replacement.upper()
    elif original.islower():
        return replacement.lower()
    elif original.istitle() or (original and original[0].isupper()):
        return replacement.capitalize()
    else:
        return replacement
