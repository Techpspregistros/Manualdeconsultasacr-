
from __future__ import annotations

import csv
import io
import os
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st
from sqlalchemy import func, select

from database import (
    AuditLog, Document, FAQ, Feedback, QueryLog, Synonym, User,
    db_session, init_db
)
from knowledge import (
    compose_answer, index_manual_directory, index_pdf, normalize, render_page,
    search, search_faq, seed_synonyms
)
from security import hash_password, initial_admin_password, verify_password


BASE = Path(__file__).resolve().parent
MANUALS = BASE / "manuals"
DATA = BASE / "data"
MANUALS.mkdir(exist_ok=True)
DATA.mkdir(exist_ok=True)

st.set_page_config(page_title="ARC+ Enterprise v4", page_icon="🧠", layout="wide")

st.markdown("""
<style>
.block-container {max-width: 1500px; padding-top: 1rem;}
[data-testid="stMetric"] {border:1px solid #e5e7eb;border-radius:12px;padding:10px;}
.role {padding:4px 9px;border-radius:12px;background:#eef2ff;font-size:.8rem;}
.source {font-size:.86rem;color:#555;}
</style>
""", unsafe_allow_html=True)


def audit(username: str, action: str, detail: str = ""):
    with db_session() as db:
        db.add(AuditLog(username=username, action=action, detail=detail))
        db.commit()


@st.cache_resource
def startup():
    init_db()
    seed_synonyms()
    with db_session() as db:
        admin = db.scalar(select(User).where(User.username == "admin"))
        if not admin:
            db.add(User(
                username="admin",
                full_name="Administrador",
                agency="Central",
                role="admin",
                password_hash=hash_password(initial_admin_password()),
                active=True,
            ))
            db.commit()
        document_count = db.scalar(select(func.count(Document.id))) or 0
    if document_count == 0:
        index_manual_directory(MANUALS)
    return True


startup()


def current_user():
    return st.session_state.get("user")


def login_screen():
    st.title("🧠 ARC+ Knowledge Assistant Enterprise")
    st.caption("Plataforma privada de conocimiento operativo — versión 4.0 MVP")
    with st.form("login"):
        username = st.text_input("Usuario")
        password = st.text_input("Contraseña", type="password")
        submitted = st.form_submit_button("Ingresar", type="primary", use_container_width=True)
    if submitted:
        with db_session() as db:
            user = db.scalar(select(User).where(User.username == username.strip().lower()))
            if user and user.active and verify_password(password, user.password_hash):
                st.session_state["user"] = {
                    "id": user.id, "username": user.username, "name": user.full_name,
                    "agency": user.agency, "role": user.role
                }
                audit(user.username, "LOGIN")
                st.rerun()
        st.error("Credenciales inválidas.")
    st.info(
        "Primer acceso local: usuario **admin**. La contraseña inicial se define con "
        "`ARCPLUS_ADMIN_PASSWORD`; si no se configura, es `Cambiar123!`. Cámbiela inmediatamente."
    )


if not current_user():
    login_screen()
    st.stop()

user = current_user()

with st.sidebar:
    st.markdown(f"### {user['name'] or user['username']}")
    st.markdown(f"<span class='role'>{user['role'].upper()}</span>", unsafe_allow_html=True)
    st.caption(user.get("agency", ""))
    options = ["Asistente", "Biblioteca", "Mi historial"]
    if user["role"] in ("supervisor", "admin"):
        options += ["Analítica"]
    if user["role"] == "admin":
        options += ["Aprendizaje", "Usuarios", "Auditoría"]
    view = st.radio("Módulos", options)
    st.divider()
    if st.button("Cerrar sesión", use_container_width=True):
        audit(user["username"], "LOGOUT")
        st.session_state.clear()
        st.rerun()


def categories():
    with db_session() as db:
        return sorted(set(db.scalars(select(Document.category).where(Document.active == True)).all()))


