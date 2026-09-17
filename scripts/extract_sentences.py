"""Extract the unique Russian source sentences from the legacy DOCX tables."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from docx import Document
from docx.document import Document as DocumentType


DOCUMENTS = {
    "DE DICTO.docx": "dicto.txt",
    "DE RE.docx": "dere.txt",
}

# Source entries begin with "Вася" and end at the first sentence-final mark.
# Some cells contain a parenthetical model note after that mark, or a separate
# line beginning with "Прим:"; neither is part of the Russian source sentence.
SOURCE_SENTENCE = re.compile(r"^(Вася\b.*?[.!?])(?:\s|$)")

# User-approved corrections to source-data errors in the legacy document.
APPROVED_CORRECTIONS = {
    "Вася, я так и знал, дурак.": "Я так и знал, что Вася дурак.",
    "Вася, я так и знал, не придет.": "Я так и знал, что Вася не придет.",
    "Вася, я так и знал, не пришел.": "Я так и знал, что Вася не пришел.",
    "Вася, я так и знал, ошибся.": "Я так и знал, что Вася ошибся.",
    "Вася, я так и знал, не собирался приходить.": (
        "Я так и знал, что Вася не собирался приходить."
    ),
}


def extract_sentences(document: DocumentType) -> list[str]:
    """Return exact source sentences in first-occurrence order."""
    sentences: list[str] = []
    seen: set[str] = set()

    for table in document.tables:
        table_sentences: list[str] = []
        # The first row is a language header (sometimes with a note in cell 1).
        for row in table.rows[1:]:
            for raw_line in row.cells[0].text.splitlines():
                match = SOURCE_SENTENCE.match(raw_line.strip())
                if match is None:
                    continue

                sentence = APPROVED_CORRECTIONS.get(match.group(1), match.group(1))
                if sentence not in seen:
                    seen.add(sentence)
                    table_sentences.append(sentence)

        # The first source-bearing table is authoritative. Later tables repeat
        # it, but one contains "умный" substitutions introduced only because a
        # model refused to translate "дурак"; those are not source sentences.
        if table_sentences:
            sentences.extend(table_sentences)
            break

    return sentences


def extract_file(source: Path, destination: Path) -> int:
    """Extract one DOCX file and write a UTF-8 sentence-per-line file."""
    sentences = extract_sentences(Document(source))
    destination.write_text("\n".join(sentences) + "\n", encoding="utf-8", newline="\n")
    return len(sentences)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract unique Russian source sentences from the DOCX tables."
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "data",
        help="directory containing the source DOCX files (default: repository data/)",
    )
    return parser.parse_args()


def main() -> None:
    data_dir = parse_args().data_dir
    for source_name, destination_name in DOCUMENTS.items():
        count = extract_file(data_dir / source_name, data_dir / destination_name)
        print(f"{destination_name}: {count} unique sentences")


if __name__ == "__main__":
    main()
