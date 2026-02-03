"""
Core redaction engine.
"""

import re
from pathlib import Path
from typing import Callable

from config import Config, PIIField
from matchers import Match, Matcher, apply_replacement
from reporters import FileStats, Report, ConsoleReporter
from file_handlers.text_handler import TextHandler
from file_handlers.structured_handler import JSONHandler, YAMLHandler, StructuredHandler


class Redactor:
    """Main redaction engine that coordinates the redaction process."""

    def __init__(
        self,
        config: Config,
        dry_run: bool = False,
        interactive: bool = True,
        context_lines: int = 2,
        reporter: ConsoleReporter = None
    ):
        self.config = config
        self.dry_run = dry_run
        self.interactive = interactive
        self.context_lines = context_lines
        self.reporter = reporter or ConsoleReporter()
        self.matcher = Matcher(config.pii_fields, config.case_sensitive)

    def process_file(self, input_path: Path, output_path: Path = None) -> FileStats:
        """Process a single file and return statistics."""
        # Determine handler and output path
        if JSONHandler.can_handle(input_path):
            return self._process_structured_file(input_path, output_path, JSONHandler)
        elif YAMLHandler.can_handle(input_path):
            return self._process_structured_file(input_path, output_path, YAMLHandler)
        else:
            return self._process_text_file(input_path, output_path)

    def _process_text_file(self, input_path: Path, output_path: Path = None) -> FileStats:
        """Process a plain text file."""
        if output_path is None:
            output_path = TextHandler.get_output_path(input_path)

        stats = FileStats(
            file_path=str(input_path),
            output_path=str(output_path)
        )

        self.reporter.print_file_start(str(input_path))

        # Read file
        text = TextHandler.read(input_path)

        # Find exact matches
        exact_matches = self.matcher.find_exact_matches(text)
        self.matcher.add_line_context(text, exact_matches, self.context_lines)

        # Track stats for exact matches
        for match in exact_matches:
            stats.add_exact_match(match.pii_field.name)

        # Apply exact replacements (process from end to start to preserve positions)
        exact_matches_sorted = sorted(exact_matches, key=lambda m: m.start, reverse=True)
        for match in exact_matches_sorted:
            text = apply_replacement(text, match, preserve_case=True)

        self.reporter.print_exact_matches(stats)

        # Find partial matches (on already-redacted text, but using original positions)
        # Re-read and find partials on original text
        original_text = TextHandler.read(input_path)
        partial_matches = self.matcher.find_partial_matches(original_text, exact_matches)
        self.matcher.add_line_context(original_text, partial_matches, self.context_lines)

        # Track stats for partial matches
        for match in partial_matches:
            stats.add_partial_match(match.pii_field.name)

        self.reporter.print_partial_summary(len(partial_matches))

        # Handle partial matches
        if partial_matches and self.interactive:
            selected_indices = self._prompt_partial_matches(partial_matches)

            # Apply selected partial replacements
            # Need to recalculate positions after exact matches were applied
            # For simplicity, we'll do a second pass on the text
            for i, match in enumerate(partial_matches):
                if i in selected_indices:
                    stats.add_partial_replaced(match.pii_field.name)
                    # Replace in the current text using the matched_text
                    text = self._replace_partial(text, match)
                else:
                    stats.add_partial_skipped(match.pii_field.name)
        elif partial_matches:
            # Non-interactive mode: skip all partial matches
            for match in partial_matches:
                stats.add_partial_skipped(match.pii_field.name)

        # Write output
        if not self.dry_run:
            TextHandler.write(output_path, text)

        self.reporter.print_file_complete(stats)
        return stats

    def _process_structured_file(self, input_path: Path, output_path: Path, handler_class) -> FileStats:
        """Process a structured (JSON/YAML) file."""
        if output_path is None:
            output_path = handler_class.get_output_path(input_path)

        stats = FileStats(
            file_path=str(input_path),
            output_path=str(output_path)
        )

        self.reporter.print_file_start(str(input_path))

        # Read file
        raw_text, data = handler_class.read(input_path)

        # Create a redaction function that tracks stats
        def redact_string(s: str) -> str:
            result = s

            # Find and apply exact matches
            exact_matches = self.matcher.find_exact_matches(result)
            for match in exact_matches:
                stats.add_exact_match(match.pii_field.name)

            # Apply exact replacements (from end to start)
            exact_matches_sorted = sorted(exact_matches, key=lambda m: m.start, reverse=True)
            for match in exact_matches_sorted:
                result = apply_replacement(result, match, preserve_case=True)

            return result

        # Redact the structure
        redacted_data = StructuredHandler.redact_structure(data, redact_string)

        self.reporter.print_exact_matches(stats)

        # For structured files, we handle partial matches on the raw text
        partial_matches = self.matcher.find_partial_matches(raw_text)
        self.matcher.add_line_context(raw_text, partial_matches, self.context_lines)

        for match in partial_matches:
            stats.add_partial_match(match.pii_field.name)

        self.reporter.print_partial_summary(len(partial_matches))

        if partial_matches and self.interactive:
            selected_indices = self._prompt_partial_matches(partial_matches)

            # For selected partial matches, we need to do another pass
            def redact_partial(s: str) -> str:
                result = s
                for i, match in enumerate(partial_matches):
                    if i in selected_indices:
                        # Check if this match is in this string
                        if match.matched_text in result or match.matched_text.lower() in result.lower():
                            result = self._replace_partial(result, match)
                return result

            # Re-process with partial replacements
            redacted_data = StructuredHandler.redact_structure(redacted_data, redact_partial)

            for i, match in enumerate(partial_matches):
                if i in selected_indices:
                    stats.add_partial_replaced(match.pii_field.name)
                else:
                    stats.add_partial_skipped(match.pii_field.name)
        elif partial_matches:
            for match in partial_matches:
                stats.add_partial_skipped(match.pii_field.name)

        # Write output
        if not self.dry_run:
            handler_class.write(output_path, redacted_data)

        self.reporter.print_file_complete(stats)
        return stats

    def _replace_partial(self, text: str, match: Match) -> str:
        """Replace a partial match in text, preserving case."""
        pii_value = match.pii_field.value
        replacement = match.pii_field.replacement
        matched_text = match.matched_text

        # Find where the PII value is within the matched text
        flags = 0 if self.config.case_sensitive else re.IGNORECASE
        pattern = re.escape(pii_value)

        def replace_preserving_case(m):
            original = m.group()
            if original.isupper():
                return replacement.upper()
            elif original.islower():
                return replacement.lower()
            elif original[0].isupper():
                return replacement.capitalize()
            return replacement

        # Replace the PII value within the matched text
        new_matched = re.sub(pattern, replace_preserving_case, matched_text, flags=flags)

        # Now replace the matched_text with new_matched in the full text
        return text.replace(matched_text, new_matched)

    def _prompt_partial_matches(self, matches: list[Match]) -> set[int]:
        """Prompt user to select which partial matches to replace."""
        print(f"\n  Probable matches found (partial):")

        for i, match in enumerate(matches):
            self.reporter.print_partial_match(i + 1, match)

        print()
        while True:
            response = input("  Replace probable matches? [a]ll / [n]one / [s]elect: ").strip().lower()

            if response == 'a' or response == 'all':
                return set(range(len(matches)))
            elif response == 'n' or response == 'none':
                return set()
            elif response == 's' or response == 'select':
                selection = input("  Select matches to replace (comma-separated, e.g., 1,3,5): ").strip()
                try:
                    # Parse selection (1-indexed in prompt, convert to 0-indexed)
                    indices = set()
                    for part in selection.split(','):
                        part = part.strip()
                        if '-' in part:
                            # Range like 1-5
                            start, end = part.split('-')
                            indices.update(range(int(start) - 1, int(end)))
                        else:
                            indices.add(int(part) - 1)

                    # Validate indices
                    valid_indices = {i for i in indices if 0 <= i < len(matches)}
                    return valid_indices
                except ValueError:
                    print("  Invalid selection. Please enter numbers separated by commas.")
            else:
                print("  Invalid option. Please enter 'a', 'n', or 's'.")
