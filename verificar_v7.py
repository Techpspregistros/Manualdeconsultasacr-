from pathlib import Path
import py_compile
import sys

ROOT = Path(__file__).resolve().parent
required = [
    "app.py", "database.py", "knowledge.py", "knowledge_engine.py",
    "quality.py", "security.py", "requirements.txt",
]
missing = [name for name in required if not (ROOT / name).exists()]
if missing:
    print("ERROR: faltan archivos:", ", ".join(missing))
    sys.exit(1)

for name in [
    "app.py", "database.py", "knowledge.py",
    "knowledge_engine.py", "quality.py", "security.py",
]:
    py_compile.compile(str(ROOT / name), doraise=True)

from database import init_db
init_db()

from knowledge_engine import save_procedure, search_procedure, delete_procedure
test_id = save_procedure(
    code="TEST.1",
    title="Realizar pre-cierre de prueba",
    objective="Prueba temporal.",
    steps=["Paso temporal"],
    keywords="pre cierre",
    status="approved",
    username="verificador",
)
match = search_procedure("¿Cómo realizar un pre-cierre de prueba?")
assert match is not None
assert match.procedure.id == test_id
delete_procedure(test_id)

print("OK: Knowledge Engine v7 instalado y prueba superada.")
print("Ahora ejecute: git status")
