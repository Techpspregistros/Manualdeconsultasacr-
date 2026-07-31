# ARC+ Enterprise v7.0 — instalación completa

Esta carpeta contiene una versión completa e integrada. Incluye la aplicación,
la biblioteca, el asistente conversacional, aprendizaje supervisado, audio y el
Knowledge Engine con procedimientos estructurados.

## Forma segura de actualizar el repositorio actual

1. Mantenga una copia de respaldo de:
   - la carpeta `manuals`;
   - cualquier archivo local dentro de `data`;
   - sus archivos `.env` o secretos.
2. Copie todo el contenido de esta carpeta a:
   `C:\Consulta Manual ARC+ Git`
3. Seleccione **Reemplazar los archivos en el destino**.
4. No elimine archivos locales de base de datos que ya contengan información.
5. En CMD ejecute:

```bat
cd /d "C:\Consulta Manual ARC+ Git"
python verificar_v7.py
git status
git add .
git commit -m "Instala ARC Plus Enterprise v7 completa"
git push origin main
```

6. En Streamlit Community Cloud use **Reboot**.

## Cómo confirmar que v7 está activa

En el menú lateral debe aparecer:

`Centro de conocimiento`

## Primera configuración del procedimiento de pre-cierre

1. Ingrese como administrador.
2. Abra **Centro de conocimiento**.
3. Entre en **Crear procedimiento**.
4. Registre el título `Realizar pre-cierre`.
5. Agregue solamente los pasos correctos y aprobados.
6. Use palabras clave como:
   `pre-cierre, pre cierre, realizar pre-cierre`
7. Seleccione estado `approved`.
8. Consulte: `¿Cómo realizar un pre-cierre?`
9. Verifique que el origen indique:
   `Procedimiento estructurado`.

## Prioridad de respuesta

1. Respuesta oficial aprobada.
2. Procedimiento estructurado aprobado.
3. Fragmentos del documento PDF.

El sistema no inventa el contenido correcto del procedimiento. El administrador
debe registrar o aprobar los pasos oficiales.
