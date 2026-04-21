from pathlib import Path
from collections import defaultdict
import re
from Bio import SeqIO
from Bio.Seq import Seq
from Bio.SeqRecord import SeqRecord
from Bio.SeqFeature import SeqFeature, FeatureLocation

def normalize_seqid(s: str) -> str:
    return s.split()[0]

_attr_re = re.compile(r'([^=;]+)=([^;]+)')
def parse_attrs(attr_str: str) -> dict:
    d = {}
    for m in _attr_re.finditer(attr_str.strip()):
        d[m.group(1)] = m.group(2)
    return d

def gff_to_gbk_with_translations(fasta: Path, gff3: Path, out_gbk: Path) -> tuple[int,int]:
    seqs = {rec.id: rec for rec in SeqIO.parse(str(fasta), "fasta")}
    if not seqs:
        raise RuntimeError(f"No contigs read from FASTA: {fasta}")
    seqs_norm = {normalize_seqid(k): v for k, v in seqs.items()}

    cds_by_parent = defaultdict(list)
    with gff3.open() as fh:
        for line in fh:
            if not line.strip() or line.startswith("#"):
                continue
            parts = line.rstrip("\n").split("\t")
            if len(parts) != 9:
                continue
            seqid, source, ftype, start, end, score, strand, phase, attrs = parts
            if ftype != "CDS":
                continue
            a = parse_attrs(attrs)
            parent = a.get("Parent") or a.get("transcript_id") or a.get("ID")
            if not parent:
                parent = f"{seqid}:{start}-{end}:{strand}"
            cds_by_parent[parent].append({
                "seqid": normalize_seqid(seqid),
                "start": int(start),
                "end": int(end),
                "strand": strand,
                "phase": phase,
            })

    if not cds_by_parent:
        raise RuntimeError(f"No CDS features found in GFF3: {gff3}")

    out_records = []
    for seqid_norm, rec in seqs_norm.items():
        features = []
        for parent, cds_list in cds_by_parent.items():
            cds_list_contig = [c for c in cds_list if c["seqid"] == seqid_norm]
            if not cds_list_contig:
                continue

            strand = cds_list_contig[0]["strand"]
            if strand not in {"+","-"}:
                strand = "+"

            if strand == "+":
                cds_list_contig.sort(key=lambda x: x["start"])
            else:
                cds_list_contig.sort(key=lambda x: x["start"], reverse=True)

            pieces = []
            loc_parts = []
            for c in cds_list_contig:
                s0 = c["start"] - 1
                e0 = c["end"]
                loc_parts.append(FeatureLocation(s0, e0, strand=1 if strand=="+" else -1))
                pieces.append(rec.seq[s0:e0])

            cds_seq = Seq("").join(pieces)
            if strand == "-":
                cds_seq = cds_seq.reverse_complement()

            try:
                ph = int(cds_list_contig[0]["phase"]) if cds_list_contig[0]["phase"] not in {".",""} else 0
            except Exception:
                ph = 0
            if ph in (1,2):
                cds_seq = cds_seq[ph:]

            prot = cds_seq.translate(to_stop=False)

            location = loc_parts[0]
            for lp in loc_parts[1:]:
                location = location + lp

            quals = {
                "locus_tag": [parent],
                "product": ["predicted_protein"],
                "translation": [str(prot)],
            }
            features.append(SeqFeature(location=location, type="CDS", qualifiers=quals))

        gb_rec = SeqRecord(rec.seq, id=rec.id, name=rec.name, description=rec.description)
        gb_rec.annotations["molecule_type"] = "DNA"
        gb_rec.features = features
        out_records.append(gb_rec)

    out_gbk.parent.mkdir(parents=True, exist_ok=True)
    with out_gbk.open("w") as out:
        SeqIO.write(out_records, out, "genbank")

    txt = out_gbk.read_text(errors="ignore")
    cds_count = sum(1 for line in txt.splitlines() if re.match(r"^\s+CDS\s", line))
    tr_count = txt.count("/translation=")
    return cds_count, tr_count

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--fasta", required=True)
    ap.add_argument("--gff3", required=True)
    ap.add_argument("--out_gbk", required=True)
    args = ap.parse_args()
    cds, tr = gff_to_gbk_with_translations(Path(args.fasta), Path(args.gff3), Path(args.out_gbk))
    print(f"WROTE {args.out_gbk}")
    print(f"CDS features: {cds}")
    print(f"/translation=: {tr}")
