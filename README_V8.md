# ARC+ Enterprise v8.0 — Motor de Procesos de Negocio

## Objetivo

Evitar que una pregunta sobre un proceso específico se responda con fragmentos
de procesos parecidos. La aplicación identifica la intención funcional antes de
consultar los documentos.

## Flujo de respuesta

1. Respuesta oficial aprobada.
2. Detección de proceso de negocio.
3. Procedimiento estructurado aprobado.
4. Búsqueda documental, únicamente cuando sea segura.

## Protección anti-mezcla

Las intenciones estrictas, como `PRE_CIERRE`, bloquean la búsqueda documental
si todavía no existe un procedimiento aprobado. En lugar de dar una respuesta
incorrecta, ARC+ informa que el conocimiento está pendiente de aprobación.

## Catálogo inicial

- Pre-cierre.
- Cierre del contrato.
- Reapertura.
- Cambio de vehículo.
- Depósito de garantía.

El administrador puede editar alias, términos excluidos, procedimiento objetivo
y comportamiento estricto desde el Centro de conocimiento.
