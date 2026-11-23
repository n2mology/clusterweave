"""Content admission for supplied plant CDS; source sequences remain unchanged."""
from __future__ import annotations

import hashlib
import io
import re
import warnings
from pathlib import Path

from genbank_readiness import inspect_genbank_translation_stream


class PlantAnnotationError(ValueError):
    """A supplied annotation failure, distinct from an absent annotation."""
    def __init__(self, reason, *, state='ANNOTATION_INCOMPATIBLE', record_id=None,
                 cds_ordinal=None, protein_id=None, gene=None):
        self.receipt = dict(state=state, reason=reason, record_id=record_id,
                            cds_ordinal=cds_ordinal, protein_id=protein_id, gene=gene)
        label = 'Annotation required' if state == 'ANNOTATION_REQUIRED' else 'Supplied plant annotation incompatible'
        identity = ' / '.join(str(x) for x in (record_id,
            f'CDS {cds_ordinal + 1}' if cds_ordinal is not None else None, gene, protein_id) if x)
        super().__init__(f"{label}: {identity + ': ' if identity else ''}{reason}")


def _one(qualifiers, name, default=None):
    values = qualifiers.get(name, [default])
    if not isinstance(values, list) or len(values) != 1 or values[0] is None:
        raise ValueError(f"missing or nonunique {name}")
    return str(values[0])


def check_translation(feature, sequence):
    """Validate structure first; retain bounded source assertions without editing.

    RefSeq's unclassified translation discrepancy explicitly permits indels
    between genomic CDS and the supplied protein. It is source provenance,
    not an independently verified translation or permission to repair DNA.
    """
    from Bio.Seq import Seq
    from Bio.SeqFeature import ExactPosition
    from Bio.Data.CodonTable import TranslationError
    try:
        supplied = ''.join(_one(feature.qualifiers, 'translation').split())
        supplied = supplied.removesuffix('*')
        if not supplied or set(supplied) - set('ACDEFGHIKLMNPQRSTVWYXBZJUO'):
            raise ValueError('invalid supplied peptide')
        offset = int(_one(feature.qualifiers, 'codon_start', '1')) - 1
        if offset not in (0, 1, 2):
            raise ValueError('invalid codon_start')
        table = int(_one(feature.qualifiers, 'transl_table', '1'))
        if feature.location is None:
            raise ValueError('missing location')
        for part in feature.location.parts:
            if part.ref or part.ref_db or part.strand not in (-1, 1):
                raise ValueError('remote or unstranded CDS location')
            if not 0 <= int(part.start) < int(part.end) <= len(sequence):
                raise ValueError('CDS location outside sequence')
        nt = str(feature.extract(sequence))[offset:]
        if not nt or set(nt.upper()) - set('ACGTRYSWKMBDHVN'):
            raise ValueError('invalid CDS sequence')
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            ordinary = str(Seq(nt).translate(table=table)).removesuffix('*')
            try:
                complete = str(Seq(nt).translate(table=table, cds=True)).removesuffix('*')
            except Exception:
                complete = None
        last = feature.location.parts[-1]
        end = last.end if last.strand != -1 else last.start
        partial3 = not isinstance(end, ExactPosition)
        declared_partial = any(not isinstance(pos, ExactPosition) for part in feature.location.parts for pos in (part.start, part.end))
        if len(nt) % 3 and not declared_partial:
            # Only this declared discrepancy explains the observed complete-CDS
            # length mismatch. A generic exception, splice-site note or single
            # codon transl_except does not excuse an unexplained missing base.
            if feature.qualifiers.get('exception') == ['unclassified translation discrepancy']:
                return {'status': 'SOURCE_EXCEPTION',
                        'reason': 'source_declared_translation_discrepancy',
                        'exception': list(feature.qualifiers['exception']),
                        'length_nt': len(nt), 'length_aa': len(supplied),
                        'independent_truth': False}
            return {'status': 'FAIL', 'reason': 'complete_cds_has_partial_codon'}
        if supplied in (complete, ordinary):
            return {'status': 'EXACT', 'declared_partial': declared_partial, 'length_nt': len(nt)}
        if partial3 and len(nt) % 3 == 2 and set(nt[-2:].upper()) <= set('ACGT'):
            peptides = {str(Seq(nt + base).translate(table=table)).removesuffix('*') for base in 'ACGT'}
            if peptides == {supplied}:
                return {'status': 'PARTIAL3_COMPATIBLE', 'terminal_bases': nt[-2:], 'terminal_amino_acid': supplied[-1], 'all_four_completions_equal': True, 'length_nt': len(nt)}
        exception = feature.qualifiers.get('exception')
        if exception in (['unclassified translation discrepancy'], ['RNA editing'], ['ribosomal slippage']):
            return {'status': 'SOURCE_EXCEPTION', 'reason': 'source_declared_translation_exception',
                    'exception': list(exception), 'independent_truth': False}
        codon_exceptions = feature.qualifiers.get('transl_except')
        if codon_exceptions:
            from Bio.SeqFeature import Location
            from Bio.Data.IUPACData import protein_letters_3to1
            amino_acids = set(protein_letters_3to1) | {'Sec', 'Pyl', 'TERM', 'OTHER'}
            for declared in codon_exceptions:
                match = re.fullmatch(r'\(pos:(.+),\s*aa:([A-Za-z]+)\)', declared)
                if not match or match[2] not in amino_acids:
                    raise ValueError('malformed transl_except')
                codon = Location.fromstring(re.sub(r'\s+', '', match[1]), length=len(sequence))
                if len(codon) != 3 or any(part.ref or part.ref_db for part in codon.parts):
                    raise ValueError('transl_except must identify one local codon')
                if any(pos not in feature.location for pos in codon):
                    raise ValueError('transl_except outside CDS')
            return {'status': 'SOURCE_EXCEPTION', 'reason': 'source_declared_translation_exception',
                    'transl_except': list(codon_exceptions), 'independent_truth': False}
        return {'status': 'FAIL', 'reason': 'unexplained_translation_mismatch', 'partial3': partial3}
    except (ValueError, TypeError, IndexError, KeyError, AttributeError, TranslationError) as exc:
        return {'status': 'FAIL', 'reason': 'malformed_cds', 'detail': str(exc)}