if view == "Asistente":
    st.title("Asistente inteligente")
    st.caption("Consulta varios manuales, muestra fuentes y registra aprendizaje supervisado.")

    c1, c2 = st.columns([3, 1])
    with c2:
        selected_categories = st.multiselect("Categorías", categories(), default=categories())
        limit = st.slider("Resultados", 3, 12, 7)
        show_pages = st.checkbox("Mostrar página del PDF", True)

    examples = [
        "¿Cómo cierro un contrato?",
        "El contrato no permite guardar.",
        "¿Cómo se realiza un cambio de vehículo?",
        "¿Dónde se registra el depósito de garantía?",
    ]
    excols = st.columns(4)
    for i, item in enumerate(examples):
        if excols[i].button(item, use_container_width=True):
            st.session_state["question"] = item

    with c1:
        question = st.text_area(
            "Pregunta", key="question", height=110,
            placeholder="Describa el proceso, pantalla, botón o mensaje de error."
        )
        ask = st.button("Consultar", type="primary")

    if ask and question.strip():
        faq = search_faq(question)
        results, intent, confidence, elapsed = search(
            question, limit=limit, categories=selected_categories or None
        )
        with db_session() as db:
            log = QueryLog(
                user_id=user["id"], username=user["username"], agency=user["agency"],
                question=question.strip(), intent=intent, confidence=confidence,
                result_title=results[0].title if results else "",
                document_name=results[0].document_name if results else "",
                page_number=results[0].page_number if results else None,
                elapsed_ms=elapsed,
            )
            db.add(log)
            db.commit()
            query_id = log.id
        st.session_state["last"] = {
            "question": question, "faq": faq, "results": results, "intent": intent,
            "confidence": confidence, "elapsed": elapsed, "query_id": query_id,
            "answer": compose_answer(question, results, faq)
        }

    last = st.session_state.get("last")
    if last:
        m1, m2, m3 = st.columns(3)
        m1.metric("Intención", last["intent"])
        m2.metric("Confianza", last["confidence"])
        m3.metric("Tiempo", f"{last['elapsed']} ms")
        st.markdown(last["answer"])

        text_export = (
            f"ARC+ ENTERPRISE V4\nFecha: {datetime.now():%Y-%m-%d %H:%M}\n"
            f"Usuario: {user['username']}\nPregunta: {last['question']}\n\n"
            + last["answer"].replace("### ", "").replace("**", "").replace("_", "")
        )
        st.download_button("Descargar respuesta", text_export, "respuesta_arcplus.txt", "text/plain")

        st.divider()
        st.subheader("Retroalimentación")
        rating = st.radio(
            "¿La respuesta resolvió la consulta?",
            ["Resuelta", "Parcial", "No resuelta", "Incorrecta"],
            horizontal=True,
        )
        comment = st.text_area("Comentario opcional")
        solution = st.text_area("¿Cómo se resolvió finalmente? (útil para aprendizaje)")
        if st.button("Guardar retroalimentación"):
            with db_session() as db:
                db.add(Feedback(
                    query_id=last["query_id"], rating=rating,
                    comment=comment.strip(), final_solution=solution.strip()
                ))
                if rating == "Resuelta":
                    log = db.get(QueryLog, last["query_id"])
                    log.resolved = True
                db.commit()
            audit(user["username"], "FEEDBACK", f"Consulta {last['query_id']}: {rating}")
            st.success("Retroalimentación guardada para revisión.")

        st.divider()
        st.subheader("Fuentes")
        for i, r in enumerate(last["results"], 1):
            label = f"{i}. {r.title} — {r.document_name} — pág. {r.page_number}"
            with st.expander(label, expanded=(i == 1)):
                st.write(r.excerpt)
                st.caption("Coincidencias: " + ", ".join(r.matches))
                if show_pages:
                    try:
                        with db_session() as db:
                            document = db.scalar(select(Document).where(Document.name == r.document_name))
                        st.image(
                            render_page(MANUALS, document.filename, r.page_number),
                            caption=f"{r.document_name}, página {r.page_number}",
                            use_container_width=True,
                        )
                    except Exception as exc:
                        st.warning(f"No se pudo mostrar la página: {exc}")

elif view == "Biblioteca":
    st.title("Biblioteca de conocimiento")
    with db_session() as db:
        docs = db.scalars(select(Document).order_by(Document.category, Document.name)).all()
    if docs:
        df = pd.DataFrame([{
            "ID": d.id, "Documento": d.name, "Categoría": d.category,
            "Versión": d.version, "Páginas": d.page_count,
            "Activo": d.active, "Indexado": d.indexed_at
        } for d in docs])
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("No hay documentos indexados.")

    if user["role"] == "admin":
        st.subheader("Agregar o actualizar documento")
        uploaded = st.file_uploader("PDF", type=["pdf"])
        c1, c2, c3 = st.columns(3)
        name = c1.text_input("Nombre documental")
        category = c2.text_input("Categoría", value="General")
        version = c3.text_input("Versión")
        if st.button("Guardar e indexar", type="primary") and uploaded:
            safe_name = Path(uploaded.name).name
            target = MANUALS / safe_name
            target.write_bytes(uploaded.getbuffer())
            index_pdf(target, name=name.strip() or target.stem, category=category.strip(), version=version.strip())
            audit(user["username"], "INDEX_DOCUMENT", safe_name)
            st.cache_resource.clear()
            st.success("Documento guardado e indexado.")
            st.rerun()

