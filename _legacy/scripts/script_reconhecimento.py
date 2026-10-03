"""Ponto de entrada compatível com a versão antiga do projeto.

Preferencialmente execute com:
    assistente-voz
ou:
    python -m voice_assistant
"""

import sys
from pathlib import Path


def _ensure_src_on_path() -> None:
    project_root = Path(__file__).resolve().parent
    src_dir = project_root / "src"
    if src_dir.exists():
        sys.path.insert(0, str(src_dir))


def _main() -> int:
    _ensure_src_on_path()
    from voice_assistant.app import main

    return main()


if __name__ == "__main__":
    raise SystemExit(_main())
