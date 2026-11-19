"""Tests for the Azure Blob Storage connection, against a stand-in server.

    python3 tools/test_azure.py

No network and no Azure account: every upload goes to tools/fake_azure.py on
this computer. These prove the app checks a link properly, sends what Azure's
Put Blob documentation describes, keeps the folders, and turns each failure
into the right plain message.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

if __name__ == "__main__":
    import start  # noqa: E402
    start.ensure_environment(__file__)

from fake_azure import CONTAINER, FakeAzure  # noqa: E402

from studio import storage  # noqa: E402

REAL = ("https://examplestorage.blob.core.windows.net/campaign-studio"
        "?sv=2021-08-06&sr=c&sp=cw&se=2099-01-01T00:00:00Z&sig=abc")


class LinkChecks(unittest.TestCase):
    """What's caught before anything is sent."""

    def setUp(self):
        self.saved = os.environ.pop("AZURE_TEST_HOST", None)

    def tearDown(self):
        if self.saved is not None:
            os.environ["AZURE_TEST_HOST"] = self.saved

    def refused(self, link, message):
        with self.assertRaises(storage.StorageError) as e:
            storage.parse(link)
        self.assertEqual(str(e.exception), message)

    def test_a_real_container_link_is_accepted(self):
        p = storage.parse(REAL)
        self.assertEqual((p["account"], p["container"]), ("examplestorage", "campaign-studio"))
        self.assertTrue(p["expires"].startswith("2099-01-01"))

    def test_not_a_link(self):
        self.refused("hello", storage.NOT_A_LINK)

    def test_a_link_without_a_signature(self):
        self.refused(REAL.split("&sig=")[0], storage.NOT_A_LINK)

    def test_another_website(self):
        self.refused(REAL.replace(".blob.core.windows.net", ".example.com"), storage.NOT_AZURE)

    def test_plain_http_to_azure(self):
        self.refused(REAL.replace("https://", "http://"), storage.NOT_AZURE)

    def test_a_link_to_one_file(self):
        self.refused(REAL.replace("sr=c", "sr=b"), storage.ONE_FILE)
        self.refused(REAL.replace("/campaign-studio?", "/campaign-studio/ad.png?"), storage.ONE_FILE)

    def test_a_link_to_the_whole_account(self):
        self.refused(REAL.replace("/campaign-studio?", "/?"), storage.NO_CONTAINER)

    def test_a_read_only_link(self):
        self.refused(REAL.replace("sp=cw", "sp=rl"), storage.NO_WRITE)

    def test_an_expired_link(self):
        self.refused(REAL.replace("2099-01-01", "2020-01-01"), storage.EXPIRED)

    def test_the_token_never_reaches_the_panel(self):
        os.environ[storage.ENV_KEY] = REAL
        try:
            shown = json.dumps(storage.describe())
        finally:
            os.environ.pop(storage.ENV_KEY)
        self.assertIn("campaign-studio", shown)
        self.assertNotIn("sig", shown)
        self.assertNotIn("abc", shown)


class Uploads(unittest.TestCase):
    """What's sent, and what each refusal becomes."""

    def setUp(self):
        self.saved = {k: os.environ.get(k) for k in ("AZURE_TEST_HOST", storage.ENV_KEY)}
        os.environ.pop(storage.ENV_KEY, None)
        self.fake = FakeAzure().start()
        os.environ["AZURE_TEST_HOST"] = self.fake.host
        self.wait, storage.RETRY_WAIT = storage.RETRY_WAIT, 0
        self.dir = Path(tempfile.mkdtemp())
        (self.dir / "ad.png").write_bytes(b"\x89PNG fake")
        (self.dir / "report.json").write_text("{}")
        self.files = [("daylight-mist/1x1/US-en.png", self.dir / "ad.png"), ("report.json", self.dir / "report.json")]

    def tearDown(self):
        self.fake.stop()
        storage.RETRY_WAIT = self.wait
        for k, v in self.saved.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v

    def fails(self, message, link=None, **kw):
        with self.assertRaises(storage.StorageError) as e:
            storage.send("long-light", self.files, link or self.fake.link(**kw))
        self.assertEqual(str(e.exception), message)

    def test_check_writes_one_small_file(self):
        storage.check(self.fake.link())
        self.assertEqual(list(self.fake.blobs), ["campaign-studio-check.txt"])

    def test_send_keeps_the_folders_and_types(self):
        self.assertEqual(storage.send("long-light", self.files, self.fake.link()), 2)
        self.assertEqual(sorted(self.fake.blobs), ["long-light/daylight-mist/1x1/US-en.png", "long-light/report.json"])
        self.assertEqual(self.fake.blobs["long-light/daylight-mist/1x1/US-en.png"], b"\x89PNG fake")
        sent = {r["path"]: r["headers"] for r in self.fake.requests}
        png = sent[f"/{CONTAINER}/long-light/daylight-mist/1x1/US-en.png"]
        self.assertEqual(png["x-ms-blob-type"], "BlockBlob")
        self.assertEqual(png["x-ms-version"], storage.API_VERSION)
        self.assertEqual(png["content-type"], "image/png")
        self.assertEqual(sent[f"/{CONTAINER}/long-light/report.json"]["content-type"], "application/json")

    def test_sending_twice_replaces(self):
        storage.send("long-light", self.files, self.fake.link())
        storage.send("long-light", self.files, self.fake.link())
        self.assertEqual(len(self.fake.blobs), 2)

    def test_uses_the_saved_link(self):
        os.environ[storage.ENV_KEY] = self.fake.link()
        self.assertEqual(storage.send("long-light", self.files), 2)

    def test_not_connected(self):
        with self.assertRaises(storage.StorageError) as e:
            storage.send("long-light", self.files)
        self.assertEqual(str(e.exception), storage.NOT_CONNECTED)

    def test_wrong_signature(self):
        self.fails(storage.REFUSED, sig="wrong")

    def test_no_such_container(self):
        self.fails(storage.NOT_FOUND, container="gone")

    def test_azure_says_no_write_permission(self):
        self.fake.fail_with = (403, "AuthorizationPermissionMismatch")
        self.fails(storage.NO_WRITE)

    def test_azure_says_the_link_has_run_out(self):
        self.fake.fail_with = (403, "AuthenticationFailed")
        # The stand-in's message for a signature outside its time window, as Azure words it.
        self.fake.server.RequestHandlerClass._reply.__defaults__ = ("", "Signed expiry time has to be after signed start time")
        try:
            self.fails(storage.EXPIRED)
        finally:
            self.fake.server.RequestHandlerClass._reply.__defaults__ = ("", "")

    def test_one_server_hiccup_is_retried(self):
        self.fake.fail_once = (503, "ServerBusy")
        self.assertEqual(storage.send("long-light", self.files, self.fake.link()), 2)

    def test_a_busy_service(self):
        self.fake.fail_with = (429, "ServerBusy")
        self.fails(storage.BUSY)

    def test_a_broken_service(self):
        self.fake.fail_with = (500, "InternalError")
        self.fails(storage.SERVER)

    def test_unreachable(self):
        link = self.fake.link()
        self.fake.stop()
        self.fails(storage.UNREACHABLE, link=link)
        self.fake = FakeAzure().start()  # so tearDown has something to stop


if __name__ == "__main__":
    unittest.main(verbosity=1)
