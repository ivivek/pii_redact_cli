"""
Post-redaction verification.

Exact matching runs against a file's literal bytes, so any encoding layer
between those bytes and the text a human (or an LLM, or a support engineer)
will eventually read hides PII from the matcher: base64 and quoted-printable
MIME parts, percent-encoded request logs, HTML entities, gzipped payloads. The
run then reports a replacement count and a grep of the output finds nothing,
which is worse than failing loudly -- the obvious sanity check confirms a false
clean.

This module closes that hole from the other end. Instead of trying to enumerate
every container the redactor might be handed, it takes the redacted output,
decodes it every way it knows how, and re-runs exact matching over each decoded
view. A configured value recoverable from the output is reported as a leak
whatever encoding hid it, including encodings no file handler was ever written
for.

Detection and warning are deliberately calibrated differently:

- Leak detection is aggressive. Decoding something that was not really encoded
  yields garbage, and a configured PII value does not appear in garbage, so a
  speculative decode costs nothing but a wasted scan.
- "Could not inspect" warnings are conservative, and only fire on strong
  evidence (a MIME-shaped base64 block, a recognised binary signature, a binary
  input file). A warning that cries wolf gets ignored, and an ignored warning
  is the silent failure all over again.

Regions that decode to something that is not text -- compressed archives,
binary attachments -- cannot be checked by matching at all. Those are reported
as uninspected so that "nothing found" never quietly stands in for "nothing
looked".
"""

import base64
import binascii
import gzip
import html
import quopri
import re
import zlib
from dataclasses import dataclass, field
from urllib.parse import unquote, unquote_plus

from .matchers import Matcher


# How many times a decoded view may itself be decoded again. Two levels covers
# the shapes seen in practice (base64 of gzip, base64 of percent-encoded form
# data); more mostly buys permutations of garbage.
MAX_DEPTH = 3

# Ceilings so a pathological input cannot turn verification into the expensive
# part of the run. Both are far above any realistic log or mail file.
MAX_VIEWS = 500
MAX_TOTAL_DECODED_BYTES = 32 * 1024 * 1024

# Shortest base64 run worth decoding. Below this, false candidates outnumber
# real ones and the payload is too small to hold a PII value anyway.
MIN_B64_LEN = 24

# A wrapped base64 body (MIME, PEM) is a run of lines that are nothing but
# base64 characters. Requiring a decent line length keeps ordinary prose and
# single-word lines out.
MIN_B64_LINE = 40

# Smallest decoded payload an inline (unwrapped) base64 token may have before
# it is allowed to raise an uninspected-content warning. Real embedded binaries
# are kilobytes; a short random token that happens to hit a magic number is not.
MIN_WEAK_BINARY_BYTES = 512

# Leading bytes that identify a container we cannot search as text.
_BINARY_SIGNATURES = [
    (b'\x1f\x8b', 'gzip stream'),
    (b'PK\x03\x04', 'zip archive (docx/xlsx/odt are zip containers)'),
    (b'%PDF-', 'PDF document'),
    (b'\x89PNG', 'PNG image'),
    (b'\xff\xd8\xff', 'JPEG image'),
    (b'GIF8', 'GIF image'),
    (b'\x25\x21PS', 'PostScript document'),
    (b'\xd0\xcf\x11\xe0', 'legacy Office document'),
]


@dataclass
class Leak:
    """A configured PII value still recoverable from the redacted output."""

    field_name: str
    encoding_path: str  # how the value had to be decoded to be found, e.g. "base64 -> gzip"
    count: int

    @property
    def is_plaintext(self) -> bool:
        """True when the value survived in the output's literal text."""
        return self.encoding_path == 'raw'


@dataclass
class UninspectedRegion:
    """Content that could not be searched, so nothing can be claimed about it."""

    reason: str
    encoding_path: str
    byte_length: int


@dataclass
class VerificationResult:
    """Outcome of verifying one redacted output."""

    leaks: list[Leak] = field(default_factory=list)
    uninspected: list[UninspectedRegion] = field(default_factory=list)
    views_checked: int = 0

    @property
    def passed(self) -> bool:
        """True when no configured value is recoverable from the output."""
        return not self.leaks

    @property
    def complete(self) -> bool:
        """True when every part of the output could actually be searched."""
        return not self.uninspected

    @property
    def total_leaked_occurrences(self) -> int:
        return sum(leak.count for leak in self.leaks)