elif view == "Mi historial":
    st.title("Mi historial")
    with db_session() as db:
        rows = db.scalars(
            select(QueryLog).where(QueryLog.user_id == user["id"]).order_by(QueryLog.id.desc()).limit(500)
        ).all()
    df = pd.DataFrame([{
        "Fecha": x.created_at, "Pregunta": x.question, "Tema": x.intent,
        "Confianza": x.confidence, "Documento": x.document_name,
        "Página": x.page_number, "Resuelta": x.resolved
    } for x in rows])
    st.dataframe(df, use_container_width=True, hide_index=True)

elif view == "Analítica":
    st.title("Inteligencia organizacional")
    with db_session() as db:
        total = db.scalar(select(func.count(QueryLog.id))) or 0
        resolved = db.scalar(select(func.count(QueryLog.id)).where(QueryLog.resolved == True)) or 0
        low = db.scalar(select(func.count(QueryLog.id)).where(QueryLog.confidence == "Baja")) or 0
        neg = db.scalar(select(func.count(Feedback.id)).where(Feedback.rating.in_(["No resuelta", "Incorrecta"]))) or 0
        queries = db.scalars(select(QueryLog).order_by(QueryLog.created_at)).all()
    a, b, c, d = st.columns(4)
    a.metric("Consultas", total)
    b.metric("Resueltas", resolved)
    c.metric("Confianza baja", low)
    d.metric("Feedback negativo", neg)

    if queries:
        df = pd.DataFrame([{
            "Fecha": q.created_at.date(), "Tema": q.intent or "General",
            "Agencia": q.agency or "Sin agencia", "Confianza": q.confidence,
            "Tiempo_ms": q.elapsed_ms
        } for q in queries])
        st.subheader("Consultas por día")
        st.line_chart(df.groupby("Fecha").size())
        st.subheader("Temas más consultados")
        st.bar_chart(df.groupby("Tema").size().sort_values(ascending=False).head(15))
        st.subheader("Consultas por agencia")
        st.bar_chart(df.groupby("Agencia").size().sort_values(ascending=False).head(15))
        st.subheader("Tiempo promedio por tema")
        st.dataframe(
            df.groupby("Tema", as_index=False)["Tiempo_ms"].mean().sort_values("Tiempo_ms", ascending=False),
            use_container_width=True, hide_index=True
        )

