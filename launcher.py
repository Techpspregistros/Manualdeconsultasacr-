from __future__ import annotations

import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def find_free_port(start: int = 8501, end: int = 8599) -> int:
    for port in range(start, end + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            if sock.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise RuntimeError("No se encontró un puerto disponible entre 8501 y 8599.")


def main() -> None:
    port = find_free_port()
    url = f"http://127.0.0.1:{port}"
    print("=" * 58)
    print("ARC+ Enterprise v5.1")
    print(f"La aplicación se abrirá en: {url}")
    print("Mantenga esta ventana abierta mientras usa el sistema.")
    print("=" * 58)

    # Abrir el navegador unos segundos después de iniciar Streamlit.
    import threading
    threading.Thread(target=lambda: (time.sleep(3), webbrowser.open(url)), daemon=True).start()

    command = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        "app.py",
        "--server.address",
        "127.0.0.1",
        "--server.port",
        str(port),
        "--browser.gatherUsageStats",
        "false",
    ]
    raise SystemExit(subprocess.call(command, cwd=ROOT))


if __name__ == "__main__":
    main()
