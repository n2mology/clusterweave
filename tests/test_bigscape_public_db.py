from __future__ import annotations

import hashlib
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = REPO_ROOT / "web"
if str(WEB_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_DIR))

import bigscape_public_db as bigscape_public_db_module  # noqa: E402
from bigscape_public_db import (  # noqa: E402
    BigscapePublicDatabaseError,
    PUBLIC_EXPORT_TABLE,
    PUBLIC_EXPORT_VERSION,
    PUBLIC_BIGSCAPE_VIEWER_EXPORT_TABLE,
    PUBLIC_BIGSCAPE_VIEWER_EXPORT_VERSION,
    PUBLIC_BIGSCAPE_VIEWER_PATH_POLICY,
    PUBLIC_BIGSCAPE_VIEWER_QUERY_CONTRACT,
    VIEWER_SIDECAR_FILENAME,
    create_public_bigscape_viewer_database,
    public_bigscape_viewer_database_valid,
    sanitize_bigscape_database,
    validate_public_bigscape_viewer_database,
)
from result_policy import (  # noqa: E402
    PUBLIC_BIGSCAPE_DATABASE_FILENAME,
    PUBLIC_BIGSCAPE_PATH_POLICY,
    result_is_public_bigscape_database,
    result_is_public_bigscape_viewer_database,
    result_path_public_shape,
)


RAW_NT = "ACGTGGTACCACTGACGTAGCTAGCTAGGCTA"
RAW_AA = "MKWVTFISLLFLFSSAYSRGVFRRDTHKSEIA"
RAW_ALIGNMENT = "MKWVTFISLLF--LFS+AYS"
RAW_HASH_SHARED = "raw-content-hash-shared-7fd307"
RAW_HASH_OTHER = "raw-content-hash-other-c824a1"
RAW_CONFIG_HASH_SHARED = "raw-config-hash-shared-f83a14"
RAW_CONFIG_HASH_OTHER = "raw-config-hash-other-129a7c"
RAW_DATASET_PATH = "/data/jobs/private-job/work/bigscape_stage/genome_a.gbk"
RAW_REFERENCE_PATH = "/home/private-worker/software/mibig/BGC0000001.gbk"
RAW_QUERY_PATH = "/data/jobs/private-job/work/query/query_input.gbk"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def schema_signature(connection: sqlite3.Connection) -> list[tuple]:
    return list(
        connection.execute(
            "SELECT type, name, tbl_name, COALESCE(sql, '') "
            "FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' AND name != ? "
            "ORDER BY type, name",
            (PUBLIC_EXPORT_TABLE,),
        )
    )


def row_counts(connection: sqlite3.Connection) -> dict[str, int]:
    tables = [
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name != ? "
            "ORDER BY name",
            (PUBLIC_EXPORT_TABLE,),
        )
    ]
    return {
        table: int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
        for table in tables
    }