elif view == "Aprendizaje":
    st.title("Aprendizaje supervisado")
    tabs = st.tabs(["Pendientes", "Sinónimos", "Preguntas frecuentes"])

    with tabs[0]:
        with db_session() as db:
            feedback = db.execute(
                select(Feedback, QueryLog)
                .join(QueryLog, QueryLog.id == Feedback.query_id)
                .where(Feedback.reviewed == False)
                .order_by(Feedback.id.desc())
            ).all()
        if not feedback:
            st.success("No hay retroalimentaciones pendientes.")
        for fb, q in feedback:
            with st.expander(f"#{fb.id} · {fb.rating} · {q.question[:90]}"):
                st.write("**Pregunta:**", q.question)
                st.write("**Respuesta encontrada:**", q.result_title, q.document_name, q.page_number)
                st.write("**Comentario:**", fb.comment or "—")
                st.write("**Solución real:**", fb.final_solution or "—")
                if st.button("Marcar revisada", key=f"review_{fb.id}"):
                    with db_session() as db:
                        row = db.get(Feedback, fb.id)
                        row.reviewed = True
                        db.commit()
                    audit(user["username"], "REVIEW_FEEDBACK", str(fb.id))
                    st.rerun()

    with tabs[1]:
        with st.form("synonym_form"):
            expression = st.text_input("Expresión del usuario", placeholder="RA")
            concept = st.text_input("Concepto oficial", placeholder="contrato")
            save = st.form_submit_button("Agregar")
        if save and expression.strip() and concept.strip():
            with db_session() as db:
                existing = db.scalar(select(Synonym).where(Synonym.expression == normalize(expression)))
                if existing:
                    existing.concept = normalize(concept)
                    existing.approved = True
                else:
                    db.add(Synonym(expression=normalize(expression), concept=normalize(concept), approved=True))
                db.commit()
            audit(user["username"], "UPSERT_SYNONYM", f"{expression}={concept}")
            st.success("Sinónimo guardado.")
            st.rerun()
        with db_session() as db:
            syns = db.scalars(select(Synonym).order_by(Synonym.concept, Synonym.expression)).all()
        st.dataframe(pd.DataFrame([{
            "ID": s.id, "Expresión": s.expression, "Concepto": s.concept, "Aprobado": s.approved
        } for s in syns]), use_container_width=True, hide_index=True)

    with tabs[2]:
        with st.form("faq_form"):
            fq = st.text_input("Pregunta")
            answer = st.text_area("Respuesta oficial")
            keywords = st.text_input("Palabras clave")
            source = st.text_input("Documento fuente")
            page = st.number_input("Página PDF", min_value=0, step=1)
            save_faq = st.form_submit_button("Guardar FAQ")
        if save_faq and fq.strip() and answer.strip():
            with db_session() as db:
                db.add(FAQ(
                    question=fq.strip(), normalized_question=normalize(fq),
                    answer=answer.strip(), keywords=keywords.strip(),
                    document_name=source.strip(), page_number=int(page) if page else None,
                    active=True
                ))
                db.commit()
            audit(user["username"], "CREATE_FAQ", fq)
            st.success("Respuesta oficial guardada.")
            st.rerun()
        with db_session() as db:
            faqs = db.scalars(select(FAQ).order_by(FAQ.id.desc())).all()
        st.dataframe(pd.DataFrame([{
            "ID": f.id, "Pregunta": f.question, "Documento": f.document_name,
            "Página": f.page_number, "Activa": f.active
        } for f in faqs]), use_container_width=True, hide_index=True)

elif view == "Usuarios":
    st.title("Usuarios y permisos")
    with st.form("user_form"):
        c1, c2 = st.columns(2)
        username = c1.text_input("Usuario").strip().lower()
        full_name = c2.text_input("Nombre completo")
        c3, c4 = st.columns(2)
        agency = c3.text_input("Agencia")
        role = c4.selectbox("Rol", ["agent", "supervisor", "admin"])
        password = st.text_input("Contraseña temporal", type="password")
        create = st.form_submit_button("Crear usuario")
    if create and username and password:
        with db_session() as db:
            if db.scalar(select(User).where(User.username == username)):
                st.error("El usuario ya existe.")
            else:
                db.add(User(
                    username=username, full_name=full_name.strip(), agency=agency.strip(),
                    role=role, password_hash=hash_password(password), active=True
                ))
                db.commit()
                audit(user["username"], "CREATE_USER", username)
                st.success("Usuario creado.")
                st.rerun()

    with db_session() as db:
        users = db.scalars(select(User).order_by(User.username)).all()
    st.dataframe(pd.DataFrame([{
        "ID": u.id, "Usuario": u.username, "Nombre": u.full_name, "Agencia": u.agency,
        "Rol": u.role, "Activo": u.active, "Creado": u.created_at
    } for u in users]), use_container_width=True, hide_index=True)

    st.subheader("Cambiar mi contraseña")
    new_password = st.text_input("Nueva contraseña", type="password")
    if st.button("Actualizar contraseña") and len(new_password) >= 8:
        with db_session() as db:
            row = db.get(User, user["id"])
            row.password_hash = hash_password(new_password)
            db.commit()
        audit(user["username"], "CHANGE_PASSWORD")
        st.success("Contraseña actualizada.")

elif view == "Auditoría":
    st.title("Auditoría")
    with db_session() as db:
        logs = db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(2000)).all()
    df = pd.DataFrame([{
        "Fecha": x.created_at, "Usuario": x.username, "Acción": x.action, "Detalle": x.detail
    } for x in logs])
    st.dataframe(df, use_container_width=True, hide_index=True)
    if not df.empty:
        st.download_button(
            "Exportar auditoría CSV",
            df.to_csv(index=False).encode("utf-8-sig"),
            "auditoria_arcplus.csv", "text/csv"
        )