class Verifier:
    """Re-checks a redacted output through every decoding it can apply."""

    def __init__(self, matcher: Matcher, max_depth: int = MAX_DEPTH):
        self.matcher = matcher
        self.max_depth = max_depth

    def verify_text(self, text: str) -> VerificationResult:
        """Search the redacted text, and every decoding of it, for configured PII."""
        result = VerificationResult()

        # Views already scanned, keyed by content, so that decoders that are
        # near no-ops on a given input do not multiply the work.
        seen: set[str] = {text}
        queue: list[tuple[str, str, int]] = [(text, 'raw', 0)]
        decoded_budget = MAX_TOTAL_DECODED_BYTES

        while queue and result.views_checked < MAX_VIEWS:
            view, path, depth = queue.pop(0)
            result.views_checked += 1

            self._scan_for_leaks(view, path, result)

            if depth >= self.max_depth or decoded_budget <= 0:
                continue

            for name, decoded in self._decodings_of(view, path, result):
                if decoded in seen:
                    continue
                decoded_budget -= len(decoded)
                if decoded_budget <= 0:
                    break
                seen.add(decoded)
                queue.append((decoded, _extend(path, name), depth + 1))

        result.leaks = _consolidate(result.leaks)
        result.uninspected = _dedupe_regions(result.uninspected)
        return result

    def _scan_for_leaks(self, view: str, path: str, result: VerificationResult) -> None:
        """Record any configured value that exact-matches inside this view."""
        counts: dict[str, int] = {}
        for match in self.matcher.find_exact_matches(view):
            name = match.pii_field.name
            counts[name] = counts.get(name, 0) + 1

        for name, count in counts.items():
            result.leaks.append(Leak(field_name=name, encoding_path=path, count=count))

    def _decodings_of(self, view: str, path: str, result: VerificationResult):
        """Yield (decoder_name, decoded_text) for every decoding of this view."""
        yield from _iter_text_decodings(view)
        yield from _iter_embedded_binary(view, path, result)


def _extend(path: str, name: str) -> str:
    """Append a decoder to an encoding path, dropping the 'raw' root."""
    return name if path == 'raw' else f"{path} -> {name}"


def _consolidate(leaks: list[Leak]) -> list[Leak]:
    """Collapse the many paths that reach the same leak into the shortest ones.

    Decoders overlap: form-decoding rewrites the '+' in a base64 body, so the
    same block is reached as 'base64' and again as 'form-encoding -> base64',
    and a block may be picked up both as a wrapped body and as an inline token.
    All of those are one leak. A path is dropped when another path for the same
    field uses a subset of its decoders, which keeps genuinely distinct routes
    (a value hidden in both a quoted-printable and a base64 part) while
    discarding the detours that merely arrive at one of them.
    """
    by_field: dict[str, list[Leak]] = {}
    for leak in leaks:
        by_field.setdefault(leak.field_name, []).append(leak)

    consolidated: list[Leak] = []
    for field_name, group in by_field.items():
        # Merge identical paths first, keeping the highest occurrence count:
        # two routes to one view describe the same occurrences, not twice as many.
        merged: dict[frozenset, Leak] = {}
        for leak in group:
            key = frozenset(leak.encoding_path.split(' -> '))
            existing = merged.get(key)
            if existing is None or leak.count > existing.count:
                merged[key] = leak

        for key, leak in merged.items():
            if any(other < key for other in merged if other != key):
                continue
            consolidated.append(leak)

    # Plaintext survival first, then the deepest-hidden values, so the most
    # alarming line is not buried under a list of encodings.
    consolidated.sort(key=lambda leak: (not leak.is_plaintext, leak.encoding_path, leak.field_name))
    return consolidated


def _dedupe_regions(regions: list[UninspectedRegion]) -> list[UninspectedRegion]:
    """Drop repeat reports of the same uninspectable content."""
    seen: set[tuple] = set()
    unique: list[UninspectedRegion] = []
    for region in regions:
        key = (region.reason, region.encoding_path, region.byte_length)
        if key not in seen:
            seen.add(key)
            unique.append(region)
    return unique


