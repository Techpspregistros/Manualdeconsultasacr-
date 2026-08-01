
from database import init_db
from database_manager import create_backup, database_report

init_db()
report = database_report()

print("=" * 72)
print("ARC+ ENTERPRISE V9 - DIAGNÓSTICO")
print("=" * 72)
print("Tipo:", report["database_url_type"])
print("Ruta:", report["database_path"])
print("Existe:", "Sí" if report["exists"] else "No")
print("Tamaño:", report["size_bytes"], "bytes")
print("\nREGISTROS")
for table, count in report["counts"].items():
    print(f"{table:<28} {count}")

if report["database_url_type"] == "SQLite" and report["exists"]:
    backup = create_backup("diagnostico_v9")
    print("\nRespaldo creado:", backup)

print("=" * 72)
