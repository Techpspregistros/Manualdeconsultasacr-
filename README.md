
# ARC+ Knowledge Assistant Enterprise v4.0 — MVP funcional

Esta entrega convierte el prototipo anterior en una base empresarial ejecutable y desplegable.

## Funciones incluidas

- Inicio de sesión.
- Roles: agente, supervisor y administrador.
- Consulta simultánea de varios manuales.
- Búsqueda por palabras, frases, sinónimos e intención.
- Respuestas extractivas limitadas a los documentos.
- Página exacta y visualización del PDF.
- Nivel de confianza.
- Historial por usuario y agencia.
- Retroalimentación y solución real.
- Aprendizaje supervisado.
- Diccionario corporativo.
- Preguntas frecuentes oficiales.
- Carga e indexación de documentos PDF.
- Dashboard de consultas, agencias, temas y tiempos.
- Administración de usuarios.
- Auditoría.
- SQLite para instalación local.
- PostgreSQL para despliegue multiusuario.
- Docker y Docker Compose.

## Primer acceso local

Usuario:

`admin`

La contraseña se toma de la variable `ARCPLUS_ADMIN_PASSWORD`.
Cuando no se configura, el valor provisional es:

`Cambiar123!`

Debe cambiarse inmediatamente desde el módulo **Usuarios**.

## Instalación local

1. Instale Python 3.11 o 3.12.
2. Ejecute `instalar_local.bat`.
3. Ejecute `iniciar_local.bat`.
4. Abra `http://localhost:8501`.

## Publicación con Docker y PostgreSQL

1. Cambie las contraseñas en `docker-compose.yml`.
2. Ejecute:

```bash
docker compose up -d --build
```

3. Abra `http://IP-DEL-SERVIDOR:8501`.

## Publicación en Streamlit Community Cloud

Puede publicarse para una prueba, pero SQLite no garantiza persistencia duradera en esa plataforma.
Para aprendizaje compartido y conservación de datos, configure `DATABASE_URL` con PostgreSQL.

Archivos principales:

- `app.py`
- `database.py`
- `knowledge.py`
- `security.py`
- `requirements.txt`
- `manuals/`

## Límites de esta entrega

Esta es una versión Enterprise MVP, no una integración terminada con el sistema transaccional ARC+.

Todavía requieren trabajo adicional:

- conexión con contratos, reservas, clientes, placas, lotes y cortes reales;
- autenticación corporativa SSO/Microsoft/Google;
- recuperación semántica con embeddings;
- videos de procedimientos;
- almacenamiento externo de documentos;
- políticas detalladas por documento;
- copias de seguridad automáticas;
- pruebas de penetración y endurecimiento de seguridad.

La integración con ARC+ requiere una API oficial o acceso autorizado a su base de datos.
