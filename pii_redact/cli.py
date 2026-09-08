#!/usr/bin/env python3
"""
PII Redaction Tool - Command line tool for redacting personally identifiable information.

Usage:
    pii-redact input.log
    pii-redact *.log *.txt
    pii-redact "logs/**/*.log"
    pii-redact input.log --output redacted.log
    pii-redact input.log --dry-run
    pii-redact input.log --no-interactive
"""

import argparse
import sys
from glob import glob
from pathlib import Path

from .config import Config, DEFAULT_CONFIG_PATH
from .redactor import Redactor
from .reporters import Report, ConsoleReporter


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        prog='pii-redact',
        description='Redact personally identifiable information from files.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s input.log
      Redact PII from input.log, output to input_redacted.log

  %(prog)s *.log *.txt
      Redact PII from all .log and .txt files in current directory

  %(prog)s "logs/**/*.log"
      Redact PII from all .log files in logs/ directory recursively

  %(prog)s input.log --output redacted.log
      Redact PII and save to specific output file

  %(prog)s input.log --dry-run
      Show what would be changed without modifying files

  %(prog)s input.log --no-interactive
      Skip prompts for probable matches (exact matches only)

  %(prog)s input.eml --strict
      Also fail if any part of the input could not be read as text

Exit codes:
  0   Every output verified clean
  1   Could not start: bad arguments, or missing/invalid config
  2   VERIFICATION FAILED - configured PII is still recoverable from an
      output file. Do not share it.
  3   One or more files could not be processed
  4   Content could not be inspected (--strict only); nothing was proven
      about the parts that could not be read
"""
    )

    parser.add_argument(
        'input',
        nargs='+',
        help='Input file(s) or glob pattern(s) (e.g., *.log "logs/**/*.log")'
    )

    parser.add_argument(
        '-c', '--config',
        default=str(DEFAULT_CONFIG_PATH),
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
        help='Skip interactive prompts for probable matches (same as --partial none)'
    )

    parser.add_argument(
        '--partial',
        choices=['all', 'none', 'ask'],
        default=None,
        help='How to handle probable/partial matches: all (replace all), none (skip all), ask (prompt interactively, default)'
    )

    parser.add_argument(
        '--no-color',
        action='store_true',
        help='Disable colored output'
    )

    parser.add_argument(
        '--no-verify',
        action='store_true',
        help='Skip the post-redaction verification pass (not recommended: verification is '
             'what catches PII hidden inside encoded content such as base64 or quoted-printable)'
    )

    parser.add_argument(
        '--strict',
        action='store_true',
        help='Also exit non-zero when part of an input could not be inspected '
             '(binary or compressed content), not only when PII is found to survive'
    )

    parser.add_argument(
        '--context-lines',
        type=int,
        default=2,
        help='Number of context lines to show around matches (default: 2)'
    )

    parser.add_argument(
        '--report',
        nargs='?',
        const='auto',
        default=None,
        help='Save JSON report file. Optionally specify path (default: <first_output>_report.json)'
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
    # Handle 'init' subcommand
    if len(sys.argv) > 1 and sys.argv[1] == 'init':
        from .config_generator import run_init
        run_init(sys.argv[2:])
        return

    args = parse_args()

    # Initialize reporter
    reporter = ConsoleReporter(use_color=not args.no_color)

    # Load config
    config_path = Path(args.config)
    try:
        config = Config.from_yaml(config_path)
    except FileNotFoundError:
        reporter.print_error(f"Config file not found: {config_path}")
        sys.exit(1)
    except Exception as e:
        reporter.print_error(f"Failed to load config: {e}")
        sys.exit(1)

    # Validate config and show warnings
    warnings = config.validate()
    for warning in warnings:
        reporter.print_warning(warning)

    # Expand input patterns
    input_files = []
    for pattern in args.input:
        input_files.extend(expand_glob(pattern))
    # Deduplicate while preserving order
    seen = set()
    input_files = [f for f in input_files if not (f in seen or seen.add(f))]

    # Validate output option
    if args.output and len(input_files) > 1:
        reporter.print_error("--output can only be used with a single input file")
        sys.exit(1)

    # Determine partial match mode: --partial takes precedence over --no-interactive
    if args.partial:
        partial_mode = args.partial
    elif args.no_interactive:
        partial_mode = 'none'
    else:
        partial_mode = 'ask'

    # Initialize redactor
    redactor = Redactor(
        config=config,
        dry_run=args.dry_run,
        partial_mode=partial_mode,
        context_lines=args.context_lines,
        reporter=reporter,
        verify=not args.no_verify
    )

    # Initialize report
    report = Report(config_file=str(config_path))

    reporter.print_header(f"PII Redaction Tool {'(DRY RUN)' if args.dry_run else ''}")
    print(f"Config: {config_path}")
    print(f"Files to process: {len(input_files)}")
    print(f"PII fields configured: {len(config.pii_fields)}")

    # Process each file
    failed_files = 0
    for input_path in input_files:
        try:
            output_path = Path(args.output) if args.output else None
            stats = redactor.process_file(input_path, output_path)
            report.add_file_stats(stats)
        except Exception as e:
            reporter.print_error(f"Failed to process {input_path}: {e}")
            failed_files += 1
            continue

    # Complete report
    report.complete()

    # Print summary
    reporter.print_final_summary(report)

    if args.dry_run:
        reporter.print_dry_run_notice()

    # Save report (only when --report flag is passed)
    if not args.dry_run and args.report:
        if args.report != 'auto':
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

    sys.exit(_exit_code(report, failed_files, strict=args.strict))


def _exit_code(report: Report, failed_files: int, strict: bool) -> int:
    """Decide the process exit status, worst outcome first.

    Surviving PII outranks everything else: it is the one result where acting
    on a successful-looking run does real damage. A file that could not be
    processed at all comes next, since it silently produced no output. Content
    that could not be inspected is advisory by default -- most files carry some
    opaque blob, and a code that fires on every run is a code nobody checks --
    so it only fails the run under --strict.
    """
    if report.files_with_leaks:
        return 2
    if failed_files:
        return 3
    if strict and report.files_uninspected:
        return 4
    return 0


if __name__ == '__main__':
    main()
