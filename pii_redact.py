#!/usr/bin/env python3
"""
PII Redaction Tool - Command line tool for redacting personally identifiable information.

Usage:
    pii_redact input.log
    pii_redact input.log --config my_pii.yaml
    pii_redact "logs/**/*.log" --config my_pii.yaml
    pii_redact input.log --config my_pii.yaml --output redacted.log
    pii_redact input.log --config my_pii.yaml --dry-run
    pii_redact input.log --config my_pii.yaml --no-interactive

Default config location: ~/.config/pii_redact/config.yaml
"""

import argparse
import sys
from glob import glob
from pathlib import Path

from config import Config

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "pii_redact" / "config.yaml"
from redactor import Redactor
from reporters import Report, ConsoleReporter


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        prog='pii_redact',
        description='Redact personally identifiable information from files.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Examples:
  %(prog)s input.log
      Redact PII using default config ({DEFAULT_CONFIG_PATH})

  %(prog)s input.log --config my_pii.yaml
      Redact PII from input.log using specified config

  %(prog)s "logs/**/*.log"
      Redact PII from all .log files in logs/ directory recursively

  %(prog)s input.log --dry-run
      Show what would be changed without modifying files

  %(prog)s input.log --no-interactive
      Skip prompts for probable matches (exact matches only)
"""
    )

    parser.add_argument(
        'input',
        help='Input file or glob pattern (e.g., "logs/**/*.log")'
    )

    parser.add_argument(
        '-c', '--config',
        help=f'Path to YAML config file with PII values and replacements (default: {DEFAULT_CONFIG_PATH})'
    )

    parser.add_argument(
        '-o', '--output',
        help='Output file path (only valid for single file input)'
    )

    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be changed without modifying files'
    )

    parser.add_argument(
        '--no-interactive',
        action='store_true',
        help='Skip interactive prompts for probable matches'
    )

    parser.add_argument(
        '--no-color',
        action='store_true',
        help='Disable colored output'
    )

    parser.add_argument(
        '--context-lines',
        type=int,
        default=2,
        help='Number of context lines to show around matches (default: 2)'
    )

    parser.add_argument(
        '--report',
        help='Path to save JSON report file (default: <first_output>_report.json)'
    )

    return parser.parse_args()


def expand_glob(pattern: str) -> list[Path]:
    """Expand glob pattern to list of file paths."""
    # Check if it's a glob pattern or single file
    if '*' in pattern or '?' in pattern or '[' in pattern:
        # Use recursive glob
        matches = glob(pattern, recursive=True)
        files = [Path(m) for m in matches if Path(m).is_file()]
    else:
        # Single file
        path = Path(pattern)
        if path.is_file():
            files = [path]
        elif path.is_dir():
            print(f"Error: '{pattern}' is a directory. Use a glob pattern like '{pattern}/**/*'")
            sys.exit(1)
        else:
            print(f"Error: File not found: {pattern}")
            sys.exit(1)

    if not files:
        print(f"Error: No files matched pattern: {pattern}")
        sys.exit(1)

    return sorted(files)


def main():
    """Main entry point."""
    args = parse_args()

    # Initialize reporter
    reporter = ConsoleReporter(use_color=not args.no_color)

    # Determine config path
    if args.config:
        config_path = Path(args.config)
    else:
        config_path = DEFAULT_CONFIG_PATH

    # Load config
    try:
        config = Config.from_yaml(config_path)
    except FileNotFoundError:
        reporter.print_error(f"Config file not found: {config_path}")
        if config_path == DEFAULT_CONFIG_PATH:
            reporter.print_error(f"Create a config file at {DEFAULT_CONFIG_PATH} or specify one with --config")
        sys.exit(1)
    except Exception as e:
        reporter.print_error(f"Failed to load config: {e}")
        sys.exit(1)

    # Validate config and show warnings
    warnings = config.validate()
    for warning in warnings:
        reporter.print_warning(warning)

    # Expand input pattern
    input_files = expand_glob(args.input)

    # Validate output option
    if args.output and len(input_files) > 1:
        reporter.print_error("--output can only be used with a single input file")
        sys.exit(1)

    # Initialize redactor
    redactor = Redactor(
        config=config,
        dry_run=args.dry_run,
        interactive=not args.no_interactive,
        context_lines=args.context_lines,
        reporter=reporter
    )

    # Initialize report
    report = Report(config_file=str(config_path))

    reporter.print_header(f"PII Redaction Tool {'(DRY RUN)' if args.dry_run else ''}")
    print(f"Config: {config_path}")
    print(f"Files to process: {len(input_files)}")
    print(f"PII fields configured: {len(config.pii_fields)}")

    # Process each file
    for input_path in input_files:
        try:
            output_path = Path(args.output) if args.output else None
            stats = redactor.process_file(input_path, output_path)
            report.add_file_stats(stats)
        except Exception as e:
            reporter.print_error(f"Failed to process {input_path}: {e}")
            continue

    # Complete report
    report.complete()

    # Print summary
    reporter.print_final_summary(report)

    if args.dry_run:
        reporter.print_dry_run_notice()

    # Save report
    if not args.dry_run:
        if args.report:
            report_path = Path(args.report)
        elif report.files:
            # Default: save next to first output file
            first_output = Path(report.files[0].output_path)
            report_path = first_output.parent / f"{first_output.stem}_report.json"
        else:
            report_path = None

        if report_path:
            report.save(report_path)
            print(f"\nReport saved: {report_path}")


if __name__ == '__main__':
    main()
