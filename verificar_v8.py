from pathlib import Path
import py_compile
import sys

ROOT = Path(__file__).resolve().parent
required = [
    "app.py", "database.py", "knowledge.py", "knowledge_engine.py",
    "intent_engine.py", "quality.py", "security.py", "requirements.txt",
]
missing = [name for name in required if not (ROOT / name).exists()]
if missing:
    print("ERROR: faltan archivos:", ", ".join(missing))
    sys.exit(1)

for name in [
    "app.py", "database.py", "knowledge.py", "knowledge_engine.py",
    "intent_engine.py", "quality.py", "security.py",
]:
    py_compile.compile(str(ROOT / name), doraise=True)

from database import init_db
init_db()

from intent_engine import detect_intent, route_question, seed_business_intents
from knowledge_engine import save_procedure, delete_procedure

seed_business_intents()

intent = detect_intent("¿Cómo realizar un pre-cierre?")
assert intent is not None
assert intent.code == "PRE_CIERRE"

decision_without = route_question("¿Cómo realizar un pre-cierre?")
assert decision_without.route in {"blocked", "procedure"}

test_id = save_procedure(
    code="TEST.PRE",
    title="Realizar pre-cierre",
    objective="Prueba temporal de enrutamiento.",
    steps=["Validar información"],
    keywords="pre-cierre, pre cierre",
    status="approved",
    username="verificador",
)
decision_with = route_question("¿Cómo realizar un pre-cierre?")
assert decision_with.route == "procedure"
assert decision_with.procedure is not None
assert decision_with.procedure.procedure.id == test_id
delete_procedure(test_id)

print("OK: ARC+ v8 instalado; intención PRE_CIERRE y protección anti-mezcla superadas.")
print("Ahora ejecute: git status")
