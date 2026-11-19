"""Tests for the Adobe Firefly adapter, against a stand-in server.

    python3 tools/test_firefly.py

No network and no Adobe account: every request goes to tools/fake_firefly.py on
this computer. These prove the adapter sends what Adobe's documentation
describes and turns each failure into the right plain message. They can't
prove the documentation matches the live service.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

if __name__ == "__main__":
    # Run inside the app's own Python environment (.venv), setting it up if needed.
    import start  # noqa: E402
    start.ensure_environment(__file__)

from fake_firefly import CLIENT_ID, CLIENT_SECRET, TOKEN, FakeFirefly  # noqa: E402

from studio import config, providers  # noqa: E402
from studio.providers import firefly  # noqa: E402
from studio.providers.base import ProviderError  # noqa: E402

VARS = ("FIREFLY_CLIENT_ID", "FIREFLY_CLIENT_SECRET", "FIREFLY_MODEL_VERSION", "FIREFLY_SCOPES",
        "FIREFLY_IMS_URL", "FIREFLY_API_URL")


class FireflyCase(unittest.TestCase):
    def setUp(self):
        self.saved = {k: os.environ.get(k) for k in VARS}
        for k in VARS:
            os.environ.pop(k, None)
        self.fake = FakeFirefly().start()
        self.fake.polls_before_done = 0
        os.environ.update(FIREFLY_CLIENT_ID=CLIENT_ID, FIREFLY_CLIENT_SECRET=CLIENT_SECRET,
                          FIREFLY_IMS_URL=self.fake.url, FIREFLY_API_URL=self.fake.url)
        self.waits = (firefly.RETRY_WAIT, firefly.POLL_EVERY, firefly.POLL_LIMIT)
        firefly.RETRY_WAIT = 0
        firefly.POLL_EVERY = 0
        firefly.forget_tokens()

    def tearDown(self):
        self.fake.stop()
        firefly.RETRY_WAIT, firefly.POLL_EVERY, firefly.POLL_LIMIT = self.waits
        firefly.forget_tokens()
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def make(self, size: int = 512, seed: int = 123456789):
        return firefly.FireflyProvider().generate_image("A bottle on a beach.", size, seed, {})

    def fails_with(self, start: str, **kw) -> str:
        with self.assertRaises(ProviderError) as cm:
            self.make(**kw)
        self.assertTrue(str(cm.exception).startswith(start), f"got: {cm.exception}")
        return str(cm.exception)


class Requests(FireflyCase):
    def test_token_request(self):
        self.make()
        (req,) = self.fake.seen("token")
        self.assertEqual(req["method"], "POST")
        self.assertEqual(req["path"], "/ims/token/v3")
        self.assertTrue(req["headers"]["content-type"].startswith("application/x-www-form-urlencoded"))
        self.assertEqual(req["form"], {
            "grant_type": "client_credentials", "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET,
            "scope": "openid,AdobeID,session,additional_info,read_organizations,firefly_api,ff_apis"})

    def test_scope_override(self):
        os.environ["FIREFLY_SCOPES"] = "openid,AdobeID,firefly_api,ff_apis"
        self.make()
        self.assertEqual(self.fake.seen("token")[0]["form"]["scope"], "openid,AdobeID,firefly_api,ff_apis")

    def test_token_reused_then_refetched_after_expiry(self):
        self.make()
        self.make()
        self.assertEqual(len(self.fake.seen("token")), 1, "the token should be reused")
        firefly.forget_tokens()
        self.fake.expires_in = 30   # under the one-minute margin, so already stale
        self.make()
        self.make()
        self.assertEqual(len(self.fake.seen("token")), 3, "an expired token should be fetched again")

    def test_generate_request(self):
        self.make(seed=123456789)
        (req,) = self.fake.seen("generate")
        self.assertEqual(req["method"], "POST")
        self.assertEqual(req["path"], "/v3/images/generate-async")
        self.assertEqual(req["headers"]["x-api-key"], CLIENT_ID)
        self.assertEqual(req["headers"]["authorization"], f"Bearer {TOKEN}")
        self.assertTrue(req["headers"]["content-type"].startswith("application/json"))
        self.assertEqual(req["json"], {
            "prompt": "A bottle on a beach.", "numVariations": 1,
            "size": {"width": 2048, "height": 2048}, "contentClass": "photo",
            "seeds": [1 + 123456789 % 100000]})
        self.assertNotIn("x-model-version", req["headers"])

    def test_model_version_sent_only_when_set(self):
        os.environ["FIREFLY_MODEL_VERSION"] = "image4_standard"
        self.make()
        self.assertEqual(self.fake.seen("generate")[0]["headers"]["x-model-version"], "image4_standard")

    def test_unsupported_model_version_stops_before_any_request(self):
        os.environ["FIREFLY_MODEL_VERSION"] = "image5"
        self.fails_with("FIREFLY_MODEL_VERSION is set to 'image5'.")
        self.assertEqual(self.fake.requests, [])

    def test_status_gets_both_headers_and_download_gets_neither(self):
        self.make()
        status = self.fake.seen("status")[0]
        self.assertEqual(status["method"], "GET")
        self.assertEqual(status["headers"]["x-api-key"], CLIENT_ID)
        self.assertEqual(status["headers"]["authorization"], f"Bearer {TOKEN}")
        image = self.fake.seen("image")[0]
        self.assertNotIn("authorization", image["headers"])
        self.assertNotIn("x-api-key", image["headers"])

    def test_secret_goes_only_to_sign_in(self):
        self.make()
        for req in self.fake.requests:
            if req["endpoint"] != "token":
                self.assertNotIn(CLIENT_SECRET.encode(), req["raw"])
                self.assertNotIn(CLIENT_SECRET, str(req["headers"]))


class Results(FireflyCase):
    def test_polls_until_done_documented_shape(self):
        self.fake.polls_before_done = 2
        self.make()
        self.assertEqual(len(self.fake.seen("status")), 3)

    def test_older_result_shape(self):
        self.fake.result_shape = "flat"
        self.fake.polls_before_done = 1
        img = self.make()
        self.assertEqual(img.size, (512, 512))

    def test_image_is_rgb_square_at_requested_size(self):
        img = self.make(size=640)
        self.assertEqual((img.mode, img.size), ("RGB", (640, 640)))

    def test_wide_image_is_cropped_square(self):
        self.fake.image_size = (1344, 768)
        img = self.make(size=600)
        self.assertEqual((img.mode, img.size), ("RGB", (600, 600)))


class Errors(FireflyCase):
    def test_no_credentials(self):
        os.environ.pop("FIREFLY_CLIENT_SECRET")
        self.fails_with("No Firefly credentials are set.")
        self.assertEqual(self.fake.requests, [])

    def test_sign_in_refuses_credentials(self):
        os.environ["FIREFLY_CLIENT_SECRET"] = "wrong"
        self.fails_with("Adobe didn't accept the Firefly credentials. Check the client ID and secret")
        self.assertEqual(len(self.fake.seen("token")), 1, "bad credentials aren't retried")

    def test_sign_in_refuses_credentials_401(self):
        self.fake.fail("token", 401, {"error": "invalid_client"})
        self.fails_with("Adobe didn't accept the Firefly credentials. Check the client ID and secret")

    def test_sign_in_refuses_scope(self):
        os.environ["FIREFLY_SCOPES"] = "openid"
        self.fails_with("These credentials aren't set up for Firefly.")

    def test_api_401_and_token_forgotten(self):
        self.fake.fail("generate", 401, {"error_code": "401013", "message": "Oauth token is not valid"})
        self.fails_with("Adobe didn't accept the Firefly credentials. Check them under Services.")
        self.assertEqual(len(self.fake.seen("generate")), 1, "401 isn't retried")
        self.make()
        self.assertEqual(len(self.fake.seen("token")), 2, "a 401 should clear the saved token")

    def test_api_403(self):
        self.fake.fail("generate", 403, {"error_code": "access_error"}, headers={"x-access-error": "user_non_entitled"})
        self.fails_with("This Adobe organisation doesn't have access to Firefly Services.")
        self.assertEqual(len(self.fake.seen("generate")), 1, "403 isn't retried")

    def test_api_403_out_of_allowance(self):
        self.fake.fail("generate", 403, {"error_code": "access_error"}, headers={"x-access-error": "quota_exhausted"})
        self.fails_with("This Adobe organisation has used up its Firefly allowance.")

    def test_policy_refusal(self):
        for status, body in ((451, {"error_code": "prompt_unsafe"}),
                             (400, {"error_code": "bad_request", "message": "Prompt violates our content policy."}),
                             (422, {"error_code": "validation_error", "message": "Request blocked by user guidelines"})):
            before = len(self.fake.seen("generate"))
            self.fake.fail("generate", status, body)
            self.fails_with("Firefly declined this image request under its content policy.")
            self.assertEqual(len(self.fake.seen("generate")) - before, 1, "a policy refusal isn't retried")

    def test_other_400_and_422_show_the_detail(self):
        self.fake.fail("generate", 400, {"error_code": "bad_request"})
        self.assertEqual(self.fails_with("Firefly didn't accept the request (400)"),
                         "Firefly didn't accept the request (400): bad_request")
        self.fake.fail("generate", 422, {"error_code": "validation_error", "validation_errors": [
            {"loc": ["body", "contentClass"], "msg": "value is not a valid enumeration member " + "x" * 300}]})
        msg = self.fails_with("Firefly didn't accept the request (422): contentClass: value is not a valid")
        self.assertLessEqual(len(msg), len("Firefly didn't accept the request (422): ") + 200)

    def test_429_retried_once_then_reported(self):
        self.fake.fail("generate", 429, {"error_code": "rate_limited"})
        self.make()
        self.assertEqual(len(self.fake.seen("generate")), 2, "one retry after a 429")
        self.fake.fail("generate", 429, {"error_code": "rate_limited"}, times=2)
        self.fails_with("Firefly is busy (rate limit).")
        self.assertEqual(len(self.fake.seen("generate")), 4)

    def test_500_retried_once_then_reported(self):
        self.fake.fail("generate", 500, {"error_code": "runtime_error"})
        self.make()
        self.assertEqual(len(self.fake.seen("generate")), 2, "one retry after a 500")
        self.fake.fail("status", 503, {}, times=2)
        self.fails_with("Firefly had a server problem.")

    def test_job_failed(self):
        self.fake.final_status = "failed"
        self.fails_with("Firefly couldn't make this image.")

    def test_job_cancelled_or_timed_out(self):
        self.fake.final_status = "cancelled"
        self.fails_with("Firefly cancelled this image")
        self.fake.final_status = "timeout"
        self.fails_with("Firefly took too long to answer.")

    def test_job_never_finishes(self):
        self.fake.polls_before_done = 10 ** 6
        firefly.POLL_EVERY = 0.05
        firefly.POLL_LIMIT = 0.2
        self.fails_with("Firefly took too long to answer.")

    def test_no_connection(self):
        self.fake.stop()
        self.fails_with("Couldn't reach Adobe.")

    def test_answer_without_an_image(self):
        self.fake.empty_outputs = True
        self.fails_with("Firefly answered without an image.")

    def test_download_that_is_not_an_image(self):
        self.fake.fail("image", 200, {"not": "an image"})
        self.fails_with("Firefly answered without an image.")


class Safety(FireflyCase):
    def test_foreign_status_address_is_refused_and_never_sent_the_token(self):
        other = FakeFirefly().start()
        try:
            self.fake.status_url = other.url + "/v3/status/job-1"
            self.fails_with("Firefly sent back an address this app doesn't trust")
            self.assertEqual(other.requests, [], "nothing may be sent to an address Adobe didn't own")
        finally:
            other.stop()

    def test_status_address_rule_for_the_real_service(self):
        del os.environ["FIREFLY_API_URL"]
        self.assertTrue(firefly._trusted_status_url("https://firefly-epo855230.adobe.io/v3/status/urn:ff:jobs:1"))
        self.assertTrue(firefly._trusted_status_url("https://firefly-api.adobe.io/v3/status/1"))
        for bad in ("http://firefly-api.adobe.io/v3/status/1", "https://adobe.io.evil.example/v3/status/1",
                    "https://evil.example/adobe.io", "https://notadobe.io/x", self.fake.url + "/v3/status/1", ""):
            self.assertFalse(firefly._trusted_status_url(bad), bad)

    def test_download_address_must_be_https_or_the_test_server(self):
        self.fake.image_url = "http://images.example/picture.png"
        self.fails_with("Firefly sent back an address this app doesn't trust")
        self.assertEqual(self.fake.seen("image"), [])

    def test_a_redirect_is_never_followed_with_the_token(self):
        other = FakeFirefly().start()
        try:
            self.fake.fail("status", 302, {}, headers={"Location": other.url + "/v3/status/job-1"})
            self.fails_with("Firefly returned an error (302)")
            self.assertEqual(other.requests, [])
        finally:
            other.stop()


class Labels(FireflyCase):
    def test_pointed_at_a_test_server_it_never_says_firefly(self):
        p = providers.get_image("firefly")
        self.assertEqual((p.id, p.label, p.model), ("firefly-test", "Firefly test server", "test-server"))
        entry = providers.available()["image"][-1]
        self.assertEqual((entry["id"], entry["label"]), ("firefly-test", "Firefly test server"))
        self.assertEqual(providers.resolve("image", "firefly"), "firefly-test")
        os.environ.pop("FIREFLY_IMS_URL")   # one override alone is still a test set-up
        self.assertEqual(providers.get_image("firefly").id, "firefly-test")

    def test_pointed_at_adobe(self):
        os.environ.pop("FIREFLY_IMS_URL")
        os.environ.pop("FIREFLY_API_URL")
        p = providers.get_image("firefly")
        self.assertEqual((p.id, p.label, p.model), ("firefly", "Adobe Firefly", "firefly (Adobe's default)"))
        os.environ["FIREFLY_MODEL_VERSION"] = "image4_ultra"
        self.assertEqual(p.model, "image4_ultra")
        self.assertEqual(config.firefly_ims_url(), "https://ims-na1.adobelogin.com")
        self.assertEqual(config.firefly_api_url(), "https://firefly-api.adobe.io")

    def test_registry(self):
        lists = providers.available()
        self.assertEqual([p["id"] for p in lists["text"]], ["mock", "openai"], "Firefly doesn't translate")
        self.assertNotEqual(providers.default_name("image"), "firefly")
        with self.assertRaises(ProviderError):
            providers.get_text("firefly")
        os.environ.pop("FIREFLY_CLIENT_ID")
        os.environ.pop("FIREFLY_IMS_URL")
        os.environ.pop("FIREFLY_API_URL")
        entry = providers.available()["image"][-1]
        self.assertEqual((entry["id"], entry["ready"], entry.get("connect")), ("firefly", False, "firefly"))


class CheckCredentials(FireflyCase):
    def test_good_pair_passes_with_one_token_request(self):
        firefly.check_credentials(CLIENT_ID, CLIENT_SECRET)
        self.assertEqual([r["endpoint"] for r in self.fake.requests], ["token"])

    def test_bad_pair_fails_plainly(self):
        with self.assertRaises(ProviderError) as cm:
            firefly.check_credentials(CLIENT_ID, "nope")
        self.assertIn("didn't accept the Firefly credentials", str(cm.exception))
        self.assertNotIn("nope", str(cm.exception))

    def test_no_connection(self):
        self.fake.stop()
        with self.assertRaises(ProviderError) as cm:
            firefly.check_credentials(CLIENT_ID, CLIENT_SECRET)
        self.assertTrue(str(cm.exception).startswith("Couldn't reach Adobe."))


if __name__ == "__main__":
    unittest.main(verbosity=1)
