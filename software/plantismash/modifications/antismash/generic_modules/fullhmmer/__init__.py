# vim: set fileencoding=utf-8 :
#
# Copyright (C) 2010-2012 Marnix H. Medema
# University of Groningen
# Department of Microbial Physiology / Groningen Bioinformatics Centre
#
# Copyright (C) 2011,2012 Kai Blin
# University of Tuebingen
# Interfaculty Institute of Microbiology and Infection Medicine
# Div. of Microbiology/Biotechnology
#
# License: GNU Affero General Public License v3 or later
# A copy of GNU AGPL v3 should have been included in this software package in LICENSE.txt.

"""Full genome PFAM anotation"""

import logging
import hashlib
from os import path
from antismash import utils
from collections import defaultdict
from Bio.SeqFeature import SeqFeature, FeatureLocation, CompoundLocation
from .name2pfamid import name_to_pfamid

name = "fullhmmer"
short_description = name.capitalize()
priority = 10000


# Tuple is ( binary_name, optional)
_required_binaries = [
    ('hmmscan', False)
]

_required_files = [
    ('Pfam-A.hmm', False),
    ('Pfam-A.hmm.h3f', False),
    ('Pfam-A.hmm.h3i', False),
    ('Pfam-A.hmm.h3m', False),
    ('Pfam-A.hmm.h3p', False)
]

def check_prereqs(options):
    "Check if all required applications are around"
    
    if 'pfamdir' not in options:
        options.pfamdir = utils.get_full_path(__file__, '')

    failure_messages = []
    for binary_name, optional in _required_binaries:
        if utils.locate_executable(binary_name) is None and not optional:
            failure_messages.append("Failed to locate file: %r" % binary_name)

    for file_name, optional in _required_files:
        if utils.locate_file(path.join(options.pfamdir, file_name)) is None and not optional:
            failure_messages.append("Failed to locate file: %r" % file_name)

    return failure_messages

def run(seq_record, options):
    "run hmmsearch against PFAM for all CDS features"
    if 'pfamdir' not in options:
        options.pfamdir = utils.get_full_path(__file__, '')

    query_sequence, feature_by_id = _protein_queries(seq_record)

    target_hmmfile = path.join(options.pfamdir, 'Pfam-A.hmm')

    logging.info('Running whole-genome pfam search')
    results = utils.run_hmmscan(target_hmmfile, query_sequence)

    _annotate(seq_record, options, results, feature_by_id)

def _parent_key(feature):
    """Stable identity independent of duplicated gene names and feature sorting."""
    identity = [str(feature.location), feature.qualifiers['translation'][0], utils.get_gene_id(feature), *feature.qualifiers.get('protein_id', [])]
    return hashlib.sha256('\0'.join(identity).encode()).hexdigest()


def _protein_queries(seq_record):
    """Give each supplied CDS its own search ID, including transcript isoforms."""
    rows, features = [], {}
    for ordinal, feature in enumerate(utils.get_cds_features(seq_record), 1):
        peptide = str(feature.qualifiers['translation'][0])
        if not peptide or '-' in peptide:
            raise ValueError('Pfam requires a nonempty, ungapped supplied CDS translation')
        query = 'CDS_{:08d}'.format(ordinal)
        features[query] = feature
        rows.append('>'+query+'\n'+peptide)
    return '\n'.join(rows), features


def _annotate(seq_record, options, results, feature_by_id=None):
    "Annotate seq_record with CDS_motifs for the result"
    logging.debug("generating feature objects for PFAM hits")
    min_score = _min_score(options)
    max_evalue = _max_evalue(options)

    if feature_by_id is None:
        feature_by_id = utils.get_feature_dict(seq_record)
    
    for r in results:
        i = 1
        for hsp in r.hsps:
            if hsp.bitscore <= min_score or hsp.evalue >= max_evalue:
                continue

            if hsp.query_id not in feature_by_id:
                continue

            feature = feature_by_id[hsp.query_id]

            loc = _domain_location(feature, hsp)
            
            newFeature = SeqFeature(location=loc, type=options.FeatureTags.fullhmmer_tag)
            
            quals = defaultdict(list)
            
            quals['label'].append(utils.get_gene_id(feature))
            quals['aSParentCDS'] = [_parent_key(feature)]
            for key in ['gene','protein_id']:
                if key in feature.qualifiers:quals[key] = list(feature.qualifiers[key])
            if 'locus_tag' in feature.qualifiers:       
                quals['locus_tag'] = feature.qualifiers['locus_tag']
            else:
                quals['locus_tag'] = [utils.get_gene_id(feature)]
            quals['domain'] = [hsp.hit_id]
            quals['asDomain_id'] = ['fullhmmer_'+hsp.query_id+'_'+'{:04d}'.format(i)]
            i += 1
            
            quals['evalue'] = [str("{:.2E}".format(float(hsp.evalue)))]
            quals['score'] = [str(hsp.bitscore)]
            quals['aSTool'] = ["fullhmmer"]
            quals['detection'] = ["hmmscan"]
            quals['database'] = [path.basename(r.target)]
            if 'transl_table' in feature.qualifiers:
                [transl_table] = feature.qualifiers['transl_table']
            else:
                transl_table = 1
            quals['translation'] = [str(feature.qualifiers['translation'][0][hsp.query_start:hsp.query_end])]

            quals['note'].append("%s-Hit: %s. Score: %s. E-value: %s. Domain range: %s..%s." % \
                    (path.basename(r.target), hsp.hit_id, hsp.bitscore, hsp.evalue,
                     hsp.hit_start, hsp.hit_end))

            quals['description'] = [hsp.hit_description]

            try:
                pfamid = name_to_pfamid[hsp.hit_id]
                if 'db_xref' in quals:
                    quals['db_xref'].append("PFAM: %s" % pfamid)
                else:
                    quals['db_xref'] = ["PFAM: %s" % pfamid]    
            except KeyError:
                pass
            
            newFeature.qualifiers=quals
            seq_record.features.append(newFeature)


def _domain_location(feature, result):
    """Map the searched protein interval through the supplied CDS splice order."""
    offset = int(feature.qualifiers.get('codon_start', ['1'])[0]) - 1
    start = 3 * int(result.query_start) + offset
    end = 3 * int(result.query_end) + offset
    if offset not in (0, 1, 2) or not 0 <= start < end <= len(feature.location):
        raise ValueError('Pfam query interval cannot map to supplied CDS')
    parts = []
    consumed = 0
    for part in feature.location.parts:
        left = max(start - consumed, 0)
        right = min(end - consumed, len(part))
        if left < right:
            if part.strand == -1:
                mapped = FeatureLocation(int(part.end)-right, int(part.end)-left, strand=-1)
            else:
                mapped = FeatureLocation(int(part.start)+left, int(part.start)+right, strand=part.strand)
            parts.append(mapped)
        consumed += len(part)
    if not parts or sum(map(len, parts)) != end-start:
        raise ValueError('Incomplete Pfam domain coordinate mapping')
    return parts[0] if len(parts)==1 else CompoundLocation(parts, operator=getattr(feature.location,'operator','join'))


def _calculate_start_end(feature, result):
    """Compatibility bounds; annotations retain the complete splice location."""
    location = _domain_location(feature, result)
    return location.start, location.end

def _min_score(options):
    "Load the minimal score from the configuration or set a default"
    try:
        score = float(options.fullhmmer.score)
    except:
        score = 0

    return score

def _max_evalue(options):
    "Load the maximal evalue from the configuration or set a default"
    try:
        evalue = float(options.fullhmmer.evalue)
    except:
        evalue = 0.01

    return evalue
