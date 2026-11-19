"""A stand-in for Azure Blob Storage, for testing with no Azure account.

It answers Put Blob (PUT /<container>/<name>?<sas>) the way Azure documents:
201 on success, and the documented status plus x-ms-error-code on failure. It
keeps what was uploaded in memory, records every request, and can be told to
fail in a chosen way. It checks only what Azure would refuse first: the
signature, the permissions, the container name and the blob type header.

In tests:

    fake = FakeAzure().start()
    os.environ["AZURE_TEST_HOST"] = fake.host
    link = fake.link()            # a container SAS link for this stand-in
    ...
    fake.stop()

By hand, to try the app's Azure flow offline:

    python3 tools/fake_azure.py

It prints the line to put in the environment before `python3 start.py`, and the
link to paste under Services.
"""
from __future__ import annotations

import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CONTAINER = "campaign-studio"
SIGNATURE = "test-signature"


class FakeAzure:
    def __init__(self, port: int = 0):
        self.blobs: dict[str, bytes] = {}
        self.requests: list[dict] = []
        self.fail_with: tuple[int, str] | None = None   # (status, x-ms-error-code) for every request
        self.fail_once: tuple[int, str] | None = None   # the next request only
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _reply(self, status: int, code: str = "", message: str = "") -> None:
                self.send_response(status)
                body = b""
                if code:
                    self.send_header("x-ms-error-code", code)
                    body = (f'<?xml version="1.0"?><Error><Code>{code}</Code>'
                            f"<Message>{message or code}</Message></Error>").encode()
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_PUT(self):
                u = urllib.parse.urlsplit(self.path)
                q = urllib.parse.parse_qs(u.query)
                data = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                fake.requests.append({"path": urllib.parse.unquote(u.path), "query": q,
                                      "headers": {k.lower(): v for k, v in self.headers.items()}, "size": len(data)})
                if fake.fail_once:
                    failure, fake.fail_once = fake.fail_once, None
                    return self._reply(*failure)
                if fake.fail_with:
                    return self._reply(*fake.fail_with)
                if q.get("sig", [""])[0] != SIGNATURE:
                    return self._reply(403, "AuthenticationFailed", "Signature did not match.")
                if not ({"c", "w"} & set(q.get("sp", [""])[0])):
                    return self._reply(403, "AuthorizationPermissionMismatch")
                container, _, name = urllib.parse.unquote(u.path).lstrip("/").partition("/")
                if container != CONTAINER:
                    return self._reply(404, "ContainerNotFound")
                if self.headers.get("x-ms-blob-type") != "BlockBlob" or not name:
                    return self._reply(400, "InvalidHeaderValue")
                fake.blobs[name] = data
                return self._reply(201)

        self.server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.host = f"127.0.0.1:{self.server.server_address[1]}"
        self.url = f"http://{self.host}"

    def link(self, perms: str = "cw", expires: str = "2099-01-01T00:00:00Z", container: str = CONTAINER,
             sig: str = SIGNATURE, sr: str = "c") -> str:
        q = urllib.parse.urlencode({"sv": "2021-08-06", "sr": sr, "sp": perms, "se": expires, "sig": sig})
        return f"{self.url}/{container}?{q}"

    def start(self) -> "FakeAzure":
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def main() -> int:
    fake = FakeAzure(port=int(sys.argv[1]) if len(sys.argv) > 1 else 8790).start()
    print(f"Stand-in Azure Blob Storage running at {fake.url} (not Azure).\n")
    print("Start the app with:\n")
    print(f"    AZURE_TEST_HOST={fake.host} python3 start.py\n")
    print("Then paste this link under Services, Storage:\n")
    print(f"    {fake.link()}\n")
    print("Uploads are kept in memory and listed here. Ctrl+C to stop.")
    seen: set[str] = set()
    try:
        while True:
            threading.Event().wait(1)
            for name in sorted(set(fake.blobs) - seen):
                print("  received", name)
                seen.add(name)
    except KeyboardInterrupt:
        fake.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