def inspect_plant_annotation(handle, fasta_handle=None):
    """Check complete GenBank content and, when supplied, exact paired sequences."""
    from Bio import SeqIO
    from taxon_routing import parse_genbank_taxonomy_stream
    raw = handle.read()
    if isinstance(raw, str):
        raw = raw.encode('utf-8')
    readiness = inspect_genbank_translation_stream(io.BytesIO(raw))
    if not readiness.structurally_complete:
        raise PlantAnnotationError('malformed_or_incomplete_genbank')
    if not readiness.cds_total:
        raise PlantAnnotationError('supply translated GenBank with CDS for every plant record; FASTA+GFF3 conversion is not supported for plants', state='ANNOTATION_REQUIRED')
    authority = parse_genbank_taxonomy_stream(io.BytesIO(raw))
    if authority and authority['taxon_group'] != 'plants':
        raise ValueError('Plant assignment conflicts with GenBank source taxonomy')
    records, checks, seen, seqs = [], [], set(), {}
    try:
        with warnings.catch_warnings(record=True) as messages:
            warnings.simplefilter('always')
            parsed = list(SeqIO.parse(io.StringIO(raw.decode('utf-8')), 'genbank'))
        if messages:
            raise ValueError('Malformed GenBank: ' + str(messages[0].message))
        for record in parsed:
            if record.id in seen:
                raise ValueError('Duplicate GenBank record identity: ' + record.id)
            seen.add(record.id)
            sequence = str(record.seq).upper()
            if len(sequence) <= 1000 or set(sequence) - set('ACGTRYSWKMBDHVN'):
                raise ValueError('Plant records require valid nucleotide sequences longer than 1000 bases')
            cds = [f for f in record.features if f.type == 'CDS']
            keys = set()
            for ordinal, feature in enumerate(cds):
                check = check_translation(feature, record.seq)
                check.update(record_id=record.id, cds_ordinal=ordinal,
                             protein_id=feature.qualifiers.get('protein_id', [None])[0],
                             gene=feature.qualifiers.get('gene', [None])[0])
                checks.append(check)
                if check['status'] == 'FAIL':
                    reason = check['reason'] + (': ' + check['detail'] if check.get('detail') else '')
                    raise PlantAnnotationError(reason, record_id=record.id, cds_ordinal=ordinal,
                                               protein_id=check['protein_id'], gene=check['gene'])
                peptide = _one(feature.qualifiers, 'translation')
                key = (str(feature.location), peptide, tuple(feature.qualifiers.get('protein_id', [])))
                if key in keys:
                    raise ValueError('Ambiguous duplicate plant CDS identity')
                keys.add(key)
            seqs[record.id] = sequence
            records.append({'record_id': record.id, 'sequence_sha256': hashlib.sha256(sequence.encode()).hexdigest(), 'cds_count': len(cds),
                            'analysis_state': 'supplied_cds' if cds else 'not_evaluated_no_cds',
                            'reason': None if cds else 'Native plantiSMASH skips records with no supplied CDS; original sequence retained, no gene prediction or BGC absence claim.'})
        if fasta_handle is not None:
            fasta = fasta_handle.read()
            if isinstance(fasta, bytes):
                fasta = fasta.decode('utf-8')
            pairs = list(SeqIO.parse(io.StringIO(fasta), 'fasta'))
            if len({r.id for r in pairs}) != len(pairs) or {r.id: str(r.seq).upper() for r in pairs} != seqs:
                raise ValueError('Manual annotation does not match the supplied FASTA record identities and sequences')
    except PlantAnnotationError:
        raise
    except (ValueError, TypeError, KeyError, IndexError) as exc:
        raise PlantAnnotationError(str(exc)) from exc
    return {'schema': 'plant-annotation-admission-v1', 'annotation_state': 'ready', 'source_sha256': hashlib.sha256(raw).hexdigest(), 'records': records, 'cds_checks': checks, 'source_exceptions_are_not_independent_truth': True, 'records_without_cds_are_not_evaluated': True}


def inspect_plant_annotation_path(path, fasta=None):
    with Path(path).open('rb') as handle:
        if fasta:
            with Path(fasta).open('rb') as paired:
                return inspect_plant_annotation(handle, paired)
        return inspect_plant_annotation(handle)
