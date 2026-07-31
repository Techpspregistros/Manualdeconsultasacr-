
# Guía de despliegue

## Alternativa recomendada: servidor empresarial

Arquitectura:

- Aplicación Streamlit en Docker.
- PostgreSQL central.
- Carpeta de manuales en volumen persistente.
- Proxy HTTPS (Nginx, Traefik o servicio administrado).
- Acceso por VPN o red corporativa cuando los manuales sean internos.

## Prueba sin costo

Streamlit Community Cloud permite validar la interfaz. Para conservar el aprendizaje,
use una base PostgreSQL externa y configure `DATABASE_URL` en los secretos.

## Producción

Antes de exponer la aplicación en Internet:

1. Cambie todas las contraseñas.
2. Active HTTPS.
3. Restrinja el acceso por firewall/VPN.
4. Agregue autenticación corporativa.
5. Configure copias de seguridad de PostgreSQL.
6. No coloque documentos confidenciales en repositorios públicos.
7. Revise permisos por rol.
8. Pruebe restauración de respaldos.
