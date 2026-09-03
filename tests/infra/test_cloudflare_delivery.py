from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from scripts.infra.validate_cloudflare_delivery import (
    DeliveryContractError,
    validate_plan,
    validate_repository,
)
from scripts.infra.verify_http_delivery import IMMUTABLE, HttpDeliveryError, verify_object


ROOT = Path(__file__).resolve().parents[2]
RELEASE = (
    ROOT
    / "contracts/release/v1/fixtures/release"
    / "searise-europe-v1.0.0-20260810-c096aeab4e09"
)
PMTILES = RELEASE / "layers/ssp2-45/2050.pmtiles"
COG = RELEASE / "analysis/ssp2-45/2050.tif"
ALLOWED_ORIGIN = "https://app-fixture.example.invalid"


class DeliveryHandler(BaseHTTPRequestHandler):
    server_version = "SeaRiseFixture/1"
    protocol_version = "HTTP/1.1"
    objects = {
        "/releases/fixture/layers/ssp2-45/2050.pmtiles": (
            PMTILES.read_bytes(),
            "application/vnd.pmtiles",
            IMMUTABLE,
        ),
        "/releases/fixture/analysis/ssp2-45/2050.tif": (
            COG.read_bytes(),
            "image/tiff; application=geotiff; profile=cloud-optimized",
            IMMUTABLE,
        ),
        "/release.json": (
            b'{"dataReleaseId":"fixture"}\n',
            "application/json",
            "no-store",
        ),
    }

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def _cors(self) -> dict[str, str]:
        if self.headers.get("Origin") != ALLOWED_ORIGIN:
            return {}
        return {
            "Access-Control-Allow-Origin": ALLOWED_ORIGIN,
            "Access-Control-Allow-Methods": "GET, HEAD",
            "Access-Control-Allow-Headers": "If-Match, If-None-Match, Range",
            "Access-Control-Expose-Headers": (
                "Accept-Ranges, Cache-Control, Content-Length, Content-Range, "
                "Content-Type, ETag"
            ),
        }

    def do_OPTIONS(self) -> None:  # noqa: N802 - HTTP handler contract
        headers = self._cors()
        self.send_response(204)
        for name, value in headers.items():
            self.send_header(name, value)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_HEAD(self) -> None:  # noqa: N802 - HTTP handler contract
        self._serve(head=True)

    def do_GET(self) -> None:  # noqa: N802 - HTTP handler contract
        self._serve(head=False)

    def _serve(self, *, head: bool) -> None:
        record = self.objects.get(self.path)
        if record is None:
            self.send_error(404)
            return
        body, media_type, cache_control = record
        etag = f'"{hashlib.sha256(body).hexdigest()}"'
        start, end = 0, len(body) - 1
        status = 200
        range_value = self.headers.get("Range")
        if range_value:
            if range_value == f"bytes={len(body)}-":
                self.send_response(416)
                for name, value in self._cors().items():
                    self.send_header(name, value)
                self.send_header("Content-Range", f"bytes */{len(body)}")
                self.send_header("Cache-Control", cache_control)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            match = __import__("re").fullmatch(r"bytes=(\d+)-(\d+)", range_value)
            if match is None:
                self.send_error(400)
                return
            start, end = int(match.group(1)), min(int(match.group(2)), len(body) - 1)
            status = 206
        payload = body[start : end + 1]
        self.send_response(status)
        headers = {
            **self._cors(),
            "Accept-Ranges": "bytes",
            "Cache-Control": cache_control,
            "Content-Length": str(len(payload)),
            "Content-Type": media_type,
            "ETag": etag,
        }
        if status == 206:
            headers["Content-Range"] = f"bytes {start}-{end}/{len(body)}"
        for name, value in headers.items():
            self.send_header(name, value)
        self.end_headers()
        if not head:
            self.wfile.write(payload)


