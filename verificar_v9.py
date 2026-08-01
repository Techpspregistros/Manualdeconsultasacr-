
from pathlib import Path
import py_compile

ROOT = Path(__file__).resolve().parent
required = [
    "app.py",
    "database.py",
    "knowledge.py",
    "knowledge_engine.py",
    "intent_engine.py",
    "knowledge_router.py",
    "database_manager.py",
    "quality.py",
    "security.py",
]
for name in required:
    py_compile.compile(str(ROOT / name), doraise=True)

from database import init_db
from knowledge_engine import save_procedure, delete_procedure
from intent_engine import ensure_intent_for_procedure
from knowledge_router import answer_question
from database_manager import create_backup, database_report, validate_sqlite

init_db()

procedure_id = save_procedure(
    code="TEST.DEPOSITOS",
    title="Depositos de Autos",
    objective="Indicar los depósitos de garantía.",
    steps=[
        "El depósito se realiza con tarjeta de crédito.",
        "Sedán nacional: 500 dólares.",
        "SUV 4x2 nacional: 750 dólares.",
        "SUV 4x4 nacional: 1000 dólares.",
        "Cliente extranjero: 1000 dólares para cualquier categoría.",
    ],
    keywords=(
        "depósitos de autos, depósitos de garantía, deposito de autos, "
        "cuanto es el deposito, cuales son los depositos de los autos"
    ),
    status="approved",
    username="verificador",
)
ensure_intent_for_procedure(procedure_id)

answer = answer_question(
    "¿Cuáles son los depósitos de los autos?",
    style="Normal",
)
assert answer.origin == "Procedimiento estructurado"
assert answer.procedure is not None
assert answer.procedure["id"] == procedure_id
assert "Sedán nacional" in answer.answer
assert "Pestañas de información" not in answer.answer

report = database_report()
assert "users" in report["counts"]
assert "procedures" in report["counts"]

backup = create_backup("prueba_v9")
validation = validate_sqlite(backup)
assert validation["integrity"] == "ok"
backup.unlink(missing_ok=True)

delete_procedure(procedure_id)

print("OK: ARC+ Enterprise v9 instalado.")
print("Knowledge Router prioriza procedimientos antes que el PDF.")
print("Prueba de depósitos de autos superada.")
print("Diagnóstico y respaldo de base superados.")
