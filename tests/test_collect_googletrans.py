import csv
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace

from scripts.collect_googletrans import (
    ProviderBlockedError,
    TARGETS,
    SourceSentence,
    capped_failure_counts,
    collect,
    print_status,
    read_sources,
)


class FakeTranslator:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    async def translate(self, text: str, dest: str, src: str) -> SimpleNamespace:
        self.calls.append((text, dest, src))
        return SimpleNamespace(
            text=f"{dest}:{text}",
            origin=text,
            src=src,
            dest=dest,
            pronunciation=None,
            _response=SimpleNamespace(status_code=200, http_version="HTTP/2"),
        )


class BlockedTranslator:
    async def translate(self, text: str, dest: str, src: str) -> SimpleNamespace:
        raise RuntimeError("Unexpected status code 429")


async def no_sleep(_: float) -> None:
    return None


class SourceTests(unittest.TestCase):
    def test_reads_groups_with_stable_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            data_dir = Path(temporary_directory)
            (data_dir / "dicto.txt").write_text("Первое.\n", encoding="utf-8")
            (data_dir / "dere.txt").write_text("Второе.\n", encoding="utf-8")

            self.assertEqual(
                read_sources(data_dir),
                [
                    SourceSentence("dicto-001", "dicto", "Первое."),
                    SourceSentence("dere-001", "dere", "Второе."),
                ],
            )

    def test_status_replaces_and_clears_the_current_line(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            print_status("[351/900] dicto-036 -> EN")
            print_status("Waiting 9.0s")

        self.assertEqual(
            output.getvalue(),
            "\r\033[2K[351/900] dicto-036 -> EN\r\033[2KWaiting 9.0s",
        )


class CollectionTests(unittest.IsolatedAsyncioTestCase):
    def test_legacy_dns_failures_do_not_exhaust_attempt_limit(self) -> None:
        records = [
            {
                "sentence_id": "dere-038",
                "target_code": "hi",
                "status": "failed",
                "counts_toward_max_attempts": True,
                "error": "ConnectError: [Errno -3] Temporary failure in name resolution",
            }
            for _ in range(3)
        ]

        self.assertEqual(capped_failure_counts(records), {})

    async def test_collects_one_sentence_per_call_and_resumes(self) -> None:
        sources = [SourceSentence("dicto-001", "dicto", "Вася ошибся.")]
        client = FakeTranslator()

        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            raw_path = directory / "raw.jsonl"
            csv_path = directory / "translations.csv"
            result = await collect(
                client,
                sources,
                raw_path,
                csv_path,
                "test-run",
                0,
                0,
                1,
                sleep=no_sleep,
                random_uniform=lambda _minimum, _maximum: 0,
            )

            self.assertEqual(result, (len(TARGETS), 0))
            self.assertEqual(len(client.calls), len(TARGETS))
            self.assertTrue(all(call[0] == sources[0].text for call in client.calls))
            records = [json.loads(line) for line in raw_path.read_text().splitlines()]
            self.assertEqual(len(records), len(TARGETS))
            with csv_path.open(encoding="utf-8", newline="") as csv_file:
                row = next(csv.DictReader(csv_file))
            self.assertEqual(row["RU"], "Вася ошибся.")
            self.assertEqual(row["EN"], "en:Вася ошибся.")

            resumed_client = FakeTranslator()
            resumed = await collect(
                resumed_client,
                sources,
                raw_path,
                csv_path,
                "test-run",
                0,
                0,
                1,
                sleep=no_sleep,
                random_uniform=lambda _minimum, _maximum: 0,
            )
            self.assertEqual(resumed, (len(TARGETS), 0))
            self.assertEqual(resumed_client.calls, [])

    async def test_stops_the_run_immediately_on_rate_limit(self) -> None:
        sources = [SourceSentence("dicto-001", "dicto", "Вася ошибся.")]
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            raw_path = directory / "raw.jsonl"
            with self.assertRaises(ProviderBlockedError):
                await collect(
                    BlockedTranslator(),
                    sources,
                    raw_path,
                    directory / "translations.csv",
                    "test-run",
                    0,
                    0,
                    3,
                    sleep=no_sleep,
                    random_uniform=lambda _minimum, _maximum: 0,
                )

            records = [json.loads(line) for line in raw_path.read_text().splitlines()]
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["status"], "failed")
            self.assertFalse(records[0]["counts_toward_max_attempts"])

    async def test_blocked_attempts_never_exhaust_resume_limit(self) -> None:
        sources = [SourceSentence("dicto-001", "dicto", "Вася ошибся.")]
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            raw_path = directory / "raw.jsonl"
            csv_path = directory / "translations.csv"
            for _ in range(3):
                with self.assertRaises(ProviderBlockedError):
                    await collect(
                        BlockedTranslator(),
                        sources,
                        raw_path,
                        csv_path,
                        "test-run",
                        0,
                        0,
                        1,
                        sleep=no_sleep,
                        random_uniform=lambda _minimum, _maximum: 0,
                    )

            client = FakeTranslator()
            completed = await collect(
                client,
                sources,
                raw_path,
                csv_path,
                "test-run",
                0,
                0,
                1,
                sleep=no_sleep,
                random_uniform=lambda _minimum, _maximum: 0,
            )
            self.assertEqual(completed, (len(TARGETS), 0))
            records = [json.loads(line) for line in raw_path.read_text().splitlines()]
            english_success = next(
                record
                for record in records
                if record["target_code"] == "en" and record["status"] == "success"
            )
            self.assertEqual(english_success["attempt"], 4)


if __name__ == "__main__":
    unittest.main()
