import os

from .app import app


def main() -> int:
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "5000"))
    debug = os.getenv("DEBUG", "1") == "1"
    app.run(host=host, port=port, debug=debug)
    return 0
