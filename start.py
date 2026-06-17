"""Arranque todo-en-uno del prototipo.

Comprueba que el frontend esta compilado (y lo compila si falta), verifica que
Ollama responde con el modelo esperado, arranca el backend de FastAPI y abre el
navegador. Pensado para lanzar la demo del TFG con un solo comando:

    python start.py

Asume que Python, Node/npm y Ollama estan instalados en la maquina.
"""

import argparse
import json
import shutil
import subprocess
import sys
import threading
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FRONTEND_DIR = ROOT / "frontend"
INDEX_FILE = ROOT / "app" / "static" / "index.html"
AGENTS_FILE = ROOT / "app" / "config" / "agents.json"


def _c(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m"


def info(msg: str) -> None:
    print(_c("[start]", "36"), msg, flush=True)


def warn(msg: str) -> None:
    print(_c("[warn] ", "33"), msg, flush=True)


def fail(msg: str) -> None:
    print(_c("[error]", "31"), msg, flush=True)


def ollama_target() -> tuple[str, str]:
    """Devuelve (base_url, model) del primer agente Ollama de agents.json."""
    default = ("http://127.0.0.1:11434/api", "gemma3:4b")
    try:
        catalog = json.loads(AGENTS_FILE.read_text(encoding="utf-8"))
        for agent in catalog.get("agents", []):
            if agent.get("provider") == "ollama":
                return agent.get("base_url", default[0]), agent.get("model", default[1])
    except (OSError, json.JSONDecodeError):
        pass
    return default


def ensure_frontend(rebuild: bool) -> bool:
    if INDEX_FILE.exists() and not rebuild:
        info("Frontend ya compilado.")
        return True

    npm = shutil.which("npm")
    if npm is None:
        fail("npm no esta en el PATH. Instala Node.js o compila el frontend a mano.")
        return False

    info("Compilando frontend (npm run build)...")
    result = subprocess.run([npm, "run", "build"], cwd=FRONTEND_DIR)
    if result.returncode != 0:
        fail("El build del frontend fallo. Revisa la salida de npm.")
        return False
    info("Frontend compilado.")
    return True


def check_ollama() -> None:
    base_url, model = ollama_target()
    host = base_url.rsplit("/api", 1)[0]
    tags_url = f"{host}/api/tags"
    try:
        with urllib.request.urlopen(tags_url, timeout=3) as response:
            data = json.loads(response.read().decode("utf-8"))
        models = [m.get("name", "") for m in data.get("models", [])]
        if any(name == model or name.startswith(model) for name in models):
            info(f"Ollama responde y el modelo '{model}' esta disponible.")
        else:
            warn(f"Ollama responde pero no encuentro el modelo '{model}'.")
            warn(f"Descargalo con:  ollama pull {model}")
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        warn(f"Ollama no responde en {host}.")
        warn("Arranca Ollama antes de ejecutar el pipeline:  ollama serve")
        warn("La interfaz cargara igual, pero el analisis fallara sin Ollama.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Arranque todo-en-uno del prototipo.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--rebuild", action="store_true", help="Forzar recompilacion del frontend.")
    parser.add_argument("--skip-build", action="store_true", help="No compilar aunque falte el build.")
    parser.add_argument("--no-browser", action="store_true", help="No abrir el navegador.")
    parser.add_argument("--skip-ollama-check", action="store_true")
    args = parser.parse_args()

    if not args.skip_build:
        if not ensure_frontend(args.rebuild):
            return 1
    elif not INDEX_FILE.exists():
        warn("Frontend sin compilar y --skip-build activo: la UI no se servira.")

    if not args.skip_ollama_check:
        check_ollama()

    url = f"http://{args.host}:{args.port}/"
    if not args.no_browser:
        threading.Timer(1.8, lambda: webbrowser.open(url)).start()

    info(f"Arrancando backend en {url}  (Ctrl+C para parar)")

    try:
        import uvicorn
    except ImportError:
        fail("uvicorn no esta instalado. Ejecuta:  pip install -r requirements.txt")
        return 1

    sys.path.insert(0, str(ROOT))
    uvicorn.run("app.main:app", host=args.host, port=args.port, reload=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
