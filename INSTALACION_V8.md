# Instalación de ARC+ Enterprise v8.0

1. Haga respaldo de la carpeta actual:
   `C:\Consulta Manual ARC+ Git`
2. Descomprima esta entrega.
3. Copie todo el contenido dentro de:
   `C:\Consulta Manual ARC+ Git`
4. Seleccione **Reemplazar los archivos en el destino**.
5. No elimine su base de datos local, manuales ni secretos.

Ejecute:

```bat
cd /d "C:\Consulta Manual ARC+ Git"
python verificar_v8.py
git status
git add .
git commit -m "Instala ARC Plus Enterprise v8 Motor de Procesos"
git push origin main
```

Después use **Reboot** en Streamlit.

## Prueba segura

Antes de registrar el procedimiento:

`¿Cómo realizar un pre-cierre?`

ARC+ debe reconocer el proceso y evitar mezclarlo con el cierre.

Después:

1. Abra **Centro de conocimiento**.
2. Cree y apruebe el procedimiento `Realizar pre-cierre`.
3. Registre solo los pasos oficiales.
4. Repita la pregunta.

El origen debe indicar:

`Proceso de negocio estructurado`
