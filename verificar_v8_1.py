from pathlib import Path
import py_compile
import sys

ROOT = Path(__file__).resolve().parent
for name in [
    "app.py", "database.py", "knowledge.py", "knowledge_engine.py",
    "intent_engine.py", "quality.py", "security.py",
]:
    py_compile.compile(str(ROOT / name), doraise=True)

from database import init_db
init_db()

from intent_engine import (
    detect_procedure_intent, ensure_intent_for_procedure, route_question
)
from knowledge_engine import (
    save_procedure, delete_procedure, procedure_to_dict
)

test_id = save_procedure(
    code="TEST.DEP",
    title="Depositos de Autos",
    objective="Prueba temporal.",
    steps=["1. El depósito se realiza con tarjeta", "2. Validar categoría"],
    keywords=(
        "depósitos de autos, deposito de autos, depósitos de garantía, "
        "cuanto es el deposito, cuales son los depositos"
    ),
    status="approved",
    username="verificador",
)
ensure_intent_for_procedure(test_id)

match = detect_procedure_intent("¿Cuáles son los depósitos de los autos?")
assert match is not None and match.procedure.id == test_id

decision = route_question("¿Cuáles son los depósitos de los autos?")
assert decision.route == "procedure"
assert decision.procedure.procedure.id == test_id

item = procedure_to_dict(decision.procedure.procedure)
assert item["steps"][0] == "El depósito se realiza con tarjeta"
assert item["steps"][1] == "Validar categoría"

delete_procedure(test_id)

print("OK: ARC+ v8.1 instalado y prueba de depósitos superada.")
print("Ahora ejecute: git status")
