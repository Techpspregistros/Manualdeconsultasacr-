# ARC+ Enterprise v9.0

## Cambio principal

Todas las preguntas pasan por `knowledge_router.py`.

Prioridad estricta:

1. Respuesta oficial aprobada.
2. Procedimiento estructurado aprobado.
3. Protección contra mezcla de procesos.
4. Manual PDF como último recurso.

El asistente ya no ejecuta de forma independiente el buscador PDF y el motor de
procedimientos. Existe un único punto de decisión.

## Compatibilidad

La versión conserva las tablas y el esquema existente. No incluye ninguna base
de datos vacía y no borra la carpeta `data`.

## Mantenimiento

Incluye:

- diagnóstico de la ruta real de la base;
- conteo por tabla;
- respaldo SQLite;
- módulo administrativo `Mantenimiento de datos`;
- script `diagnosticar_v9.py`.