def _iter_text_decodings(text: str):
    """Yield whole-text transport decodings that actually change the text.

    Applied speculatively: quoted-printable decoding of a file that is not
    quoted-printable produces nonsense, and nonsense does not contain a
    configured PII value. The only cost of guessing wrong is one wasted scan.
    """
    # Quoted-printable. This is the case that hides PII unpredictably rather
    # than totally: soft line breaks (a trailing '=') split values at column 76
    # depending only on where the wrap happens to fall, so the same value can
    # survive in one file and be caught in the next.
    try:
        qp_bytes = quopri.decodestring(text.encode('latin-1', 'replace'))
        decoded = _bytes_to_text(qp_bytes, lossy=True)
        if decoded and decoded != text:
            yield 'quoted-printable', decoded
    except Exception:
        pass

    # Percent-encoding, as found throughout access logs and request traces.
    try:
        decoded = unquote(text, errors='replace')
        if decoded != text:
            yield 'percent-encoding', decoded
    except Exception:
        decoded = text

    # Form encoding additionally maps '+' to space, which is how a name in a
    # query string ends up as "Rahul+Sharma".
    try:
        plus_decoded = unquote_plus(text, errors='replace')
        if plus_decoded != text and plus_decoded != decoded:
            yield 'form-encoding', plus_decoded
    except Exception:
        pass

    # HTML entities, including the numeric forms used to obfuscate addresses.
    try:
        unescaped = html.unescape(text)
        if unescaped != text:
            yield 'html-entities', unescaped
    except Exception:
        pass

    # Backslash escapes, as emitted by structured loggers embedding JSON in a
    # message field. Only the codepoint forms are expanded; turning '\n' into a
    # real newline could only split values apart, never reveal them.
    unescaped = _ESCAPE_RE.sub(_expand_escape, text)
    if unescaped != text:
        yield 'backslash-escapes', unescaped

    # Exotic whitespace. A non-breaking space reads as a space and is what
    # '&nbsp;' unescapes to, but it is a different codepoint, so "Rahul\xa0Sharma"
    # never matches a configured "Rahul Sharma". Zero-width characters are the
    # same problem with nothing visible at all.
    normalised = _normalise_whitespace(text)
    if normalised != text:
        yield 'unicode-whitespace', normalised


_ESCAPE_RE = re.compile(r'\\u([0-9a-fA-F]{4})|\\x([0-9a-fA-F]{2})|\\U([0-9a-fA-F]{8})')

# Codepoints that read as a space but are not one, and ones that render as
# nothing at all.
_SPACE_LIKE = '               　'
_ZERO_WIDTH = '​‌‍⁠﻿'
_WHITESPACE_MAP = {ord(c): ' ' for c in _SPACE_LIKE} | {ord(c): None for c in _ZERO_WIDTH}


def _normalise_whitespace(text: str) -> str:
    """Fold space-like codepoints to a space and drop zero-width ones."""
    return text.translate(_WHITESPACE_MAP)


def _expand_escape(match: re.Match) -> str:
    """Turn one \\uXXXX / \\xXX / \\UXXXXXXXX escape into its character."""
    digits = match.group(1) or match.group(2) or match.group(3)
    try:
        return chr(int(digits, 16))
    except (ValueError, OverflowError):
        return match.group(0)


def _iter_embedded_binary(text: str, path: str, result: VerificationResult):
    """Yield decodings of base64 regions, and note the ones that are not text.

    Two shapes are recognised: a wrapped block of base64-only lines, which is
    how MIME bodies and PEM blobs are laid out, and a single long inline token,
    which covers JWTs and data URIs.
    """
    for candidate, strong in _iter_base64_candidates(text):
        raw = _b64_decode(candidate)
        if raw is None:
            continue

        decoded_name = 'base64'
        decompressed, compression = _decompress(raw)
        if decompressed is not None:
            raw = decompressed
            decoded_name = f"base64 -> {compression}"

        as_text = _bytes_to_text(raw)
        if as_text is not None:
            yield decoded_name, as_text
            continue

        # Decoded to something that is not text. Matching cannot see into it,
        # so say so rather than let it pass as checked -- but only when the
        # candidate was convincingly encoded, since a false warning here trains
        # users to ignore the real ones.
        #
        # A magic number alone is not enough for a weak candidate: gzip's is two
        # bytes, so across a log with tens of thousands of hash-like tokens some
        # random token will decode to it by chance. Real embedded payloads are
        # also substantial, so size is the corroboration that costs nothing.
        signature = _binary_signature(raw)
        if strong or (signature and len(raw) >= MIN_WEAK_BINARY_BYTES):
            result.uninspected.append(UninspectedRegion(
                reason=signature or 'base64 region decodes to binary content',
                encoding_path=_extend(path, 'base64'),
                byte_length=len(raw),
            ))


def _iter_base64_candidates(text: str):
    """Yield (base64_text, is_strong_candidate) for regions worth decoding.

    'Strong' means the region is shaped like a real encoded body rather than a
    long word that happens to use base64's alphabet; only strong candidates are
    allowed to raise an uninspected-content warning.
    """
    lines = text.splitlines()
    block: list[str] = []

    for line in lines:
        stripped = line.strip()
        if len(stripped) >= MIN_B64_LINE and _B64_LINE_RE.fullmatch(stripped):
            block.append(stripped)
            continue
        if block:
            yield ''.join(block), True
            block = []
    if block:
        yield ''.join(block), True

    # Inline tokens: a JWT segment, a data: URI payload, a base64 field in a
    # log line. Held to a character-mix test because ordinary long words are
    # spelled entirely in base64's alphabet too.
    for match in _B64_TOKEN_RE.finditer(text):
        for token in _inline_variants(match.group()):
            if _has_encoded_character_mix(token):
                yield token, False