def create_source_database(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            """
            PRAGMA user_version=7;
            PRAGMA foreign_keys=ON;
            CREATE TABLE bgc_record (
                id INTEGER PRIMARY KEY,
                gbk_id INTEGER REFERENCES gbk(id),
                parent_id INTEGER,
                record_number INTEGER,
                contig_edge INTEGER,
                record_type TEXT,
                nt_start INTEGER,
                nt_stop INTEGER,
                product TEXT,
                category TEXT,
                merged INTEGER
            );
            CREATE TABLE bgc_record_family (
                record_id INTEGER,
                family_id INTEGER
            );
            CREATE TABLE cds (
                id INTEGER PRIMARY KEY,
                gbk_id INTEGER NOT NULL REFERENCES gbk(id),
                nt_start INTEGER,
                nt_stop INTEGER,
                orf_num INTEGER,
                strand INTEGER,
                gene_kind TEXT,
                aa_seq TEXT NOT NULL
            );
            CREATE TABLE connected_component (
                id INTEGER PRIMARY KEY,
                record_id INTEGER,
                cutoff REAL,
                bin_label TEXT,
                run_id INTEGER
            );
            CREATE TABLE distance (
                record_a_id INTEGER,
                record_b_id INTEGER,
                distance REAL,
                jaccard REAL,
                adjacency REAL,
                dss REAL,
                edge_param_id INTEGER,
                lcs_a_start INTEGER,
                lcs_a_stop INTEGER,
                lcs_b_start INTEGER,
                lcs_b_stop INTEGER,
                ext_a_start INTEGER,
                ext_a_stop INTEGER,
                ext_b_start INTEGER,
                ext_b_stop INTEGER,
                reverse INTEGER,
                lcs_domain_a_start INTEGER,
                lcs_domain_a_stop INTEGER,
                lcs_domain_b_start INTEGER,
                lcs_domain_b_stop INTEGER
            );
            CREATE TABLE edge_params (
                id INTEGER PRIMARY KEY,
                weights TEXT,
                alignment_mode TEXT,
                extend_strategy TEXT
            );
            CREATE TABLE family (
                id INTEGER PRIMARY KEY,
                center_id INTEGER,
                newick TEXT,
                cutoff REAL,
                bin_label TEXT,
                run_id INTEGER
            );
            CREATE TABLE gbk (
                id INTEGER PRIMARY KEY,
                path TEXT,
                hash TEXT,
                nt_seq TEXT,
                organism TEXT,
                taxonomy TEXT,
                description TEXT
            );
            CREATE TABLE hsp (
                id INTEGER PRIMARY KEY,
                cds_id INTEGER REFERENCES cds(id),
                accession TEXT,
                env_start INTEGER,
                env_stop INTEGER,
                bit_score REAL
            );
            CREATE TABLE hsp_alignment (
                hsp_id INTEGER PRIMARY KEY NOT NULL REFERENCES hsp(id),
                alignment TEXT NOT NULL
            );
            CREATE TABLE run (
                id INTEGER PRIMARY KEY,
                label TEXT,
                start_time TEXT,
                end_time TEXT,
                duration TEXT,
                mode TEXT,
                input_dir TEXT,
                output_dir TEXT,
                reference_dir TEXT,
                query_path TEXT,
                mibig_version TEXT,
                record_type TEXT,
                classify TEXT,
                weights TEXT,
                alignment_mode TEXT,
                extend_strategy TEXT,
                include_singletons TEXT,
                cutoffs TEXT,
                min_bgc_length INTEGER,
                include_categories TEXT,
                exclude_categories TEXT,
                include_classes TEXT,
                exclude_classes TEXT,
                config_hash TEXT
            );
            CREATE TABLE scanned_cds (
                cds_id INTEGER
            );
            CREATE INDEX distance_record_id_index
                ON distance(record_a_id, record_b_id);
            CREATE INDEX record_id_index ON bgc_record(gbk_id);
            """
        )
        connection.executemany(
            "INSERT INTO gbk(id,path,hash,nt_seq,organism,taxonomy,description) "
            "VALUES(?,?,?,?,?,?,?)",
            [
                (
                    1,
                    RAW_DATASET_PATH,
                    RAW_HASH_SHARED,
                    RAW_NT,
                    "Dataset organism",
                    "Fungi",
                    "dataset record",
                ),
                (
                    2,
                    RAW_REFERENCE_PATH,
                    RAW_HASH_OTHER,
                    RAW_NT[::-1],
                    "Reference organism",
                    "Fungi",
                    "reference record",
                ),
                (
                    3,
                    RAW_QUERY_PATH,
                    RAW_HASH_SHARED,
                    RAW_NT,
                    "Query organism",
                    "Bacteria",
                    "query record",
                ),
            ],
        )
        connection.executemany(
            "INSERT INTO run("
            "id,input_dir,output_dir,reference_dir,query_path,mibig_version,config_hash"
            ") VALUES(?,?,?,?,?,?,?)",
            [
                (
                    1,
                    "/data/jobs/private-job/work/bigscape_stage",
                    "/data/jobs/private-job/results/big_scape",
                    "/home/private-worker/software/mibig",
                    RAW_QUERY_PATH,
                    "3.1",
                    RAW_CONFIG_HASH_SHARED,
                ),
                (2, None, None, None, None, "3.1", RAW_CONFIG_HASH_SHARED),
                (3, None, None, None, None, "3.1", RAW_CONFIG_HASH_OTHER),
            ],
        )
        connection.executemany(
            "INSERT INTO bgc_record("
            "id,gbk_id,parent_id,record_number,contig_edge,record_type,"
            "nt_start,nt_stop,product,category,merged) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            [
                (1, 1, None, 1, 0, "region", 1, 100, "NRPS", "NRPS", 0),
                (2, 2, None, 1, 0, "region", 1, 100, "PKS", "PKS", 0),
                (3, 3, None, 1, 0, "region", 1, 100, "RiPP", "RiPP", 0),
            ],
        )
        connection.executemany(
            "INSERT INTO cds("
            "id,gbk_id,nt_start,nt_stop,orf_num,strand,gene_kind,aa_seq) "
            "VALUES(?,?,?,?,?,?,?,?)",
            [
                (1, 1, 1, 90, 1, 1, "biosynthetic", RAW_AA),
                (2, 2, 1, 90, 1, 1, "biosynthetic", RAW_AA[::-1]),
                (3, 3, 1, 90, 1, 1, "biosynthetic", RAW_AA),
            ],
        )
        connection.executemany(
            "INSERT INTO hsp VALUES(?,?,?,?,?,?)",
            [(1, 1, "PF00001", 1, 10, 80.0), (2, 2, "PF00002", 2, 12, 70.0)],
        )
        connection.executemany(
            "INSERT INTO hsp_alignment VALUES(?,?)",
            [(1, RAW_ALIGNMENT), (2, RAW_ALIGNMENT[::-1])],
        )
        connection.commit()
    finally:
        connection.close()


