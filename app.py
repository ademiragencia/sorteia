"""Entrypoint web do SorteIA (Vercel e qualquer servidor WSGI).

Rodar localmente:  python3 app.py  →  http://localhost:8000
"""

from sorteia.web import app

if __name__ == "__main__":
    from wsgiref.simple_server import make_server

    print("SorteIA web em http://localhost:8000 — Ctrl+C para sair")
    make_server("", 8000, app).serve_forever()
