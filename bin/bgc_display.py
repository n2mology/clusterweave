"""Display classes only; native prediction labels and sequences are never rewritten.

Exact types remain in antismash_product_types_exact.tsv. An explicit native
'other' is distinct from a label this vocabulary cannot classify. Generic
synthase/cyclase/domain names do not establish a product class.
Primary vocabulary: antiSMASH glossary and plantiSMASH 2.0 detection rules.
"""
from __future__ import annotations
import csv
from pathlib import Path
import re

VERSION = 'clusterweave-bgc-display-v3'
with (Path(__file__).resolve().parents[1] / 'config/bgc-display-classes.tsv').open() as handle:
    RULES = list(csv.DictReader(handle, delimiter='\t'))
ORDER = [row['class'] for row in RULES]
COLORS = {row['class']: row['color'] for row in RULES}
LABELS = {row['class']: row['label'] for row in RULES}


def classes(value):
    text = str(value or '').strip().lower()
    if not text:
        return {'unclassified'}
    hits = {row['class'] for row in RULES if row['pattern'] and re.search(row['pattern'], text, re.I)}
    return hits or {'unclassified'}


def collapse(values):
    values = set(values)
    informative = values - {'other', 'unclassified', 'putative'}
    if 'hybrid' in informative or len(informative) > 1:
        return 'hybrid'
    if informative:
        return next(iter(informative))
    return next((key for key in ('putative', 'other', 'unclassified') if key in values), 'unclassified')


def classify(value):
    return collapse(classes(value))


def family_class(values):
    """Class composition of a family; never replace mixed members by a majority.

    A missing member class keeps the family unresolved. Exact member labels
    remain in the crosswalk. Putative and other are legitimate native labels.
    """
    values = set(values)
    if not values or 'unclassified' in values:
        return 'unclassified'
    return next(iter(values)) if len(values) == 1 else 'hybrid'