def add_viewer_projection_rows(path: Path) -> None:
    long_nt = RAW_NT * 4096
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "UPDATE gbk SET nt_seq=? WHERE id IN (1,3)", (long_nt,)
        )
        connection.execute(
            "UPDATE gbk SET nt_seq=? WHERE id=2", (long_nt[::-1],)
        )
        connection.execute(
            "UPDATE run SET label='viewer_test_' || id, start_time='start', "
            "end_time='end', duration=1, mode='Cluster', record_type='Region', "
            "weights='mix', alignment_mode='GLOBAL', extend_strategy='LEGACY', "
            "include_singletons=1, cutoffs='0.3', min_bgc_length=0"
        )
        connection.execute(
            "INSERT INTO edge_params(id,weights,alignment_mode,extend_strategy) "
            "VALUES(1,'mix','GLOBAL','LEGACY')"
        )
        connection.execute(
            "INSERT INTO family(id,center_id,newick,cutoff,bin_label,run_id) "
            "VALUES(1,1,'(1,3);',0.3,'mix',1)"
        )
        connection.executemany(
            "INSERT INTO bgc_record_family(record_id,family_id) VALUES(?,1)",
            [(1,), (3,)],
        )
        connection.executemany(
            "INSERT INTO connected_component(id,record_id,cutoff,bin_label,run_id) "
            "VALUES(?,?,0.3,'mix',1)",
            [(1, 1), (2, 3)],
        )
        connection.executemany(
            "INSERT INTO distance VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                (1, 3, 0.1, 0.9, 0.8, 0.7, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 0, 1, 0, 1),
                (1, 2, 0.2, 0.8, 0.7, 0.6, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 0, 1, 0, 1),
            ],
        )
        connection.executemany(
            "INSERT INTO scanned_cds(cds_id) VALUES(?)", [(1,), (2,), (3,)]
        )
        connection.commit()
    finally:
        connection.close()


def create_viewer_assets(tool_root: Path) -> str:
    queries = (
        "SELECT * FROM run",
        "SELECT cc.id, family.id, family.center_id, bgc_record_family.record_id, gbk.path FROM family",
        "SELECT DISTINCT cc1.id, cc2.id FROM connected_component AS cc1",
        "SELECT DISTINCT connected_component.id FROM connected_component",
        "SELECT bgc_record.id, gbk.path, bgc_record.record_type,",
        "SELECT hsp.cds_id, hsp.accession, hsp.env_start, hsp.env_stop, hsp.bit_score FROM hsp",
        "SELECT cds.gbk_id, cds.orf_num, cds.strand, cds.nt_start, cds.nt_stop, cds.id FROM cds",
        "SELECT gbk.id, gbk.description, length(gbk.nt_seq), gbk.hash, gbk.path,",
        "SELECT distance.record_a_id, distance.record_b_id, distance.distance FROM distance",
        "SELECT distance.record_a_id, distance.record_b_id, distance.lcs_domain_a_start,",
        "SELECT family.newick FROM family WHERE family.id ==",
        "SELECT gbk.organism, COUNT(gbk.organism) FROM gbk",
        "SELECT bgc_record.product, COUNT(bgc_record.product) as c",
        "SELECT gbk.organism, gbk.path, family.id, family.bin_label FROM gbk",
    )
    index_text = "\n".join(
        [
            "CREATE TABLE rec_ids (rec_id int)",
            "CREATE TABLE gbk_ids (gbk_id int)",
            "CREATE TABLE cds_ids (cds_id int)",
            *(f"window.db.exec(`{query}`);" for query in queries),
        ]
    )
    script_text = (
        "window.db.exec(`SELECT distance.record_a_id, distance.record_b_id, "
        "distance.distance FROM distance`);"
    )
    (tool_root / "index.html").write_text(index_text, encoding="utf-8")
    script_path = tool_root / "html_content" / "js" / "bigscape.js"
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(script_text, encoding="utf-8")
    return hashlib.sha256(script_text.encode("utf-8")).hexdigest()


