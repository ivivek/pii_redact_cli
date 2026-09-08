"""
Statistics tracking and report generation.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .matchers import Match
from .verifier import VerificationResult


@dataclass
class FileStats:
    """Statistics for a single file."""
    file_path: str
    output_path: str
    exact_matches: dict[str, int] = field(default_factory=dict)  # field_name -> count
    partial_matches: dict[str, int] = field(default_factory=dict)  # field_name -> count
    partial_replaced: dict[str, int] = field(default_factory=dict)  # field_name -> count replaced
    partial_skipped: dict[str, int] = field(default_factory=dict)  # field_name -> count skipped
    verification: VerificationResult = None  # None when verification was skipped

    @property
    def leaks(self) -> list:
        """Configured values still recoverable from the output."""
        return self.verification.leaks if self.verification else []

    @property
    def uninspected(self) -> list:
        """Regions of the file that could not be searched at all."""
        return self.verification.uninspected if self.verification else []

    @property
    def total_exact(self) -> int:
        return sum(self.exact_matches.values())

    @property
    def total_partial_found(self) -> int:
        return sum(self.partial_matches.values())

    @property
    def total_partial_replaced(self) -> int:
        return sum(self.partial_replaced.values())

    @property
    def total_partial_skipped(self) -> int:
        return sum(self.partial_skipped.values())

    @property
    def total_replacements(self) -> int:
        return self.total_exact + self.total_partial_replaced

    def add_exact_match(self, field_name: str) -> None:
        self.exact_matches[field_name] = self.exact_matches.get(field_name, 0) + 1

    def add_partial_match(self, field_name: str) -> None:
        self.partial_matches[field_name] = self.partial_matches.get(field_name, 0) + 1

    def add_partial_replaced(self, field_name: str) -> None:
        self.partial_replaced[field_name] = self.partial_replaced.get(field_name, 0) + 1

    def add_partial_skipped(self, field_name: str) -> None:
        self.partial_skipped[field_name] = self.partial_skipped.get(field_name, 0) + 1


@dataclass
class Report:
    """Complete report for a redaction run."""
    files: list[FileStats] = field(default_factory=list)
    started_at: str = ""
    completed_at: str = ""
    config_file: str = ""

    def __post_init__(self):
        if not self.started_at:
            self.started_at = datetime.now().isoformat()

    def add_file_stats(self, stats: FileStats) -> None:
        self.files.append(stats)

    def complete(self) -> None:
        self.completed_at = datetime.now().isoformat()

    @property
    def total_files(self) -> int:
        return len(self.files)

    @property
    def total_exact_replacements(self) -> int:
        return sum(f.total_exact for f in self.files)

    @property
    def total_partial_replaced(self) -> int:
        return sum(f.total_partial_replaced for f in self.files)

    @property
    def total_partial_skipped(self) -> int:
        return sum(f.total_partial_skipped for f in self.files)

    @property
    def total_replacements(self) -> int:
        return self.total_exact_replacements + self.total_partial_replaced

    @property
    def files_with_leaks(self) -> list[FileStats]:
        """Outputs from which a configured value can still be recovered."""
        return [f for f in self.files if f.leaks]

    @property
    def files_uninspected(self) -> list[FileStats]:
        """Files containing content that could not be searched."""
        return [f for f in self.files if f.uninspected]

    def to_dict(self) -> dict[str, Any]:
        """Convert report to dictionary for JSON serialization."""
        return {
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "config_file": self.config_file,
            "summary": {
                "total_files": self.total_files,
                "total_exact_replacements": self.total_exact_replacements,
                "total_partial_replaced": self.total_partial_replaced,
                "total_partial_skipped": self.total_partial_skipped,
                "total_replacements": self.total_replacements,
                "files_with_leaks": len(self.files_with_leaks),
                "files_with_uninspected_content": len(self.files_uninspected)
            },
            "files": [
                {
                    "input_file": f.file_path,
                    "output_file": f.output_path,
                    "exact_matches": f.exact_matches,
                    "partial_matches": f.partial_matches,
                    "partial_replaced": f.partial_replaced,
                    "partial_skipped": f.partial_skipped,
                    "totals": {
                        "exact": f.total_exact,
                        "partial_found": f.total_partial_found,
                        "partial_replaced": f.total_partial_replaced,
                        "partial_skipped": f.total_partial_skipped,
                        "total_replacements": f.total_replacements
                    },
                    "verification": self._verification_dict(f)
                }
                for f in self.files
            ]
        }

    @staticmethod
    def _verification_dict(stats: FileStats) -> dict[str, Any]:
        """Serialize one file's verification outcome, or record that it was skipped."""
        if stats.verification is None:
            return {"ran": False}

        return {
            "ran": True,
            "passed": stats.verification.passed,
            "complete": stats.verification.complete,
            "views_checked": stats.verification.views_checked,
            "leaks": [
                {
                    "field": leak.field_name,
                    "encoding": leak.encoding_path,
                    "occurrences": leak.count
                }
                for leak in stats.leaks
            ],
            "uninspected": [
                {
                    "reason": region.reason,
                    "encoding": region.encoding_path,
                    "bytes": region.byte_length
                }
                for region in stats.uninspected
            ]
        }

    def save(self, path: Path) -> None:
        """Save report to JSON file."""
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)


