"""Ponto de entrada: inicia o servidor local e abre o navegador."""
import os
import sys
import threading
import webbrowser

from loja.app import create_app

PRODUCTION = os.environ.get("LOJA_ENV", "").strip().lower() == "production"
# Em produção a hospedagem define a porta (variável PORT) e o servidor escuta em todas as interfaces.
HOST = os.environ.get("LOJA_HOST", "0.0.0.0" if PRODUCTION else "127.0.0.1")
PORT = int(os.environ.get("LOJA_PORT") or os.environ.get("PORT") or "5000")


def porta_livre(host, inicio):
    """Devolve a primeira porta que pode ser usada (a pedida ou as seguintes).
    No Windows a porta pode estar ocupada ou reservada (erro 10013)."""
    import socket
    for p in list(range(inicio, inicio + 20)) + [8080, 8000, 8765, 5555]:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind((host, p))
            return p
        except OSError:
            continue
        finally:
            s.close()
    raise SystemExit("Nenhuma porta livre encontrada. Defina LOJA_PORT com outro numero (ex.: 8765).")


def main():
    global PORT
    escolhida = PORT if PRODUCTION else porta_livre(HOST, PORT)
    if escolhida != PORT:
        print(f" Aviso: a porta {PORT} esta ocupada ou bloqueada pelo Windows. Usando a porta {escolhida}.")
        PORT = escolhida
    app = create_app()
    url = f"http://127.0.0.1:{PORT}"
    print("=" * 60)
    print(" Sistema da Loja em execução")
    print(f" Acesse: {url}" if not PRODUCTION else f" Modo PRODUÇÃO na porta {PORT} (acesse pelo endereço HTTPS da hospedagem)")
    if HOST != "127.0.0.1" and not PRODUCTION:
        print(f" Rede local liberada ({HOST}). Use o IP deste computador nos demais.")
    print(" Para encerrar, feche esta janela ou pressione Ctrl+C.")
    print("=" * 60)
    if os.environ.get("LOJA_NO_BROWSER") != "1" and not PRODUCTION:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    try:
        from waitress import serve
        serve(app, host=HOST, port=PORT, threads=8)
    except ImportError:
        print(" (waitress não instalado: usando o servidor de desenvolvimento do Werkzeug)")
        app.run(host=HOST, port=PORT, threaded=True, debug=False)


if __name__ == "__main__":
    sys.exit(main())
