#!/usr/bin/env python3
"""Shared, streaming GenBank CDS-translation readiness checks.

A fungal GenBank input is reusable only when every non-pseudogene CDS has a
non-empty protein translation. This avoids treating a bare ``/translation=``
token, or one translated CDS among many untranslated CDS features, as a fully
annotated genome.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterator


FEATURE_RE = re.compile(r"^ {5}(?P<key>\S+)\s+")
TRANSLATION_RE = re.compile(r"/translation\s*=\s*(?P<value>.*)$", re.IGNORECASE)
PSEUDOGENE_RE = re.compile(r"/(?:pseudo\b|pseudogene\s*=)", re.IGNORECASE)
PROTEIN_CONTENT_RE = re.compile(r"[A-Za-z*]")


@dataclass(frozen=True)
class GenbankTranslationReadiness:
    utf8_valid: bool
    has_locus: bool
    has_features: bool
    has_origin: bool
    record_count: int
    terminator_count: int
    cds_total: int
    pseudogene_cds: int
    translated_cds: int
    untranslated_cds: int
    last_record_terminated: bool
    records_structurally_complete: bool = True

    @property
    def structurally_complete(self) -> bool:
        return (
            self.utf8_valid
            and self.has_locus
            and self.has_features
            and self.has_origin
            and self.record_count > 0
            and self.terminator_count == self.record_count
            and self.last_record_terminated
            and self.records_structurally_complete
        )

    @property
    def usable_translated_cds(self) -> bool:
        return (
            self.structurally_complete
            and self.translated_cds > 0
            and self.untranslated_cds == 0
        )


def _utf8_lines(handle: object) -> Iterator[str]:
    while True:
        raw = handle.readline()  # type: ignore[attr-defined]
        if raw in {b"", ""}:
            return
        if isinstance(raw, bytes):
            yield raw.decode("utf-8").rstrip("\r\n")
        else:
            yield str(raw).rstrip("\r\n")


def inspect_genbank_translation_stream(handle: object) -> GenbankTranslationReadiness:
    has_locus = False
    has_features = False
    has_origin = False
    record_count = 0
    terminator_count = 0
    cds_total = 0
    pseudogene_cds = 0
    translated_cds = 0
    untranslated_cds = 0
    last_nonempty = ""

    record_active = False
    record_has_features = False
    record_has_origin = False
    records_structurally_complete = True

    in_cds = False
    cds_is_pseudogene = False
    cds_has_translation = False
    translation_open = False
    translation_has_content = False
    translation_invalid = False

    def invalidate_open_translation() -> None:
        nonlocal translation_open, translation_invalid
        if translation_open:
            translation_invalid = True
            translation_open = False

    def finish_cds() -> None:
        nonlocal in_cds, cds_is_pseudogene, cds_has_translation, translation_open
        nonlocal translation_has_content, translation_invalid
        nonlocal cds_total, pseudogene_cds, translated_cds, untranslated_cds
        if not in_cds:
            return
        invalidate_open_translation()
        cds_total += 1
        if cds_is_pseudogene:
            pseudogene_cds += 1
        elif cds_has_translation and not translation_invalid:
            translated_cds += 1
        else:
            untranslated_cds += 1
        in_cds = False
        cds_is_pseudogene = False
        cds_has_translation = False
        translation_open = False
        translation_has_content = False
        translation_invalid = False

    def finish_record(*, terminated: bool) -> None:
        nonlocal record_active, record_has_features, record_has_origin
        nonlocal records_structurally_complete
        if not record_active:
            records_structurally_complete = False
            return
        if not (record_has_features and record_has_origin and terminated):
            records_structurally_complete = False
        record_active = False
        record_has_features = False
        record_has_origin = False

    def begin_translation(value: str) -> None:
        nonlocal cds_has_translation, translation_open
        nonlocal translation_has_content, translation_invalid
        text = value.strip()
        translation_has_content = False
        if not text.startswith('"'):
            translation_invalid = True
            translation_open = False
            return
        body = text[1:]
        closing_quote = body.find('"')
        if closing_quote < 0:
            translation_has_content = bool(PROTEIN_CONTENT_RE.search(body))
            translation_open = True
            return
        translation_has_content = bool(
            PROTEIN_CONTENT_RE.search(body[:closing_quote])
        )
        if body[closing_quote + 1 :].strip():
            translation_invalid = True
        elif translation_has_content:
            cds_has_translation = True
        translation_open = False

    def continue_translation(line: str) -> None:
        nonlocal cds_has_translation, translation_open
        nonlocal translation_has_content, translation_invalid
        text = line.strip()
        closing_quote = text.find('"')
        if closing_quote < 0:
            translation_has_content = translation_has_content or bool(
                PROTEIN_CONTENT_RE.search(text)
            )
            return
        translation_has_content = translation_has_content or bool(
            PROTEIN_CONTENT_RE.search(text[:closing_quote])
        )
        if text[closing_quote + 1 :].strip():
            translation_invalid = True
        elif translation_has_content:
            cds_has_translation = True
        translation_open = False

    try:
        for line in _utf8_lines(handle):
            stripped = line.strip()
            if stripped:
                last_nonempty = stripped
            if line.startswith("LOCUS") and re.match(r"^LOCUS\s+", line):
                finish_cds()
                if record_active:
                    finish_record(terminated=False)
                has_locus = True
                record_count += 1
                record_active = True
                record_has_features = False
                record_has_origin = False
                continue
            if re.match(r"^//\s*$", line):
                finish_cds()
                terminator_count += 1
                finish_record(terminated=True)
                continue
            if line.startswith("FEATURES") and re.match(r"^FEATURES\b", line):
                finish_cds()
                has_features = True
                if record_active:
                    record_has_features = True
                else:
                    records_structurally_complete = False
                continue
            if line.startswith("ORIGIN") and re.match(r"^ORIGIN\b", line):
                finish_cds()
                has_origin = True
                if record_active:
                    record_has_origin = True
                else:
                    records_structurally_complete = False
                continue

            feature_match = FEATURE_RE.match(line)
            if feature_match:
                finish_cds()
                in_cds = feature_match.group("key").upper() == "CDS"
                continue
            if not in_cds:
                continue

            if translation_open:
                if stripped.startswith("/"):
                    invalidate_open_translation()
                elif line.startswith("                     "):
                    continue_translation(line)
                    continue
                else:
                    invalidate_open_translation()

            if PSEUDOGENE_RE.search(line):
                cds_is_pseudogene = True
            translation_match = TRANSLATION_RE.search(line)
            if translation_match:
                begin_translation(translation_match.group("value"))
    except UnicodeDecodeError:
        return GenbankTranslationReadiness(
            utf8_valid=False,
            has_locus=has_locus,
            has_features=has_features,
            has_origin=has_origin,
            record_count=record_count,
            terminator_count=terminator_count,
            cds_total=cds_total,
            pseudogene_cds=pseudogene_cds,
            translated_cds=translated_cds,
            untranslated_cds=untranslated_cds,
            last_record_terminated=False,
            records_structurally_complete=False,
        )

    finish_cds()
    if record_active:
        finish_record(terminated=False)
    return GenbankTranslationReadiness(
        utf8_valid=True,
        has_locus=has_locus,
        has_features=has_features,
        has_origin=has_origin,
        record_count=record_count,
        terminator_count=terminator_count,
        cds_total=cds_total,
        pseudogene_cds=pseudogene_cds,
        translated_cds=translated_cds,
        untranslated_cds=untranslated_cds,
        last_record_terminated=last_nonempty == "//",
        records_structurally_complete=records_structurally_complete,
    )


def inspect_genbank_translation_path(path: object) -> GenbankTranslationReadiness:
    with open(path, "rb") as handle:
        return inspect_genbank_translation_stream(handle)