class ConsoleReporter:
    """Prints formatted output to console."""

    # ANSI color codes
    RESET = "\033[0m"
    BOLD = "\033[1m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    CYAN = "\033[36m"
    RED = "\033[31m"
    DIM = "\033[2m"

    def __init__(self, use_color: bool = True):
        self.use_color = use_color

    def _c(self, text: str, color: str) -> str:
        """Apply color if enabled."""
        if self.use_color:
            return f"{color}{text}{self.RESET}"
        return text

    def print_header(self, text: str) -> None:
        print(f"\n{self._c(text, self.BOLD + self.BLUE)}")
        print("=" * len(text))

    def print_file_start(self, file_path: str) -> None:
        print(f"\n{self._c('Processing:', self.BOLD)} {file_path}")

    def print_exact_matches(self, stats: FileStats) -> None:
        if not stats.exact_matches:
            print(f"  {self._c('No exact matches found', self.DIM)}")
            return

        print(f"\n  {self._c('Exact matches found and replaced:', self.GREEN)}")
        for field_name, count in stats.exact_matches.items():
            print(f"    - {field_name}: {count} occurrence(s)")

    def print_partial_match(self, index: int, match: Match) -> None:
        """Print a single partial match with context."""
        print(f"\n  {self._c(f'[{index}]', self.YELLOW)} \"{self._c(match.matched_text, self.RED)}\" "
              f"contains \"{match.pii_field.value}\" (line {match.line_number})")

        # Print context before
        line_num = match.line_number - len(match.context_before)
        for line in match.context_before:
            print(f"      {self._c(str(line_num).rjust(4), self.DIM)}: {line}")
            line_num += 1

        # Print the matching line with highlight
        highlighted_line = match.line_text.replace(
            match.matched_text,
            self._c(match.matched_text, self.RED + self.BOLD)
        )
        print(f"    {self._c('>', self.YELLOW)} {self._c(str(match.line_number).rjust(4), self.DIM)}: {highlighted_line}")

        # Print context after
        line_num = match.line_number + 1
        for line in match.context_after:
            print(f"      {self._c(str(line_num).rjust(4), self.DIM)}: {line}")
            line_num += 1

    def print_partial_summary(self, total: int) -> None:
        if total == 0:
            print(f"\n  {self._c('No probable matches found', self.DIM)}")
        else:
            print(f"\n  {self._c(f'Found {total} probable match(es)', self.YELLOW)}")

    def print_file_complete(self, stats: FileStats) -> None:
        print(f"\n  {self._c('Output:', self.GREEN)} {stats.output_path}")
        print(f"  {self._c('Replacements:', self.CYAN)} {stats.total_replacements} "
              f"(exact: {stats.total_exact}, partial: {stats.total_partial_replaced})")

    def print_verification(self, stats: FileStats) -> None:
        """Report what the verification pass could and could not confirm.

        Field names are printed but values never are: the point of the run is
        to stop these strings travelling, and a console log is somewhere they
        travel. The config key is enough to identify which entry leaked.
        """
        if stats.verification is None:
            print(f"  {self._c('Verification: skipped (--no-verify)', self.YELLOW)}")
            return

        for region in stats.uninspected:
            self.print_warning(
                f"not inspected ({region.encoding_path}, {region.byte_length} bytes): {region.reason}"
            )

        if stats.leaks:
            print(f"\n  {self._c('VERIFICATION FAILED - configured PII survives in the output:', self.RED + self.BOLD)}")
            for leak in stats.leaks:
                where = (
                    "in the output text"
                    if leak.is_plaintext
                    else f"after decoding: {leak.encoding_path}"
                )
                print(f"    - {leak.field_name}: {leak.count} occurrence(s) {where}")
            print(f"  {self._c('Do not share this file.', self.RED + self.BOLD)}")
            return

        if stats.uninspected:
            print(f"  {self._c('Verification: no PII recoverable from the parts that could be read', self.YELLOW)}")
        else:
            print(f"  {self._c('Verification: passed', self.GREEN)}")

    def print_final_summary(self, report: Report) -> None:
        self.print_header("Summary")
        print(f"  Files processed: {report.total_files}")
        print(f"  Total exact replacements: {report.total_exact_replacements}")
        print(f"  Total probable replacements: {report.total_partial_replaced}")
        print(f"  Total probable skipped: {report.total_partial_skipped}")
        print(f"  {self._c(f'Total replacements: {report.total_replacements}', self.BOLD)}")

        leaked = report.files_with_leaks
        uninspected = report.files_uninspected

        if leaked:
            print()
            print(f"  {self._c(f'Verification FAILED for {len(leaked)} file(s):', self.RED + self.BOLD)}")
            for stats in leaked:
                print(f"    - {stats.output_path}")
        if uninspected:
            print()
            print(f"  {self._c(f'Content not inspected in {len(uninspected)} file(s):', self.YELLOW)}")
            for stats in uninspected:
                print(f"    - {stats.file_path}")
            print(f"  {self._c('A clean result covers only the parts that could be read as text.', self.DIM)}")

    def print_dry_run_notice(self) -> None:
        print(f"\n{self._c('DRY RUN - No files were modified', self.YELLOW + self.BOLD)}")

    def print_error(self, message: str) -> None:
        print(f"{self._c('Error:', self.RED + self.BOLD)} {message}")

    def print_warning(self, message: str) -> None:
        print(f"{self._c('Warning:', self.YELLOW)} {message}")
