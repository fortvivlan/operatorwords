"""Collect independent Google Translate web translations with googletrans."""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import importlib.metadata
import json
import os
import random
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

import googletrans
import httpx
from googletrans import LANGUAGES, Translator


RUN_ID = "googletrans-4.0.0rc1-20260917-v1"
SOURCE_LANGUAGE = "ru"
TARGETS = (
    ("EN", "en"),
    ("DE", "de"),
    ("BG", "bg"),
    ("SV", "sv"),
    ("DA", "da"),
    ("IS", "is"),
    ("AR", "ar"),
    ("NO", "no"),
    ("FI", "fi"),
    ("HI", "hi"),
)
OMITTED_TARGETS = (("OS", "os", "not supported by the configured googletrans client"),)
SOURCE_FILES = (("dicto", "dicto.txt"), ("dere", "dere.txt"))
DEFAULT_DELAY_MIN = 7.0
DEFAULT_DELAY_MAX = 9.0
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_SERVICE_URL = "translate.google.com"
CLEAR_TERMINAL_LINE = "\r\033[2K"


class CollectionPausedError(RuntimeError):
    """Stop the run for an external condition that should be retried later."""


class ProviderBlockedError(CollectionPausedError):
    """Stop the whole run when the Google web endpoint blocks requests."""


class TransientNetworkError(CollectionPausedError):
    """Stop the run when DNS fails before a request reaches the provider."""


@dataclass(frozen=True)
class SourceSentence:
    sentence_id: str
    group: str
    text: str


class TranslationResult(Protocol):
    text: str
    origin: str
    src: str
    dest: str
    pronunciation: str | None
    _response: Any


class TranslationClient(Protocol):
    async def translate(
        self, text: str, dest: str = "en", src: str = "auto", **kwargs: Any
    ) -> TranslationResult: ...


class IsolatedGoogletransClient:
    """Create a fresh web client for every independent translation call."""

    def __init__(self, service_url: str, timeout: httpx.Timeout) -> None:
        self.service_url = service_url
        self.timeout = timeout

    async def translate(
        self, text: str, dest: str = "en", src: str = "auto", **kwargs: Any
    ) -> TranslationResult:
        return await asyncio.to_thread(self._translate_sync, text, dest, src)

    def _translate_sync(
        self, text: str, dest: str, src: str
    ) -> TranslationResult:
        translator = Translator(
            service_urls=[self.service_url],
            raise_exception=True,
            timeout=self.timeout,
            http2=True,
        )
        try:
            return translator.translate(text, dest=dest, src=src)
        finally:
            translator.client.close()


def print_status(message: str) -> None:
    """Replace the current terminal status line without scrolling."""
    print(f"{CLEAR_TERMINAL_LINE}{message}", end="", flush=True)


def clear_status() -> None:
    """Erase the transient status line before permanent output."""
    print(CLEAR_TERMINAL_LINE, end="", flush=True)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def read_sources(data_dir: Path) -> list[SourceSentence]:
    sources: list[SourceSentence] = []
    all_texts: set[str] = set()

    for group, filename in SOURCE_FILES:
        path = data_dir / filename
        lines = path.read_text(encoding="utf-8").splitlines()
        if not lines or any(not line for line in lines):
            raise ValueError(f"{path} must contain one non-empty sentence per line")
        if len(lines) != len(set(lines)):
            raise ValueError(f"{path} contains duplicate sentences")

        for number, text in enumerate(lines, start=1):
            if text in all_texts:
                raise ValueError(f"sentence occurs in both source groups: {text!r}")
            all_texts.add(text)
            sources.append(SourceSentence(f"{group}-{number:03d}", group, text))

    return sources


