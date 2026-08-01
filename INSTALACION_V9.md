# Instalación segura de ARC+ Enterprise v9

## 1. Respaldo obligatorio

Antes de copiar archivos, copie fuera del proyecto:

`C:\Consulta Manual ARC+ Git\data\arcplus_enterprise.db`

La extensión puede estar oculta por Windows.

## 2. Copia de la versión

Descomprima la entrega y copie todo en:

`C:\Consulta Manual ARC+ Git`

Seleccione **Reemplazar archivos**, pero no elimine la carpeta `data`.

## 3. Validación local

```bat
cd /d "C:\Consulta Manual ARC+ Git"
python verificar_v9.py
python diagnosticar_v9.py
```

## 4. Publicación

```bat
git status
git add .
git commit -m "Instala ARC Plus Enterprise v9 Knowledge Router"
git push origin main
```

Después use **Reboot** en Streamlit.

## 5. Prueba

Cree o conserve el procedimiento aprobado `Depositos de Autos` y pregunte:

`¿Cuáles son los depósitos de los autos?`

El origen debe indicar:

`Procedimiento estructurado`

## Nota sobre Streamlit Community Cloud

SQLite almacenado dentro de Streamlit Cloud no es persistente. Para una
operación real con usuarios y procedimientos permanentes se recomienda
PostgreSQL mediante la variable secreta `DATABASE_URL`.
