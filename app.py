"""Inicie com python app.py; acesse http://localhost:3000."""
import os
from nexo.web import create_app

app = create_app()

if __name__ == "__main__":
    from waitress import serve
    host = os.environ.get("NEXO_HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "3000"))
    print(f"Nexo em Python: http://{host}:{port}", flush=True)
    serve(app, host=host, port=port, threads=4, max_request_body_size=16 * 1024 * 1024)