def _inline_variants(token: str):
    """Yield a token and its '='-delimited tail, to survive a key= prefix.

    '=' is part of base64's alphabet, so a run like 'payload=H4sIAAAA...'
    scans as a single token and decodes to nothing. Real base64 only uses '='
    as trailing padding, so anything after an internal one is a fresh
    candidate -- which is the shape of every key=value log line and query
    parameter carrying an encoded payload.
    """
    yield token
    for chunk in token.split('='):
        if chunk and chunk != token and len(chunk) >= MIN_B64_LEN:
            yield chunk


_B64_LINE_RE = re.compile(r'[A-Za-z0-9+/=_-]+')
_B64_TOKEN_RE = re.compile(r'[A-Za-z0-9+/=_-]{%d,}' % MIN_B64_LEN)


def _has_encoded_character_mix(token: str) -> bool:
    """True when a token's character mix suggests encoding rather than prose."""
    if any(c in token for c in '+/='):
        return True
    classes = sum([
        any(c.isupper() for c in token),
        any(c.islower() for c in token),
        any(c.isdigit() for c in token),
    ])
    return classes >= 3


def _b64_decode(candidate: str) -> bytes | None:
    """Decode a base64 region, tolerating base64url and missing padding."""
    compact = ''.join(candidate.split())
    if len(compact) < MIN_B64_LEN:
        return None

    padded = compact + '=' * (-len(compact) % 4)
    for decoder in (base64.b64decode, base64.urlsafe_b64decode):
        try:
            raw = decoder(padded)
        except (binascii.Error, ValueError):
            continue
        if raw:
            return raw
    return None


def _decompress(data: bytes) -> tuple[bytes | None, str]:
    """Inflate a gzip or zlib stream, so compressed payloads stay searchable."""
    if data.startswith(b'\x1f\x8b'):
        try:
            return gzip.decompress(data), 'gzip'
        except (OSError, EOFError, zlib.error):
            return None, ''
    if data[:1] == b'\x78':  # zlib header variants: 78 01 / 78 9c / 78 da
        try:
            return zlib.decompress(data), 'zlib'
        except zlib.error:
            return None, ''
    return None, ''


def _binary_signature(data: bytes) -> str:
    """Name the container type if these bytes start with a known signature."""
    for magic, description in _BINARY_SIGNATURES:
        if data.startswith(magic):
            return f"{description} -- its contents cannot be searched as text"
    return ''


def _bytes_to_text(data: bytes, lossy: bool = False) -> str | None:
    """Decode bytes to text, or return None when they are not text at all.

    A successful UTF-8 decode does not by itself mean the bytes were text:
    NUL is a perfectly valid UTF-8 codepoint, so a NUL-padded PDF decodes
    without error and would otherwise pass as searchable. The decoded result is
    judged on its characters rather than its bytes so that non-Latin scripts,
    whose UTF-8 is full of high bytes, are not mistaken for binary.
    """
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError:
        if lossy or _is_probably_text(data):
            return data.decode('latin-1')
        return None

    if lossy or _is_probably_text_str(text):
        return text
    return None


def _is_probably_text(data: bytes) -> bool:
    """Heuristic for bytes that are not valid UTF-8: mostly printable, no NULs."""
    if not data:
        return False
    if b'\x00' in data:
        return False

    printable = sum(1 for b in data if 32 <= b < 127 or b in (9, 10, 13))
    return printable / len(data) >= 0.90


def _is_probably_text_str(text: str) -> bool:
    """Heuristic for decoded characters: mostly printable, no NULs."""
    if not text:
        return False
    if '\x00' in text:
        return False

    printable = sum(1 for c in text if c.isprintable() or c in '\t\n\r')
    return printable / len(text) >= 0.90


def detect_binary_input(raw_bytes: bytes) -> UninspectedRegion | None:
    """Report an input file that is not text, and so was never really searched.

    Everything that is not JSON or YAML is currently read as text with a
    latin-1 fallback, and latin-1 accepts all 256 byte values -- so a PDF or a
    zip-backed Office document is read as mojibake and processed without
    complaint. Its real contents were never matched against.
    """
    if not raw_bytes:
        return None

    signature = _binary_signature(raw_bytes)
    if not signature and _is_probably_text(raw_bytes):
        return None

    return UninspectedRegion(
        reason=signature or 'input file is binary, not text',
        encoding_path='input file',
        byte_length=len(raw_bytes),
    )
