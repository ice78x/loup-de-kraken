"""CLI.

  python -m kraken_assistant serve            → dashboard http://127.0.0.1:8000 + scheduler
  python -m kraken_assistant shell            → invite interactive (tape SCAN, POSITIONS, ...)
  python -m kraken_assistant run              → scheduler seul (sans interface)
  python -m kraken_assistant SCAN             → une commande puis sortie
  python -m kraken_assistant "SCAN URGENT"
"""
from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    from .app import App
    head = argv[0].lower()
    if head == "serve":
        import uvicorn
        from .ui.server import create_app
        core = App.build()
        uvicorn.run(create_app(core), host=core.settings.host, port=core.settings.port, log_level="warning")
        return 0
    core = App.build()
    if head == "run":
        from .scheduler import run_forever
        run_forever(core)
        return 0
    from .commands import execute
    if head == "shell":
        print("Kraken Assistant — tape une commande (AIDE pour la liste, QUIT pour sortir)")
        while True:
            try:
                line = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if line.upper() in ("QUIT", "EXIT", "Q"):
                break
            if line:
                print(execute(core, line))
        return 0
    print(execute(core, " ".join(argv)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
