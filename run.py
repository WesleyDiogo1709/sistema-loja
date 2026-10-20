"""Ponto de entrada: inicia o servidor local e abre o navegador."""
import os
import sys
import threading
import webbrowser

from loja.app import create_app

HOST = os.environ.get("LOJA_HOST", "127.0.0.1")   # use 0.0.0.0 para permitir outros computadores da rede
PORT = int(os.environ.get("LOJA_PORT", "5000"))


def main():
    app = create_app()
    url = f"http://127.0.0.1:{PORT}"
    print("=" * 60)
    print(" Sistema da Loja em execução")
    print(f" Acesse: {url}")
    if HOST != "127.0.0.1":
        print(f" Rede local liberada ({HOST}). Use o IP deste computador nos demais.")
    print(" Para encerrar, feche esta janela ou pressione Ctrl+C.")
    print("=" * 60)
    if os.environ.get("LOJA_NO_BROWSER") != "1":
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    try:
        from waitress import serve
        serve(app, host=HOST, port=PORT, threads=8)
    except ImportError:
        print(" (waitress não instalado: usando o servidor de desenvolvimento do Werkzeug)")
        app.run(host=HOST, port=PORT, threaded=True, debug=False)


if __name__ == "__main__":
    sys.exit(main())
