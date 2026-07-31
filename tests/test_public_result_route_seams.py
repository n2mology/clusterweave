from __future__ import annotations

from pathlib import Path
import sys
import types
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
if str(WEB) not in sys.path:
    sys.path.insert(0, str(WEB))

import public_result_backend  # noqa: E402
from public_result_backend import PublicResultContext, resolve_public_job  # noqa: E402
from public_result_http import handle_public_result_get  # noqa: E402


PUBLIC_ID = "R07ExplicitContext001X"


class _MissingResultApi:
    def __init__(self) -> None:
        self.requested: list[str] = []

    def resolve_public_job(self, public_id: str) -> None:
        self.requested.append(public_id)
        return None


class _Handler:
    def __init__(self) -> None:
        self.not_found: list[str] = []

    def _not_found(self, message: str) -> None:
        self.not_found.append(message)


class PublicResultRouteSeamTests(unittest.TestCase):
    def test_backend_lookup_uses_only_the_supplied_store_context(self) -> None:
        first_job = {"id": "first", "public_run_id": PUBLIC_ID}
        second_job = {"id": "second", "public_run_id": PUBLIC_ID}

        def context_for(job: dict[str, object]) -> PublicResultContext:
            return PublicResultContext(
                api=None,
                read_job=lambda job_id: job if job_id == job["id"] else None,
                list_job_summaries=lambda: [dict(job)],
            )

        self.assertEqual(
            resolve_public_job(PUBLIC_ID, context_for(first_job)),
            first_job,
        )
        self.assertEqual(
            resolve_public_job(PUBLIC_ID, context_for(second_job)),
            second_job,
        )

    def test_backend_one_argument_adapter_loads_the_standalone_store_lazily(self) -> None:
        public_id = "R07StandaloneContext1X"
        job = {"id": "standalone", "public_run_id": public_id}
        standalone_store = types.SimpleNamespace(
            read_job=lambda job_id: job if job_id == job["id"] else None,
            list_job_summaries=lambda: [dict(job)],
        )

        with (
            mock.patch.object(public_result_backend, "_CONFIGURED_CONTEXT", None),
            mock.patch.dict(sys.modules, {"job_store": standalone_store}),
        ):
            self.assertEqual(resolve_public_job(public_id), job)

    def test_http_router_uses_the_supplied_context_without_reverse_import(self) -> None:
        api = _MissingResultApi()
        context = PublicResultContext(
            api=api,
            read_job=lambda _job_id: None,
            list_job_summaries=lambda: [],
        )
        handler = _Handler()

        self.assertFalse(
            handle_public_result_get(handler, "/unrelated", {}, context)
        )
        self.assertTrue(
            handle_public_result_get(
                handler,
                f"/api/results/{PUBLIC_ID}",
                {},
                context,
            )
        )
        self.assertEqual(api.requested, [PUBLIC_ID])
        self.assertEqual(handler.not_found, ["Result not found"])


if __name__ == "__main__":
    unittest.main()