class BigscapePublicDatabaseTests(unittest.TestCase):
    def test_sanitized_copy_is_loss_minimized_redacted_and_source_immutable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "big_scape.db"
            create_source_database(source)
            source_checksum = file_sha256(source)
            source_bytes = source.read_bytes()
            with sqlite3.connect(source) as raw:
                source_schema = schema_signature(raw)
                source_counts = row_counts(raw)
                source_nt_lengths = dict(raw.execute("SELECT id,length(nt_seq) FROM gbk"))
                source_hashes = dict(raw.execute("SELECT id,hash FROM gbk"))

            exported = sanitize_bigscape_database(source)

            self.assertFalse(exported.reused)
            self.assertEqual(exported.public_path, source.parent / "public" / PUBLIC_BIGSCAPE_DATABASE_FILENAME)
            self.assertEqual((exported.dataset_paths, exported.reference_paths, exported.query_paths), (1, 1, 1))
            self.assertEqual(file_sha256(source), source_checksum)
            self.assertEqual(source.read_bytes(), source_bytes)

            public_bytes = exported.public_path.read_bytes()
            for secret in [
                RAW_DATASET_PATH,
                RAW_REFERENCE_PATH,
                RAW_QUERY_PATH,
                RAW_NT,
                RAW_AA,
                RAW_ALIGNMENT,
                RAW_HASH_SHARED,
                RAW_HASH_OTHER,
                RAW_CONFIG_HASH_SHARED,
                RAW_CONFIG_HASH_OTHER,
                "/data/jobs/",
                "/home/",
            ]:
                self.assertNotIn(secret.encode("utf-8"), public_bytes, secret)

            with sqlite3.connect(exported.public_path) as public:
                self.assertEqual(public.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                self.assertEqual(list(public.execute("PRAGMA foreign_key_check")), [])
                self.assertEqual(public.execute("PRAGMA user_version").fetchone()[0], 7)
                self.assertEqual(schema_signature(public), source_schema)
                self.assertEqual(row_counts(public), source_counts)

                marker = public.execute(
                    f'SELECT export_version,path_policy,dataset_paths,reference_paths,query_paths '
                    f'FROM "{PUBLIC_EXPORT_TABLE}"'
                ).fetchall()
                self.assertEqual(
                    marker,
                    [(PUBLIC_EXPORT_VERSION, PUBLIC_BIGSCAPE_PATH_POLICY, 1, 1, 1)],
                )

                public_paths = dict(public.execute("SELECT id,path FROM gbk ORDER BY id"))
                self.assertEqual(len(set(public_paths.values())), 3)
                self.assertTrue(public_paths[1].startswith("inputs/dataset/"))
                self.assertEqual(
                    public_paths[2],
                    "inputs/reference/mibig_antismash_3.1_gbk/"
                    "reference_00000002.gbk",
                )
                self.assertTrue(public_paths[3].startswith("inputs/query/"))
                for value in public_paths.values():
                    self.assertFalse(value.startswith("/"))
                    self.assertNotIn("..", Path(value).parts)
                    self.assertNotIn("\\", value)
                self.assertFalse(any(name in " ".join(public_paths.values()) for name in [
                    "genome_a.gbk",
                    "BGC0000001.gbk",
                    "query_input.gbk",
                ]))

                public_hashes = dict(public.execute("SELECT id,hash FROM gbk ORDER BY id"))
                self.assertEqual(public_hashes[1], public_hashes[3])
                self.assertNotEqual(public_hashes[1], public_hashes[2])
                self.assertNotEqual(public_hashes[1], source_hashes[1])
                self.assertTrue(all(value.startswith("cwpub_") for value in public_hashes.values()))

                public_config_hashes = dict(
                    public.execute("SELECT id,config_hash FROM run ORDER BY id")
                )
                self.assertEqual(public_config_hashes[1], public_config_hashes[2])
                self.assertNotEqual(public_config_hashes[1], public_config_hashes[3])
                self.assertTrue(
                    all(value.startswith("cwpub_") for value in public_config_hashes.values())
                )
                run_reference_dir, mibig_version = public.execute(
                    "SELECT reference_dir,mibig_version FROM run WHERE id=1"
                ).fetchone()
                self.assertEqual(run_reference_dir, "inputs/reference")
                self.assertIn(run_reference_dir, public_paths[2])
                self.assertIn(
                    f"mibig_antismash_{mibig_version}_gbk", public_paths[2]
                )

                self.assertEqual(
                    dict(public.execute("SELECT id,length(nt_seq) FROM gbk")),
                    source_nt_lengths,
                )
                self.assertTrue(
                    all(kind == "blob" for (kind,) in public.execute("SELECT typeof(nt_seq) FROM gbk"))
                )
                self.assertEqual(
                    public.execute("SELECT COUNT(*) FROM cds WHERE aa_seq != ''").fetchone()[0],
                    0,
                )
                self.assertEqual(
                    public.execute(
                        "SELECT COUNT(*) FROM hsp_alignment WHERE alignment != ''"
                    ).fetchone()[0],
                    0,
                )

    def test_repeated_export_reuses_identical_valid_derivative(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "data_sqlite.db"
            create_source_database(source)
            first = sanitize_bigscape_database(source)
            first_checksum = file_sha256(first.public_path)
            first_mtime = first.public_path.stat().st_mtime_ns

            second = sanitize_bigscape_database(source)

            self.assertTrue(second.reused)
            self.assertEqual(second.public_path, first.public_path)
            self.assertEqual(file_sha256(second.public_path), first_checksum)
            self.assertEqual(second.public_path.stat().st_mtime_ns, first_mtime)
            self.assertEqual(
                (second.dataset_paths, second.reference_paths, second.query_paths),
                (1, 1, 1),
            )

    def test_compact_viewer_projection_is_deterministic_attested_and_source_immutable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "big_scape.db"
            create_source_database(source)
            add_viewer_projection_rows(source)
            script_digest = create_viewer_assets(source.parent)
            raw_checksum = file_sha256(source)
            raw_bytes = source.read_bytes()

            with mock.patch.object(
                bigscape_public_db_module,
                "_BIGSCAPE_200_JS_SHA256",
                script_digest,
            ):
                exported = sanitize_bigscape_database(source)
                self.assertIsNotNone(exported.viewer_path)
                viewer = exported.viewer_path
                assert viewer is not None
                self.assertEqual(
                    viewer,
                    source.parent / "public" / "clusterweave_viewer.sqlite",
                )
                self.assertEqual(exported.viewer_bytes, viewer.stat().st_size)
                self.assertLess(exported.viewer_bytes, exported.public_bytes)
                full_checksum = file_sha256(exported.public_path)
                viewer_checksum = file_sha256(viewer)

                checked = validate_public_bigscape_viewer_database(viewer)
                self.assertEqual(checked["reachable_records"], 2)
                self.assertEqual(checked["gbk"], 2)
                self.assertEqual(checked["distance"], 1)
                self.assertEqual(checked["viewer_bytes"], exported.viewer_bytes)
                self.assertTrue(public_bigscape_viewer_database_valid(viewer))

                reused = create_public_bigscape_viewer_database(exported.public_path)
                self.assertIsNotNone(reused)
                assert reused is not None
                self.assertTrue(reused[1])
                self.assertEqual(file_sha256(viewer), viewer_checksum)

                regenerated = create_public_bigscape_viewer_database(
                    exported.public_path, force=True
                )
                self.assertIsNotNone(regenerated)
                assert regenerated is not None
                self.assertFalse(regenerated[1])
                self.assertEqual(file_sha256(viewer), viewer_checksum)
                self.assertEqual(file_sha256(exported.public_path), full_checksum)

                with sqlite3.connect(exported.public_path) as public:
                    public_lengths = dict(public.execute(
                        "SELECT id,length(nt_seq) FROM gbk WHERE id IN (1,3)"
                    ))
                with sqlite3.connect(viewer) as compact:
                    self.assertEqual(
                        compact.execute("PRAGMA integrity_check").fetchone()[0],
                        "ok",
                    )
                    self.assertEqual(list(compact.execute("PRAGMA foreign_key_check")), [])
                    self.assertEqual(compact.execute("PRAGMA freelist_count").fetchone()[0], 0)
                    self.assertEqual(
                        [row[0] for row in compact.execute("SELECT id FROM bgc_record ORDER BY id")],
                        [1, 3],
                    )
                    self.assertEqual(
                        [row[0] for row in compact.execute("SELECT id FROM gbk ORDER BY id")],
                        [1, 3],
                    )
                    self.assertEqual(
                        [row[0] for row in compact.execute("SELECT id FROM cds ORDER BY id")],
                        [1, 3],
                    )
                    self.assertEqual(
                        [row[0] for row in compact.execute("SELECT id FROM hsp ORDER BY id")],
                        [1],
                    )
                    self.assertEqual(
                        list(compact.execute("SELECT hsp_id,alignment FROM hsp_alignment")),
                        [(1, "")],
                    )
                    self.assertEqual(
                        [row[0] for row in compact.execute("SELECT cds_id FROM scanned_cds ORDER BY cds_id")],
                        [1, 3],
                    )
                    self.assertEqual(
                        list(compact.execute(
                            "SELECT record_a_id,record_b_id FROM distance"
                        )),
                        [(1, 3)],
                    )
                    self.assertEqual(
                        dict(compact.execute(
                            "SELECT id,length(nt_seq) FROM gbk ORDER BY id"
                        )),
                        public_lengths,
                    )
                    columns = {
                        row[1]: row for row in compact.execute("PRAGMA table_xinfo('gbk')")
                    }
                    self.assertEqual(columns["nt_seq"][6], 2)
                    self.assertEqual(columns["clusterweave_nt_length"][6], 0)
                    self.assertEqual(
                        tuple(row[2] for row in compact.execute(
                            "PRAGMA index_info('record_id_index')"
                        )),
                        ("gbk_id",),
                    )
                    marker = compact.execute(
                        f"SELECT export_version,query_contract,path_policy,"
                        f"reachable_records,gbk_rows,distance_rows FROM "
                        f"{PUBLIC_BIGSCAPE_VIEWER_EXPORT_TABLE}"
                    ).fetchall()
                    self.assertEqual(
                        marker,
                        [(
                            PUBLIC_BIGSCAPE_VIEWER_EXPORT_VERSION,
                            PUBLIC_BIGSCAPE_VIEWER_QUERY_CONTRACT,
                            PUBLIC_BIGSCAPE_VIEWER_PATH_POLICY,
                            2,
                            2,
                            1,
                        )],
                    )

                viewer_bytes = viewer.read_bytes()
                for secret in (
                    RAW_DATASET_PATH, RAW_REFERENCE_PATH, RAW_QUERY_PATH,
                    RAW_NT, RAW_AA, RAW_ALIGNMENT, RAW_HASH_SHARED,
                    RAW_HASH_OTHER, RAW_CONFIG_HASH_SHARED,
                    RAW_CONFIG_HASH_OTHER, "/data/jobs/", "/home/",
                ):
                    self.assertNotIn(secret.encode("utf-8"), viewer_bytes, secret)
                for suffix in ("-wal", "-shm", "-journal"):
                    self.assertFalse(Path(str(viewer) + suffix).exists())

            self.assertEqual(file_sha256(source), raw_checksum)
            self.assertEqual(source.read_bytes(), raw_bytes)

    def test_viewer_is_omitted_when_web_assets_are_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "big_scape.db"
            create_source_database(source)

            exported = sanitize_bigscape_database(source)

            self.assertIsNone(exported.viewer_path)
            self.assertEqual(exported.viewer_bytes, 0)
            self.assertTrue(exported.public_path.is_file())
            self.assertFalse(
                (exported.public_path.parent / "clusterweave_viewer.sqlite").exists()
            )

    def test_viewer_size_cap_fails_closed_without_suppressing_full_export(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "big_scape.db"
            create_source_database(source)
            add_viewer_projection_rows(source)
            script_digest = create_viewer_assets(source.parent)
            raw_checksum = file_sha256(source)

            with mock.patch.object(
                bigscape_public_db_module,
                "_BIGSCAPE_200_JS_SHA256",
                script_digest,
            ):
                exported = sanitize_bigscape_database(
                    source, max_viewer_bytes=4096
                )

            self.assertIsNone(exported.viewer_path)
            self.assertEqual(exported.viewer_bytes, 0)
            self.assertTrue(exported.public_path.is_file())
            self.assertGreater(exported.public_bytes, 4096)
            self.assertEqual(file_sha256(source), raw_checksum)

    def test_viewer_asset_drift_fails_closed_and_preserves_full_export(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "big_scape.db"
            create_source_database(source)
            add_viewer_projection_rows(source)
            script_digest = create_viewer_assets(source.parent)
            raw_checksum = file_sha256(source)

            with mock.patch.object(
                bigscape_public_db_module,
                "_BIGSCAPE_200_JS_SHA256",
                script_digest,
            ):
                first = sanitize_bigscape_database(source)
                assert first.viewer_path is not None
                full_checksum = file_sha256(first.public_path)
                viewer_path = first.viewer_path
                index_path = source.parent / "index.html"
                index_path.write_text(
                    index_path.read_text(encoding="utf-8")
                    + "\nwindow.db.exec(`SELECT * FROM new_contract`);\n",
                    encoding="utf-8",
                )

                second = sanitize_bigscape_database(source)

                self.assertTrue(second.reused)
                self.assertIsNone(second.viewer_path)
                self.assertEqual(second.viewer_bytes, 0)
                self.assertEqual(file_sha256(second.public_path), full_checksum)
                self.assertTrue(viewer_path.is_file())
                self.assertFalse(
                    (viewer_path.parent / VIEWER_SIDECAR_FILENAME).exists()
                )
                self.assertFalse(public_bigscape_viewer_database_valid(viewer_path))

            self.assertEqual(file_sha256(source), raw_checksum)

    def test_viewer_marker_schema_and_sidecar_tampering_fail_attestation(self) -> None:
        for tamper in ("marker", "schema", "sidecar", "source"):
            with self.subTest(tamper=tamper), tempfile.TemporaryDirectory() as tmp:
                source = Path(tmp) / "big_scape.db"
                create_source_database(source)
                add_viewer_projection_rows(source)
                script_digest = create_viewer_assets(source.parent)
                with mock.patch.object(
                    bigscape_public_db_module,
                    "_BIGSCAPE_200_JS_SHA256",
                    script_digest,
                ):
                    exported = sanitize_bigscape_database(source)
                    viewer = exported.viewer_path
                    assert viewer is not None
                    if tamper == "sidecar":
                        (viewer.parent / VIEWER_SIDECAR_FILENAME).write_text(
                            "{}\n", encoding="utf-8"
                        )
                    elif tamper == "source":
                        with sqlite3.connect(exported.public_path) as connection:
                            connection.execute(
                                "UPDATE run SET config_hash=? WHERE id=1",
                                ("cwpub_" + ("0" * 64),),
                            )
                            connection.commit()
                    else:
                        with sqlite3.connect(viewer) as connection:
                            if tamper == "marker":
                                connection.execute(
                                    f"UPDATE {PUBLIC_BIGSCAPE_VIEWER_EXPORT_TABLE} "
                                    "SET query_contract='unsupported'"
                                )
                            else:
                                connection.execute("CREATE TABLE unexpected(value TEXT)")
                            connection.commit()
                    self.assertFalse(
                        public_bigscape_viewer_database_valid(viewer), tamper
                    )

    def test_reuse_validation_repairs_unsafe_config_hash_and_mibig_path(self) -> None:
        mutations = (
            "UPDATE run SET config_hash='raw-config-hash' WHERE id=1",
            "UPDATE gbk SET path='inputs/reference/reference_00000002.gbk' WHERE id=2",
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                source = Path(tmp) / "big_scape.db"
                create_source_database(source)
                first = sanitize_bigscape_database(source)
                with sqlite3.connect(first.public_path) as public:
                    public.execute(mutation)
                    public.commit()

                repaired = sanitize_bigscape_database(source)

                self.assertFalse(repaired.reused)
                with sqlite3.connect(repaired.public_path) as public:
                    config_hash = public.execute(
                        "SELECT config_hash FROM run WHERE id=1"
                    ).fetchone()[0]
                    reference_path = public.execute(
                        "SELECT path FROM gbk WHERE id=2"
                    ).fetchone()[0]
                self.assertRegex(config_hash, r"^cwpub_[0-9a-f]{64}$")
                self.assertIn("/mibig_antismash_3.1_gbk/", reference_path)

    def test_generic_reference_path_does_not_gain_mibig_classification(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "big_scape.db"
            create_source_database(source)
            with sqlite3.connect(source) as raw:
                raw.execute(
                    "UPDATE gbk SET path='/references/generic/reference.gbk' WHERE id=2"
                )
                raw.execute(
                    "UPDATE run SET reference_dir='/references/generic' WHERE id=1"
                )
                raw.commit()

            exported = sanitize_bigscape_database(source)

            with sqlite3.connect(exported.public_path) as public:
                reference_path = public.execute(
                    "SELECT path FROM gbk WHERE id=2"
                ).fetchone()[0]
            self.assertEqual(
                reference_path, "inputs/reference/reference_00000002.gbk"
            )
            self.assertNotIn("mibig_antismash_", reference_path)

    def test_corrupt_source_fails_closed_without_public_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "big_scape.db"
            source.write_bytes(b"SQLite format 3\x00" + b"not-a-database" * 32)
            checksum = file_sha256(source)

            with self.assertRaises(BigscapePublicDatabaseError):
                sanitize_bigscape_database(source)

            self.assertEqual(file_sha256(source), checksum)
            public = source.parent / "public"
            self.assertFalse((public / PUBLIC_BIGSCAPE_DATABASE_FILENAME).exists())
            self.assertFalse(any(public.glob("*.sqlite*")) if public.exists() else False)

    def test_result_policy_accepts_only_exact_generated_database_paths(self) -> None:
        exact = [
            "data/results/demo/big_scape/public/clusterweave_public.sqlite",
            "data/results/demo/big_scape/output_files/public/clusterweave_public.sqlite",
            "data/results/demo/bigscape/public/clusterweave_public.sqlite",
            "data/results/demo/big-scape/public/clusterweave_public.sqlite",
        ]
        for path in exact:
            with self.subTest(exact=path):
                self.assertTrue(result_is_public_bigscape_database(path))
                self.assertTrue(result_path_public_shape(path))

        denied = [
            "data/results/demo/big_scape/big_scape.db",
            "data/results/demo/big_scape/output_files/data_sqlite.db",
            "data/results/demo/big_scape/public/data_sqlite.db",
            "data/results/demo/big_scape/public/clusterweave_public.db",
            "data/results/demo/big_scape/public/clusterweave_public.sqlite3",
            "data/results/demo/big_scape/public/clusterweave_public.sqlite-wal",
            "data/results/demo/big_scape/public/clusterweave_public.sqlite-shm",
            "data/results/demo/big_scape/public/clusterweave_public.sqlite-journal",
            "data/results/demo/big_scape/public/.clusterweave_public.sqlite.source.json",
            "data/results/demo/big_scape/public/clusterweave_public.sqlite.bak",
            "data/results/demo/big_scape/public/CLUSTERWEAVE_PUBLIC.SQLITE",
            "data/results/demo/BIG_SCAPE/public/clusterweave_public.sqlite",
            "data/results/demo/big_scape/public/nested/clusterweave_public.sqlite",
        ]
        for path in denied:
            with self.subTest(denied=path):
                self.assertFalse(result_is_public_bigscape_database(path))
                self.assertFalse(result_path_public_shape(path))

        viewer_exact = [
            "data/results/demo/big_scape/public/clusterweave_viewer.sqlite",
            "data/results/demo/big_scape/output_files/public/clusterweave_viewer.sqlite",
            "data/results/demo/bigscape/public/clusterweave_viewer.sqlite",
            "data/results/demo/big-scape/public/clusterweave_viewer.sqlite",
        ]
        for path in viewer_exact:
            with self.subTest(viewer=path):
                self.assertTrue(result_is_public_bigscape_viewer_database(path))
                self.assertFalse(result_is_public_bigscape_database(path))
                self.assertFalse(result_path_public_shape(path))
        for path in [
            "data/results/demo/big_scape/public/clusterweave_viewer.sqlite-wal",
            "data/results/demo/big_scape/public/clusterweave_viewer.sqlite.bak",
            "data/results/demo/big_scape/public/nested/clusterweave_viewer.sqlite",
            "data/results/demo/big_scape/public/CLUSTERWEAVE_VIEWER.SQLITE",
            "data/results/demo/BIG_SCAPE/public/clusterweave_viewer.sqlite",
        ]:
            with self.subTest(viewer_denied=path):
                self.assertFalse(result_is_public_bigscape_viewer_database(path))


if __name__ == "__main__":
    unittest.main()
