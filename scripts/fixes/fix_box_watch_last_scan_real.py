"""
FIX REAL last_scan - Vigilancia Box

Ejecutar:
python -m app.fix_box_watch_last_scan_real

Qué hace:
1) Corrige frontend/views/box_watch_view.py para que no use variables last_scan sueltas.
2) Añade al final de backend/services/box_watch_service.py funciones seguras que devuelven:
   - last_scan
   - ultimo_escaneo
3) No toca Box.
4) No reescanea.
"""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
VIEW_PATH = ROOT / "frontend" / "views" / "box_watch_view.py"
SERVICE_PATH = ROOT / "backend" / "services" / "box_watch_service.py"

MARKER_START = "# === QUESADA LAST_SCAN SAFE OVERRIDE START ==="
MARKER_END = "# === QUESADA LAST_SCAN SAFE OVERRIDE END ==="


OVERRIDE = r