class CloudflareRepositoryContractTests(unittest.TestCase):
    def test_repository_contract_is_complete_and_isolated(self) -> None:
        contract = validate_repository(ROOT)

        self.assertFalse(contract["safety"]["publicationAuthorized"])
        self.assertTrue(contract["safety"]["publicationRequiresIssue64Gate"])
        self.assertTrue(contract["safety"]["dataUploadAuthoritySeparated"])
        self.assertEqual(set(contract["environments"]), {"fixture", "staging", "production"})
        self.assertIn("every versioned object", contract["http"]["visualPmtilesRationale"])

    def test_wildcard_origin_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory) / "repo"
            shutil.copytree(ROOT / "infra", repository / "infra")
            variables = repository / "infra/cloudflare/environments/fixture.tfvars"
            variables.write_text(
                variables.read_text(encoding="utf-8").replace(
                    "https://app-fixture.example.invalid", "*"
                ),
                encoding="utf-8",
            )
            with self.assertRaises(DeliveryContractError):
                validate_repository(repository)

    def test_destructive_or_secret_plan_fails_closed(self) -> None:
        invalid = {
            "format_version": "1.2",
            "resource_changes": [
                {
                    "address": "cloudflare_r2_bucket.release",
                    "type": "cloudflare_r2_bucket",
                    "change": {"actions": ["delete", "create"]},
                }
            ],
            "variables": {"api_token": {"value": "do-not-record"}},
        }
        with tempfile.TemporaryDirectory() as directory:
            plan = Path(directory) / "plan.json"
            plan.write_text(json.dumps(invalid), encoding="utf-8")
            with self.assertRaisesRegex(
                DeliveryContractError, "destructive plan|secret-like"
            ):
                validate_plan(plan)

    def test_create_only_plan_emits_redacted_summary(self) -> None:
        valid = {
            "format_version": "1.2",
            "resource_changes": [
                {
                    "address": "cloudflare_r2_bucket.release",
                    "type": "cloudflare_r2_bucket",
                    "change": {"actions": ["create"]},
                }
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            plan = Path(directory) / "plan.json"
            summary = Path(directory) / "summary.json"
            plan.write_text(json.dumps(valid), encoding="utf-8")
            document = validate_plan(plan, summary)

            self.assertEqual(document["secretScan"], "passed")
            self.assertFalse(document["publicationAuthorized"])
            self.assertEqual(json.loads(summary.read_text())["planSha256"], document["planSha256"])


class HttpDeliveryContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), DeliveryHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def test_versioned_pmtiles_get_head_range_cors_etag_and_immutable_cache(self) -> None:
        result = verify_object(
            self.base_url,
            "/releases/fixture/layers/ssp2-45/2050.pmtiles",
            origin=ALLOWED_ORIGIN,
            denied_origin="https://denied.example.invalid",
            media_type="application/vnd.pmtiles",
            cache_control=IMMUTABLE,
        )
        self.assertEqual(result["status"], "passed")

    def test_cog_get_head_range_cors_etag_and_immutable_cache(self) -> None:
        result = verify_object(
            self.base_url,
            "/releases/fixture/analysis/ssp2-45/2050.tif",
            origin=ALLOWED_ORIGIN,
            denied_origin="https://denied.example.invalid",
            media_type="image/tiff; application=geotiff; profile=cloud-optimized",
            cache_control=IMMUTABLE,
        )
        self.assertEqual(result["status"], "passed")

    def test_non_release_path_is_rejected_before_network(self) -> None:
        with self.assertRaises(HttpDeliveryError):
            verify_object(
                self.base_url,
                "/latest/data.tif",
                origin=ALLOWED_ORIGIN,
                denied_origin="https://denied.example.invalid",
                media_type="image/tiff",
                cache_control=IMMUTABLE,
            )

    def test_unversioned_release_alias_is_explicitly_no_store(self) -> None:
        result = verify_object(
            self.base_url,
            "/release.json",
            origin=ALLOWED_ORIGIN,
            denied_origin="https://denied.example.invalid",
            media_type="application/json",
            cache_control="no-store",
            versioned=False,
        )
        self.assertEqual(result["status"], "passed")


if __name__ == "__main__":
    unittest.main()
