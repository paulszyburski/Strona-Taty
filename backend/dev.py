import mimetypes
from pathlib import Path
from wsgiref.simple_server import make_server

from backend.app import application as api_application
from backend.config import ROOT

PUBLIC = ROOT / "public"


def application(environ, start_response):
    path = environ.get("PATH_INFO", "/")
    if path.startswith("/api/"):
        return api_application(environ, start_response)

    relative_path = "index.html" if path == "/" else path.lstrip("/")
    requested_file = (PUBLIC / relative_path).resolve()

    if PUBLIC not in requested_file.parents or not requested_file.is_file():
        start_response("404 Not Found", [("Content-Type", "text/plain; charset=utf-8")])
        return [b"Not found"]

    content_type = mimetypes.guess_type(requested_file)[0] or "application/octet-stream"
    content = requested_file.read_bytes()
    start_response(
        "200 OK",
        [
            ("Content-Type", content_type),
            ("Content-Length", str(len(content))),
        ],
    )
    return [content]


if __name__ == "__main__":
    address = "127.0.0.1"
    port = 8000
    print(f"Open http://{address}:{port}")
    with make_server(address, port, application) as server:
        server.serve_forever()