def source_digest(sources: list[SourceSentence]) -> str:
    payload = json.dumps(
        [asdict(source) for source in sources], ensure_ascii=False, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_manifest(
    sources: list[SourceSentence],
    run_id: str,
    service_url: str,
    delay_min: float,
    delay_max: float,
    max_attempts: int,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "provider": "Google Translate web endpoint via googletrans",
        "provider_model": None,
        "provider_model_note": "the web endpoint does not expose a model identifier",
        "client": "googletrans",
        "client_distribution_version": importlib.metadata.version("googletrans"),
        "client_reported_version": googletrans.__version__,
        "service_url": service_url,
        "source_language": SOURCE_LANGUAGE,
        "targets": [
            {"column": column, "provider_code": code, "name": LANGUAGES[code]}
            for column, code in TARGETS
        ],
        "omitted_targets": [
            {"column": column, "provider_code": code, "reason": reason}
            for column, code, reason in OMITTED_TARGETS
        ],
        "source_files": [filename for _, filename in SOURCE_FILES],
        "source_count": len(sources),
        "source_sha256": source_digest(sources),
        "submission_mode": "independent sentence calls",
        "collection_method": "api",
        "delay_seconds": {"minimum": delay_min, "maximum": delay_max},
        "retry_policy": {
            "maximum_attempts_per_sentence_language": max_attempts,
            "applies_uniformly": True,
            "pre_request_network_behavior": (
                "stop immediately on a DNS resolution failure; the failed call does "
                "not consume the provider-attempt limit; resume the same run later"
            ),
            "provider_block_behavior": (
                "stop immediately on HTTP 403 or 429; blocked attempts do not "
                "consume the retry limit; resume the same run later"
            ),
        },
        "request_settings": {
            "one_sentence_per_call": True,
            "isolated_http_session_per_call": True,
            "source_code": SOURCE_LANGUAGE,
            "timeout_seconds": 30,
            "http2": True,
        },
    }


def write_or_validate_manifest(path: Path, manifest: dict[str, Any]) -> None:
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing != manifest:
            raise ValueError(
                f"{path} does not match this run; use a new run ID/output path"
            )
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def load_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as error:
            raise ValueError(f"invalid JSON on {path}:{line_number}") from error
    return records


def append_record(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
    with path.open("a", encoding="utf-8", newline="\n") as output:
        output.write(encoded)
        output.flush()
        os.fsync(output.fileno())


def successful_outputs(records: list[dict[str, Any]]) -> dict[tuple[str, str], str]:
    outputs: dict[tuple[str, str], str] = {}
    for record in records:
        if record["status"] == "success":
            outputs[(record["sentence_id"], record["target_code"])] = record[
                "raw_output"
            ]
    return outputs


def attempt_counts(records: list[dict[str, Any]]) -> dict[tuple[str, str], int]:
    counts: dict[tuple[str, str], int] = {}
    for record in records:
        key = (record["sentence_id"], record["target_code"])
        counts[key] = max(counts.get(key, 0), int(record["attempt"]))
    return counts


def capped_failure_counts(
    records: list[dict[str, Any]],
) -> dict[tuple[str, str], int]:
    """Count failures that consume the per-pair attempt limit."""
    counts: dict[tuple[str, str], int] = {}
    for record in records:
        if record["status"] != "failed" or not failure_counts_toward_limit(record):
            continue
        key = (record["sentence_id"], record["target_code"])
        counts[key] = counts.get(key, 0) + 1
    return counts


def failure_counts_toward_limit(record: dict[str, Any]) -> bool:
    """Return whether a recorded failure represents a provider attempt.

    Older records marked DNS failures as counted. Reclassify those records while
    retaining them verbatim in the append-only JSONL log.
    """
    if not record.get("counts_toward_max_attempts", True):
        return False
    return "Temporary failure in name resolution" not in (record.get("error") or "")


def write_csv(
    path: Path,
    sources: list[SourceSentence],
    outputs: dict[tuple[str, str], str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        newline="",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as temporary:
        writer = csv.DictWriter(
            temporary,
            fieldnames=["ID", "GROUP", "RU", *(column for column, _ in TARGETS)],
        )
        writer.writeheader()
        for source in sources:
            row = {"ID": source.sentence_id, "GROUP": source.group, "RU": source.text}
            row.update(
                {
                    column: outputs.get((source.sentence_id, code), "")
                    for column, code in TARGETS
                }
            )
            writer.writerow(row)
        temporary_path = Path(temporary.name)
    for retry in range(6):
        try:
            temporary_path.replace(path)
            return
        except PermissionError:
            if retry == 5:
                raise
            # Windows may briefly lock a CSV while an editor, indexer, or virus
            # scanner is reading it. The raw JSONL is already durable, so a
            # short local retry is safe and does not repeat an API request.
            time.sleep(0.25 * (retry + 1))


def response_metadata(result: TranslationResult) -> dict[str, Any]:
    response = getattr(result, "_response", None)
    return {
        "reported_source_code": result.src,
        "reported_target_code": result.dest,
        "origin": result.origin,
        "pronunciation": result.pronunciation,
        "http_status": getattr(response, "status_code", None),
        "http_version": getattr(response, "http_version", None),
    }


async def collect(
    client: TranslationClient,
    sources: list[SourceSentence],
    raw_path: Path,
    csv_path: Path,
    run_id: str,
    delay_min: float,
    delay_max: float,
    max_attempts: int,
    sleep: Any = asyncio.sleep,
    random_uniform: Any = random.uniform,
) -> tuple[int, int]:
    records = load_records(raw_path)
    outputs = successful_outputs(records)
    attempts = attempt_counts(records)
    capped_failures = capped_failure_counts(records)
    total = len(sources) * len(TARGETS)
    completed = len(outputs)
    print(f"Resuming with {completed}/{total} successful translations", flush=True)
    write_csv(csv_path, sources, outputs)

    for source in sources:
        for column, target_code in TARGETS:
            key = (source.sentence_id, target_code)
            if key in outputs:
                continue

            while capped_failures.get(key, 0) < max_attempts and key not in outputs:
                attempt = attempts.get(key, 0) + 1
                started_at = utc_now()
                try:
                    result = await client.translate(
                        source.text, src=SOURCE_LANGUAGE, dest=target_code
                    )
                    if not result.text:
                        raise ValueError("provider returned an empty translation")
                    record = {
                        "run_id": run_id,
                        "sentence_id": source.sentence_id,
                        "group": source.group,
                        "source_text": source.text,
                        "source_code": SOURCE_LANGUAGE,
                        "target_language": LANGUAGES[target_code],
                        "target_code": target_code,
                        "provider": "Google Translate web endpoint via googletrans",
                        "provider_model": None,
                        "client_version": importlib.metadata.version("googletrans"),
                        "prompt_template": None,
                        "decoding_settings": None,
                        "submission_mode": "independent",
                        "collection_method": "api",
                        "attempt": attempt,
                        "request_started_at_utc": started_at,
                        "response_received_at_utc": utc_now(),
                        "status": "success",
                        "error": None,
                        "raw_output": result.text,
                        "response_metadata": response_metadata(result),
                    }
                    append_record(raw_path, record)
                    attempts[key] = attempt
                    outputs[key] = result.text
                    completed += 1
                    write_csv(csv_path, sources, outputs)
                    print_status(
                        f"[{completed}/{total}] {source.sentence_id} -> {column}"
                    )
                except Exception as error:  # retained verbatim in the raw run log
                    if key in outputs:
                        # The provider response was already appended to JSONL;
                        # only a derived CSV refresh failed. Do not mislabel the
                        # translation or repeat the external request.
                        clear_status()
                        print(
                            f"CSV refresh deferred after {source.sentence_id} -> "
                            f"{column}: {type(error).__name__}: {error}",
                            file=sys.stderr,
                            flush=True,
                        )
                        continue
                    provider_blocked = any(
                        status in str(error) for status in ("403", "429")
                    )
                    dns_unavailable = "Temporary failure in name resolution" in str(
                        error
                    )
                    record = {
                        "run_id": run_id,
                        "sentence_id": source.sentence_id,
                        "group": source.group,
                        "source_text": source.text,
                        "source_code": SOURCE_LANGUAGE,
                        "target_language": LANGUAGES[target_code],
                        "target_code": target_code,
                        "provider": "Google Translate web endpoint via googletrans",
                        "provider_model": None,
                        "client_version": importlib.metadata.version("googletrans"),
                        "prompt_template": None,
                        "decoding_settings": None,
                        "submission_mode": "independent",
                        "collection_method": "api",
                        "attempt": attempt,
                        "request_started_at_utc": started_at,
                        "response_received_at_utc": utc_now(),
                        "status": "failed",
                        "error": f"{type(error).__name__}: {error}",
                        "counts_toward_max_attempts": not (
                            provider_blocked or dns_unavailable
                        ),
                        "raw_output": None,
                        "response_metadata": None,
                    }
                    append_record(raw_path, record)
                    attempts[key] = attempt
                    if not provider_blocked:
                        if not dns_unavailable:
                            capped_failures[key] = capped_failures.get(key, 0) + 1
                    if provider_blocked:
                        clear_status()
                        print(
                            f"BLOCKED attempt {attempt}: "
                            f"{source.sentence_id} -> {column}: {error}",
                            file=sys.stderr,
                            flush=True,
                        )
                        write_csv(csv_path, sources, outputs)
                        raise ProviderBlockedError(
                            "Google blocked the web request; the run stopped without "
                            "attempting later sentence-language pairs"
                        ) from error
                    if dns_unavailable:
                        clear_status()
                        print(
                            f"NETWORK UNAVAILABLE attempt {attempt}: "
                            f"{source.sentence_id} -> {column}: {error}",
                            file=sys.stderr,
                            flush=True,
                        )
                        write_csv(csv_path, sources, outputs)
                        raise TransientNetworkError(
                            "DNS resolution failed before reaching Google; the run "
                            "stopped and can be resumed later"
                        ) from error
                    clear_status()
                    print(
                        f"FAILED attempt {capped_failures[key]}/{max_attempts}: "
                        f"{source.sentence_id} -> {column}: {error}",
                        file=sys.stderr,
                        flush=True,
                    )

                if completed < total:
                    delay = random_uniform(delay_min, delay_max)
                    # print_status(f"Waiting {delay:.1f}s")
                    await sleep(delay)

    missing = total - len(outputs)
    write_csv(csv_path, sources, outputs)
    clear_status()
    return len(outputs), missing


def parse_args() -> argparse.Namespace:
    data_dir = Path(__file__).resolve().parents[1] / "data"
    parser = argparse.ArgumentParser(
        description="Collect independent Russian translations through googletrans."
    )
    parser.add_argument("--data-dir", type=Path, default=data_dir)
    parser.add_argument("--run-id", default=RUN_ID)
    parser.add_argument(
        "--service-url",
        default=DEFAULT_SERVICE_URL,
        help=(
            "googletrans service domain; changing it requires a new run ID "
            f"(default: {DEFAULT_SERVICE_URL})"
        ),
    )
    parser.add_argument("--delay-min", type=float, default=DEFAULT_DELAY_MIN)
    parser.add_argument("--delay-max", type=float, default=DEFAULT_DELAY_MAX)
    parser.add_argument("--max-attempts", type=int, default=DEFAULT_MAX_ATTEMPTS)
    return parser.parse_args()


async def async_main() -> int:
    args = parse_args()
    if not 0 <= args.delay_min <= args.delay_max:
        raise ValueError("delays must satisfy 0 <= minimum <= maximum")
    if args.max_attempts < 1:
        raise ValueError("--max-attempts must be positive")

    unsupported = [code for _, code in TARGETS if code not in LANGUAGES]
    if unsupported:
        raise ValueError(f"googletrans does not support configured targets: {unsupported}")

    sources = read_sources(args.data_dir)
    stem = args.run_id
    manifest_path = args.data_dir / f"{stem}.manifest.json"
    raw_path = args.data_dir / f"{stem}.jsonl"
    csv_path = args.data_dir / "google_translate.csv"
    manifest = build_manifest(
        sources,
        args.run_id,
        args.service_url,
        args.delay_min,
        args.delay_max,
        args.max_attempts,
    )
    write_or_validate_manifest(manifest_path, manifest)

    timeout = httpx.Timeout(30.0)
    client = IsolatedGoogletransClient(args.service_url, timeout)
    try:
        completed, missing = await collect(
            client,
            sources,
            raw_path,
            csv_path,
            args.run_id,
            args.delay_min,
            args.delay_max,
            args.max_attempts,
        )
    except CollectionPausedError as error:
        print(str(error), file=sys.stderr)
        return 2

    print(f"Completed: {completed}; missing: {missing}; CSV: {csv_path}")
    return 1 if missing else 0


def main() -> None:
    try:
        exit_code = asyncio.run(async_main())
    except KeyboardInterrupt:
        print("Stopped by user; run the same command to resume.", file=sys.stderr)
        exit_code = 130
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
