
from __future__ import annotations

import csv
import html
import io
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from sqlalchemy import func, select

from database import (
    AuditLog, BusinessIntent, Document, FAQ, Feedback, Procedure, QueryLog, Synonym, User,
    db_session, init_db
)
from knowledge import (
    compose_answer, contextualize_question, delete_document, index_manual_directory, index_pdf,
    normalize, render_page, search, search_faq, seed_synonyms, update_document_metadata
)
from security import hash_password, initial_admin_password, verify_password
from quality import promote_feedback_to_faq, quality_metrics, recurring_unresolved, similar_questions
from knowledge_engine import (
    compose_procedure_answer, delete_procedure, detect_procedure_candidates,
    import_candidate, list_procedures, procedure_to_dict, save_procedure,
    search_procedure,
)
from intent_engine import (
    delete_intent, detect_intent, ensure_intent_for_procedure, list_intents,
    route_question, save_intent, seed_business_intents,
    sync_approved_procedure_intents,
)


BASE = Path(__file__).resolve().parent
MANUALS = BASE / "manuals"
DATA = BASE / "data"
MANUALS.mkdir(exist_ok=True)
DATA.mkdir(exist_ok=True)

st.set_page_config(page_title="ARC+ Enterprise v8.1", page_icon="🧠", layout="wide")

st.markdown("""
<style>
.block-container {max-width: 1500px; padding-top: 1rem;}
[data-testid="stMetric"] {border:1px solid #e5e7eb;border-radius:12px;padding:10px;}
.role {padding:4px 9px;border-radius:12px;background:#eef2ff;font-size:.8rem;}
.source {font-size:.86rem;color:#555;}
</style>
""", unsafe_allow_html=True)


def answer_to_plain_text(markdown_text: str) -> str:
    """Convert the assistant Markdown response into clean text for speech."""
    text = re.sub(r"```.*?```", " ", markdown_text, flags=re.DOTALL)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"[*_~>]", "", text)
    text = re.sub(r"^\s*[-+•]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\s+", " ", text).strip()
    return html.unescape(text)


def render_audio_reader(answer: str, key: str = "answer") -> None:
    """Render a no-cost browser-based Spanish text-to-speech reader."""
    speech_text = answer_to_plain_text(answer)
    if not speech_text:
        return

    safe_text = json.dumps(speech_text, ensure_ascii=False)
    component_id = re.sub(r"[^a-zA-Z0-9_-]", "_", key)
    components.html(
        f"""
        <div id="arc-tts-{component_id}" style="font-family: Arial, sans-serif; border:1px solid #e5e7eb;
             border-radius:12px; padding:14px; background:#fafafa;">
          <div style="font-weight:700; margin-bottom:10px;">🔊 Asistente de lectura</div>
          <div style="display:flex; flex-wrap:wrap; gap:8px; align-items:center;">
            <button id="play-{component_id}" style="padding:8px 12px; cursor:pointer;">▶ Escuchar</button>
            <button id="pause-{component_id}" style="padding:8px 12px; cursor:pointer;">⏸ Pausar</button>
            <button id="resume-{component_id}" style="padding:8px 12px; cursor:pointer;">⏯ Continuar</button>
            <button id="stop-{component_id}" style="padding:8px 12px; cursor:pointer;">⏹ Detener</button>
            <label style="margin-left:4px;">Velocidad
              <select id="rate-{component_id}" style="padding:7px; margin-left:4px;">
                <option value="0.8">0.8×</option>
                <option value="1" selected>1×</option>
                <option value="1.2">1.2×</option>
                <option value="1.4">1.4×</option>
              </select>
            </label>
            <label>Voz
              <select id="voice-{component_id}" style="padding:7px; margin-left:4px; max-width:260px;"></select>
            </label>
          </div>
          <div id="status-{component_id}" style="font-size:13px; color:#555; margin-top:9px;">Listo para leer.</div>
        </div>
        <script>
          (() => {{
            const text = {safe_text};
            const synth = window.speechSynthesis;
            const voiceSelect = document.getElementById('voice-{component_id}');
            const rateSelect = document.getElementById('rate-{component_id}');
            const status = document.getElementById('status-{component_id}');
            let utterance = null;
            let voices = [];

            function loadVoices() {{
              voices = synth.getVoices();
              const spanish = voices.filter(v => (v.lang || '').toLowerCase().startsWith('es'));
              const options = spanish.length ? spanish : voices;
              voiceSelect.innerHTML = '';
              options.forEach((voice) => {{
                const option = document.createElement('option');
                option.value = voices.indexOf(voice);
                option.textContent = `${{voice.name}} (${{voice.lang}})`;
                voiceSelect.appendChild(option);
              }});
              const preferred = options.find(v => /costa rica|es-cr/i.test(`${{v.name}} ${{v.lang}}`))
                || options.find(v => /mex|latin|es-419/i.test(`${{v.name}} ${{v.lang}}`))
                || options[0];
              if (preferred) voiceSelect.value = voices.indexOf(preferred);
            }}

            loadVoices();
            if ('onvoiceschanged' in synth) synth.onvoiceschanged = loadVoices;

            document.getElementById('play-{component_id}').onclick = () => {{
              synth.cancel();
              utterance = new SpeechSynthesisUtterance(text);
              utterance.lang = 'es-CR';
              utterance.rate = Number(rateSelect.value || 1);
              const selectedVoice = voices[Number(voiceSelect.value)];
              if (selectedVoice) utterance.voice = selectedVoice;
              utterance.onstart = () => status.textContent = 'Leyendo la respuesta…';
              utterance.onpause = () => status.textContent = 'Lectura pausada.';
              utterance.onresume = () => status.textContent = 'Continuando la lectura…';
              utterance.onend = () => status.textContent = 'Lectura finalizada.';
              utterance.onerror = (event) => status.textContent = `No se pudo reproducir el audio: ${{event.error || 'error del navegador'}}.`;
              synth.speak(utterance);
            }};
            document.getElementById('pause-{component_id}').onclick = () => {{
              if (synth.speaking && !synth.paused) synth.pause();
            }};
            document.getElementById('resume-{component_id}').onclick = () => {{
              if (synth.paused) synth.resume();
            }};
            document.getElementById('stop-{component_id}').onclick = () => {{
              synth.cancel();
              status.textContent = 'Lectura detenida.';
            }};
            window.addEventListener('beforeunload', () => synth.cancel());
          }})();
        </script>
        """,
        height=145,
        scrolling=False,
    )


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
    st.caption("Plataforma inteligente de gestión del conocimiento — versión 8.1")
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
    if user["role"] in ("supervisor", "admin"):
        options += ["Centro de conocimiento"]
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
    st.title("🤖 Asistente inteligente conversacional")
    st.caption(
        "Respuestas breves basadas en la biblioteca. Las fuentes se mantienen separadas "
        "para que el audio lea únicamente la respuesta útil."
    )

    if "conversation" not in st.session_state:
        st.session_state["conversation"] = []

    c1, c2 = st.columns([3, 1])
    with c2:
        selected_categories = st.multiselect(
            "Categorías", categories(), default=categories()
        )
        response_style = st.selectbox(
            "Estilo de respuesta",
            ["Ejecutiva", "Normal", "Detallada", "Capacitación"],
            index=1,
            help=(
                "Ejecutiva: 1–2 ideas. Normal: hasta 3 ideas. "
                "Detallada: hasta 5 ideas. Capacitación: explicación más amplia."
            ),
        )
        limit = st.slider("Fuentes a revisar", 3, 12, 7)
        use_context = st.checkbox(
            "Usar contexto de la conversación",
            value=True,
            help="Relaciona preguntas breves con el tema anterior.",
        )
        show_pages = st.checkbox("Mostrar imagen de la página fuente", False)
        if st.button("🧹 Nueva conversación", use_container_width=True):
            st.session_state["conversation"] = []
            st.session_state.pop("last", None)
            st.session_state["question"] = ""
            st.rerun()

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

    for message in st.session_state["conversation"]:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    with c1:
        if st.session_state.pop("clear_question", False):
            st.session_state["question"] = ""

        question = st.text_area(
            "Pregunta",
            key="question",
            height=105,
            placeholder="Describa el proceso, pantalla, botón o mensaje de error.",
        )
        ask = st.button("Consultar", type="primary")

    if ask and question.strip():
        visible_question = question.strip()
        search_question = (
            contextualize_question(visible_question, st.session_state["conversation"])
            if use_context
            else visible_question
        )

        faq = search_faq(search_question)
        route = route_question(search_question) if not faq else None
        procedure_match = route.procedure if route else None

        results, intent, confidence, elapsed = search(
            search_question,
            limit=limit,
            categories=selected_categories or None,
        )

        if faq:
            answer = compose_answer(
                search_question, results, faq, style=response_style
            )
            answer_origin = "Respuesta oficial"
        elif route and route.route == "procedure" and procedure_match:
            answer = compose_procedure_answer(
                procedure_match, style=response_style
            )
            confidence = procedure_match.confidence
            intent = f"Proceso: {route.intent.name}"
            answer_origin = "Proceso de negocio estructurado"
        elif route and route.route == "blocked":
            answer = "### Conocimiento pendiente de aprobación\n\n" + route.message
            confidence = "Baja"
            intent = f"Proceso detectado: {route.intent.name}"
            answer_origin = "Protección contra respuesta incorrecta"
            results = []
        else:
            answer = compose_answer(
                search_question, results, None, style=response_style
            )
            if route and route.intent:
                intent = f"Proceso detectado: {route.intent.name}"
            answer_origin = "Búsqueda documental"

        with db_session() as db:
            log = QueryLog(
                user_id=user["id"],
                username=user["username"],
                agency=user["agency"],
                question=visible_question,
                intent=intent,
                confidence=confidence,
                result_title=results[0].title if results else "",
                document_name=results[0].document_name if results else "",
                page_number=results[0].page_number if results else None,
                elapsed_ms=elapsed,
            )
            db.add(log)
            db.commit()
            query_id = log.id

        st.session_state["conversation"].extend([
            {"role": "user", "content": visible_question},
            {"role": "assistant", "content": answer},
        ])
        st.session_state["last"] = {
            "question": visible_question,
            "search_question": search_question,
            "faq": faq,
            "results": results,
            "intent": intent,
            "confidence": confidence,
            "elapsed": elapsed,
            "query_id": query_id,
            "answer": answer,
            "style": response_style,
            "procedure": procedure_to_dict(procedure_match.procedure) if procedure_match else None,
            "answer_origin": answer_origin,
            "business_intent": {
                "code": route.intent.code,
                "name": route.intent.name,
                "score": route.intent.score,
                "matched_alias": route.intent.matched_alias,
            } if route and route.intent else None,
        }
        st.session_state["clear_question"] = True
        st.rerun()

    last = st.session_state.get("last")
    if last:
        confidence_icons = {"Alta": "🟢", "Media": "🟡", "Baja": "🔴"}
        m1, m2, m3 = st.columns(3)
        m1.metric("Intención", last["intent"])
        m2.metric(
            "Confianza",
            f"{confidence_icons.get(last['confidence'], '⚪')} {last['confidence']}",
        )
        m3.metric("Tiempo", f"{last['elapsed']} ms")
        st.caption(
            f"Origen de la respuesta: **{last.get('answer_origin', 'Búsqueda documental')}**"
        )
        business_intent = last.get("business_intent")
        if business_intent:
            st.caption(
                f"Proceso detectado: **{business_intent['name']}** · "
                f"Coincidencia: {business_intent['score']:.0%}"
            )

        render_audio_reader(last["answer"], key=f"answer_{last['query_id']}")

        text_export = (
            f"ARC+ ENTERPRISE V6\nFecha: {datetime.now():%Y-%m-%d %H:%M}\n"
            f"Usuario: {user['username']}\nPregunta: {last['question']}\n\n"
            + answer_to_plain_text(last["answer"])
        )
        st.download_button(
            "Descargar respuesta",
            text_export,
            "respuesta_arcplus.txt",
            "text/plain",
        )

        with st.expander("📚 Ver fuentes utilizadas", expanded=False):
            procedure = last.get("procedure")
            if procedure:
                st.markdown(
                    f"**Procedimiento estructurado: {procedure['title']}**"
                )
                st.caption(
                    f"Código: {procedure['code'] or '—'} · "
                    f"Versión: {procedure['version']} · "
                    f"Documento fuente: {procedure['source_document'] or '—'}"
                )
                if procedure["related"]:
                    st.write("**Relacionado con:**", procedure["related"])
                st.divider()

            if not last["results"] and not procedure:
                st.info("No se localizaron fuentes documentales suficientes.")
            for i, r in enumerate(last["results"], 1):
                st.markdown(f"**{i}. {r.title}**")
                st.caption(f"Documento: {r.document_name}")
                st.write(r.excerpt)
                st.caption("Coincidencias: " + ", ".join(r.matches))
                if show_pages:
                    try:
                        st.image(
                            render_page(MANUALS, r.filename, r.page_number),
                            caption=f"Vista de la fuente {i}",
                            use_container_width=True,
                        )
                    except Exception as exc:
                        st.warning(f"No se pudo mostrar la página: {exc}")
                st.divider()

        similar = similar_questions(last["question"], limit=5)
        if similar:
            with st.expander("🔎 Consultas similares realizadas anteriormente", expanded=False):
                for item in similar:
                    status = "Resuelta" if item["resolved"] else "Pendiente"
                    st.markdown(
                        f"- **{item['question']}**  \\n"
                        f"  Similitud: {item['score']:.0%} · {status} · "
                        f"Confianza: {item['confidence'] or '—'}"
                    )

        if last["confidence"] == "Baja":
            st.warning(
                "La coincidencia documental es limitada. Revise las fuentes antes de "
                "aplicar un procedimiento crítico."
            )

        st.divider()
        st.subheader("Retroalimentación")
        rating = st.radio(
            "¿La respuesta resolvió la consulta?",
            ["Resuelta", "Parcial", "No resuelta", "Incorrecta"],
            horizontal=True,
            key=f"rating_{last['query_id']}",
        )
        comment = st.text_area(
            "Comentario opcional",
            key=f"comment_{last['query_id']}",
        )
        solution = st.text_area(
            "¿Cómo se resolvió finalmente? (útil para aprendizaje)",
            key=f"solution_{last['query_id']}",
        )
        if st.button(
            "Guardar retroalimentación",
            key=f"save_feedback_{last['query_id']}",
        ):
            with db_session() as db:
                db.add(Feedback(
                    query_id=last["query_id"],
                    rating=rating,
                    comment=comment.strip(),
                    final_solution=solution.strip(),
                ))
                if rating == "Resuelta":
                    log = db.get(QueryLog, last["query_id"])
                    log.resolved = True
                db.commit()
            audit(
                user["username"],
                "FEEDBACK",
                f"Consulta {last['query_id']}: {rating}",
            )
            st.success("Retroalimentación guardada para revisión.")

elif view == "Biblioteca":
    st.title("📚 Biblioteca inteligente")
    st.caption("Administre, consulte, actualice y elimine los manuales disponibles para el asistente.")

    with db_session() as db:
        all_docs = db.scalars(select(Document).order_by(Document.category, Document.name)).all()

    total_pages = sum(d.page_count or 0 for d in all_docs)
    active_docs = sum(1 for d in all_docs if d.active)
    total_bytes = 0
    for d in all_docs:
        pdf_path = MANUALS / d.filename
        if pdf_path.exists():
            total_bytes += pdf_path.stat().st_size

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Manuales", len(all_docs))
    m2.metric("Activos", active_docs)
    m3.metric("Páginas indexadas", total_pages)
    m4.metric("Espacio utilizado", f"{total_bytes / (1024 * 1024):.1f} MB")

    query = st.text_input("🔍 Buscar manual", placeholder="Nombre, categoría, versión o archivo…")
    q = normalize(query)
    docs = [
        d for d in all_docs
        if not q or q in normalize(f"{d.name} {d.category} {d.version} {d.filename}")
    ]

    if docs:
        st.subheader(f"Documentos ({len(docs)})")
        for d in docs:
            status = "✅ Activo" if d.active else "⏸ Inactivo"
            version_label = f" · v{d.version}" if d.version else ""
            with st.expander(f"📄 {d.name}{version_label} — {status}"):
                info1, info2, info3, info4 = st.columns(4)
                info1.caption("Categoría")
                info1.write(d.category or "General")
                info2.caption("Páginas")
                info2.write(d.page_count)
                info3.caption("Archivo")
                info3.write(d.filename)
                info4.caption("Última indexación")
                info4.write(d.indexed_at.strftime("%d/%m/%Y %H:%M") if d.indexed_at else "—")

                pdf_path = MANUALS / d.filename
                a1, a2, a3, a4 = st.columns(4)
                if a1.button("👁 Ver", key=f"view_doc_{d.id}", use_container_width=True):
                    st.session_state[f"show_doc_{d.id}"] = not st.session_state.get(f"show_doc_{d.id}", False)
                if pdf_path.exists():
                    a2.download_button(
                        "📥 Descargar", data=pdf_path.read_bytes(), file_name=d.filename,
                        mime="application/pdf", key=f"download_doc_{d.id}", use_container_width=True,
                    )
                else:
                    a2.button("📥 No disponible", disabled=True, key=f"missing_doc_{d.id}", use_container_width=True)

                if user["role"] == "admin":
                    if a3.button("🔄 Reindexar", key=f"reindex_doc_{d.id}", use_container_width=True):
                        if not pdf_path.exists():
                            st.error("No se encontró el PDF original en la carpeta manuals.")
                        else:
                            with st.spinner("Reconstruyendo el índice…"):
                                index_pdf(pdf_path, name=d.name, category=d.category, version=d.version)
                            audit(user["username"], "REINDEX_DOCUMENT", d.name)
                            st.success("Documento reindexado correctamente.")
                            st.rerun()
                    if a4.button("🗑 Eliminar", key=f"ask_delete_doc_{d.id}", use_container_width=True):
                        st.session_state["confirm_delete_document"] = d.id

                if st.session_state.get(f"show_doc_{d.id}"):
                    if pdf_path.exists():
                        try:
                            st.image(
                                render_page(MANUALS, d.filename, 1),
                                caption=f"Vista previa de {d.name} — primera página",
                                use_container_width=True,
                            )
                            st.caption("Use Descargar para abrir o guardar el PDF completo.")
                        except Exception as exc:
                            st.warning(f"No se pudo generar la vista previa: {exc}")
                    else:
                        st.warning("El registro existe, pero el archivo PDF no está disponible.")

                if user["role"] == "admin":
                    with st.form(f"edit_document_{d.id}"):
                        st.markdown("**✏ Editar información**")
                        e1, e2, e3, e4 = st.columns([2, 1.3, 1, 0.8])
                        edited_name = e1.text_input("Nombre", value=d.name, key=f"name_{d.id}")
                        edited_category = e2.text_input("Categoría", value=d.category, key=f"category_{d.id}")
                        edited_version = e3.text_input("Versión", value=d.version, key=f"version_{d.id}")
                        edited_active = e4.checkbox("Activo", value=d.active, key=f"active_{d.id}")
                        save_metadata = st.form_submit_button("Guardar cambios")
                    if save_metadata:
                        try:
                            update_document_metadata(
                                d.id, edited_name, edited_category, edited_version, edited_active
                            )
                            audit(user["username"], "UPDATE_DOCUMENT", f"ID {d.id}: {edited_name}")
                            st.success("Información actualizada.")
                            st.rerun()
                        except ValueError as exc:
                            st.error(str(exc))

                if st.session_state.get("confirm_delete_document") == d.id and user["role"] == "admin":
                    st.warning(
                        "Esta acción eliminará el manual de la biblioteca, todas sus páginas indexadas "
                        "y el PDF almacenado. No se puede deshacer."
                    )
                    c_yes, c_no = st.columns(2)
                    if c_yes.button("Sí, eliminar definitivamente", type="primary", key=f"confirm_delete_{d.id}", use_container_width=True):
                        try:
                            deleted_name, removed_file = delete_document(d.id, MANUALS, delete_file=True)
                            audit(
                                user["username"], "DELETE_DOCUMENT",
                                f"{deleted_name}; PDF eliminado: {removed_file}",
                            )
                            st.session_state.pop("confirm_delete_document", None)
                            st.success(f"Se eliminó “{deleted_name}” correctamente.")
                            st.rerun()
                        except (ValueError, OSError) as exc:
                            st.error(f"No se pudo eliminar el documento: {exc}")
                    if c_no.button("Cancelar", key=f"cancel_delete_{d.id}", use_container_width=True):
                        st.session_state.pop("confirm_delete_document", None)
                        st.rerun()
    else:
        st.info("No hay documentos que coincidan con la búsqueda.")

    if user["role"] == "admin":
        st.divider()
        st.subheader("➕ Agregar o actualizar documento")
        with st.form("upload_document", clear_on_submit=True):
            uploaded = st.file_uploader("Archivo PDF", type=["pdf"])
            c1, c2, c3 = st.columns([2, 1.3, 1])
            name = c1.text_input("Nombre documental")
            category = c2.text_input("Categoría", value="General")
            version = c3.text_input("Versión")
            mode = st.radio(
                "Si ya existe un documento con el mismo nombre",
                ["Reemplazar y reindexar", "Crear como nueva versión"],
                horizontal=True,
            )
            submitted_document = st.form_submit_button("Guardar e indexar", type="primary")

        if submitted_document:
            if not uploaded:
                st.error("Seleccione un archivo PDF.")
            else:
                safe_name = Path(uploaded.name).name
                requested_name = name.strip() or Path(safe_name).stem
                with db_session() as db:
                    existing = db.scalar(select(Document).where(Document.name == requested_name))
                final_name = requested_name
                if existing and mode == "Crear como nueva versión":
                    suffix = version.strip() or datetime.now().strftime("%Y%m%d-%H%M")
                    final_name = f"{requested_name} - v{suffix}"
                target = MANUALS / safe_name
                if existing and mode == "Crear como nueva versión" and target.exists():
                    target = MANUALS / f"{target.stem}_{datetime.now().strftime('%Y%m%d%H%M%S')}{target.suffix}"
                target.write_bytes(uploaded.getbuffer())
                with st.spinner("Indexando el manual…"):
                    index_pdf(
                        target, name=final_name,
                        category=category.strip() or "General", version=version.strip(),
                    )
                audit(user["username"], "INDEX_DOCUMENT", f"{final_name} ({target.name})")
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

elif view == "Centro de conocimiento":
    st.title("🧠 Centro de conocimiento")
    st.caption(
        "Los procedimientos aprobados tienen prioridad sobre los fragmentos de PDF. "
        "Cada procedimiento aprobado genera automáticamente su comprensión de IA."
    )
    if user["role"] == "admin":
        if st.button("🔄 Sincronizar comprensión de todos los procedimientos"):
            synced = sync_approved_procedure_intents()
            audit(
                user["username"],
                "SYNC_PROCEDURE_INTENTS",
                f"{synced} procedimientos",
            )
            st.success(f"Se sincronizaron {synced} procedimientos aprobados.")

    approved = list_procedures(status="approved")
    drafts = list_procedures(status="draft")
    inactive = list_procedures(status="inactive")
    c1, c2, c3 = st.columns(3)
    c1.metric("Aprobados", len(approved))
    c2.metric("Borradores", len(drafts))
    c3.metric("Inactivos", len(inactive))

    tabs = st.tabs(["Procedimientos", "Crear procedimiento", "Catálogo funcional", "Detectar desde manuales"])

    with tabs[0]:
        filter_status = st.selectbox(
            "Estado", ["Todos", "approved", "draft", "inactive"]
        )
        procedure_query = st.text_input("Buscar procedimiento")
        rows = list_procedures(
            status=None if filter_status == "Todos" else filter_status,
            query=procedure_query,
        )
        for item in rows:
            status_display = {
                "approved": "✅ Aprobado",
                "draft": "📝 Borrador",
                "inactive": "⏸ Inactivo",
            }.get(item["status"], item["status"])
            with st.expander(
                f"{status_display} · {item['code'] or 'Sin código'} · {item['title']}"
            ):
                st.write(item["objective"] or "Sin objetivo registrado.")
                for index, step in enumerate(item["steps"], 1):
                    st.write(f"{index}. {step}")
                st.caption(
                    f"Dominio: {item['domain']} · Versión: {item['version']} · "
                    f"Fuente: {item['source_document'] or '—'}"
                )
                if user["role"] == "admin":
                    with st.form(f"edit_procedure_{item['id']}"):
                        ec1, ec2, ec3 = st.columns(3)
                        code = ec1.text_input("Código", item["code"])
                        title = ec2.text_input("Título", item["title"])
                        domain = ec3.text_input("Dominio", item["domain"])
                        objective = st.text_area("Objetivo", item["objective"])
                        steps = st.text_area("Pasos, uno por línea", "\n".join(item["steps"]))
                        requirements = st.text_area(
                            "Requisitos, uno por línea", "\n".join(item["requirements"])
                        )
                        exceptions = st.text_area(
                            "Excepciones, una por línea", "\n".join(item["exceptions"])
                        )
                        ec4, ec5, ec6 = st.columns(3)
                        responsible = ec4.text_input("Responsable", item["responsible"])
                        version = ec5.text_input("Versión", item["version"])
                        status = ec6.selectbox(
                            "Estado", ["draft", "approved", "inactive"],
                            index=["draft", "approved", "inactive"].index(item["status"]),
                        )
                        keywords = st.text_input("Palabras clave", item["keywords"])
                        related = st.text_input("Relacionado con", item["related"])
                        sc1, sc2 = st.columns(2)
                        source_document = sc1.text_input(
                            "Documento fuente", item["source_document"]
                        )
                        source_page = sc2.number_input(
                            "Página de referencia", min_value=0,
                            value=int(item["source_page"] or 0), step=1
                        )
                        if st.form_submit_button("Guardar cambios"):
                            saved_id = save_procedure(
                                procedure_id=item["id"], code=code, title=title,
                                domain=domain, objective=objective, steps=steps,
                                requirements=requirements, exceptions=exceptions,
                                responsible=responsible, keywords=keywords,
                                related=related, source_document=source_document,
                                source_page=int(source_page) if source_page else None,
                                version=version, status=status,
                                username=user["username"],
                            )
                            if status == "approved":
                                ensure_intent_for_procedure(saved_id)
                            audit(user["username"], "UPDATE_PROCEDURE", title)
                            st.success("Procedimiento actualizado.")
                            st.rerun()

                    confirm = st.checkbox(
                        "Confirmo la eliminación",
                        key=f"confirm_delete_procedure_{item['id']}",
                    )
                    if st.button(
                        "🗑 Eliminar procedimiento",
                        key=f"delete_procedure_{item['id']}",
                        disabled=not confirm,
                    ):
                        delete_procedure(item["id"])
                        audit(user["username"], "DELETE_PROCEDURE", item["title"])
                        st.rerun()

    with tabs[1]:
        if user["role"] != "admin":
            st.info("Solo un administrador puede crear procedimientos.")
        else:
            with st.form("create_procedure"):
                nc1, nc2, nc3 = st.columns(3)
                code = nc1.text_input("Código", placeholder="2.6.2.3")
                title = nc2.text_input("Título", placeholder="Realizar pre-cierre")
                domain = nc3.text_input("Dominio", value="Contratos")
                objective = st.text_area("Objetivo")
                steps = st.text_area("Pasos, uno por línea")
                requirements = st.text_area("Requisitos, uno por línea")
                exceptions = st.text_area("Excepciones, una por línea")
                nc4, nc5 = st.columns(2)
                responsible = nc4.text_input("Responsable")
                version = nc5.text_input("Versión", value="1.0")
                keywords = st.text_input("Palabras clave")
                related = st.text_input("Relacionado con")
                nc6, nc7 = st.columns(2)
                source_document = nc6.text_input("Documento fuente")
                source_page = nc7.number_input(
                    "Página de referencia", min_value=0, step=1
                )
                status = st.selectbox("Estado", ["draft", "approved"])
                if st.form_submit_button("Crear procedimiento"):
                    errors = []
                    if not title.strip():
                        errors.append("Ingrese el título del procedimiento.")
                    if not objective.strip():
                        errors.append("Ingrese el objetivo del procedimiento.")
                    if not any(line.strip() for line in steps.splitlines()):
                        errors.append("Ingrese al menos un paso.")
                    if errors:
                        for error in errors:
                            st.error(error)
                    else:
                        try:
                            new_id = save_procedure(
                                code=code, title=title, domain=domain,
                                objective=objective, steps=steps,
                                requirements=requirements, exceptions=exceptions,
                                responsible=responsible, keywords=keywords,
                                related=related, source_document=source_document,
                                source_page=int(source_page) if source_page else None,
                                version=version, status=status,
                                username=user["username"],
                            )
                            if status == "approved":
                                ensure_intent_for_procedure(new_id)
                            audit(
                                user["username"],
                                "CREATE_PROCEDURE",
                                f"{new_id}:{title}",
                            )
                            st.success("Procedimiento creado y sincronizado.")
                            st.rerun()
                        except ValueError as exc:
                            st.error(str(exc))


    with tabs[2]:
        st.subheader("Catálogo funcional de procesos")
        st.caption(
            "Este catálogo identifica la intención real del usuario antes de buscar "
            "en documentos. Las intenciones estrictas bloquean una respuesta documental "
            "cuando no existe un procedimiento aprobado, evitando mezclar procesos."
        )

        intents = list_intents()
        for item in intents:
            state = "Activo" if item["active"] else "Inactivo"
            strict_label = "Estricto" if item["strict"] else "Flexible"
            with st.expander(
                f"{state} · {strict_label} · {item['code']} · {item['name']}"
            ):
                st.write("**Alias:**", ", ".join(item["aliases"]) or "—")
                st.write(
                    "**Términos excluidos:**",
                    ", ".join(item["blocked_terms"]) or "—",
                )
                st.write(
                    "**Procedimiento objetivo:**",
                    item["target_procedure_title"] or item["name"],
                )

                if user["role"] == "admin":
                    with st.form(f"edit_intent_{item['id']}"):
                        ic1, ic2 = st.columns(2)
                        code = ic1.text_input("Código", item["code"])
                        name = ic2.text_input("Nombre del proceso", item["name"])
                        aliases = st.text_area(
                            "Alias, separados por coma o línea",
                            "\n".join(item["aliases"]),
                        )
                        blocked_terms = st.text_area(
                            "Términos excluidos",
                            "\n".join(item["blocked_terms"]),
                        )
                        target = st.text_input(
                            "Título del procedimiento objetivo",
                            item["target_procedure_title"],
                        )
                        ic3, ic4 = st.columns(2)
                        strict = ic3.checkbox(
                            "Bloquear búsqueda documental si falta el procedimiento",
                            value=item["strict"],
                        )
                        active = ic4.checkbox("Activo", value=item["active"])
                        if st.form_submit_button("Guardar intención"):
                            save_intent(
                                intent_id=item["id"],
                                code=code,
                                name=name,
                                aliases=aliases,
                                blocked_terms=blocked_terms,
                                target_procedure_title=target,
                                strict=strict,
                                active=active,
                            )
                            audit(
                                user["username"],
                                "UPDATE_BUSINESS_INTENT",
                                f"{item['id']}:{code}",
                            )
                            st.success("Intención actualizada.")
                            st.rerun()

        if user["role"] == "admin":
            st.divider()
            st.subheader("Crear una intención")
            with st.form("create_business_intent"):
                ni1, ni2 = st.columns(2)
                new_code = ni1.text_input(
                    "Código funcional", placeholder="EXTENSION_CONTRATO"
                )
                new_name = ni2.text_input(
                    "Nombre del proceso", placeholder="Extensión del contrato"
                )
                new_aliases = st.text_area(
                    "Alias",
                    placeholder="extender contrato\nampliar contrato\nextensión",
                )
                new_blocked = st.text_area("Términos excluidos")
                new_target = st.text_input(
                    "Procedimiento objetivo",
                    placeholder="Extensión del contrato",
                )
                ni3, ni4 = st.columns(2)
                new_strict = ni3.checkbox(
                    "Intención estricta", value=True
                )
                new_active = ni4.checkbox("Activa", value=True)
                if st.form_submit_button("Crear intención"):
                    try:
                        intent_id = save_intent(
                            code=new_code,
                            name=new_name,
                            aliases=new_aliases,
                            blocked_terms=new_blocked,
                            target_procedure_title=new_target,
                            strict=new_strict,
                            active=new_active,
                        )
                        audit(
                            user["username"],
                            "CREATE_BUSINESS_INTENT",
                            f"{intent_id}:{new_code}",
                        )
                        st.success("Intención creada.")
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))

    with tabs[3]:
        candidates = detect_procedure_candidates()
        st.metric("Candidatos detectados", len(candidates))
        for index, candidate in enumerate(candidates[:100]):
            with st.expander(
                f"{candidate['code']} · {candidate['title']} · "
                f"{candidate['source_document']}"
            ):
                st.write(candidate["excerpt"])
                if user["role"] == "admin" and st.button(
                    "Importar como borrador", key=f"import_candidate_{index}"
                ):
                    procedure_id = import_candidate(
                        candidate, username=user["username"]
                    )
                    audit(
                        user["username"], "IMPORT_PROCEDURE_CANDIDATE",
                        f"{procedure_id}:{candidate['title']}",
                    )
                    st.rerun()

elif view == "Aprendizaje":
    st.title("🧠 Aprendizaje supervisado y calidad")

    metrics = quality_metrics()
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Consultas", metrics["total"])
    m2.metric("Tasa resuelta", f"{metrics['resolution_rate']}%")
    m3.metric("Confianza baja", metrics["low_confidence"])
    m4.metric("Por revisar", metrics["pending_feedback"])
    m5.metric("Respuestas oficiales", metrics["official_faqs"])

    tabs = st.tabs([
        "Retroalimentación pendiente",
        "Preguntas recurrentes",
        "Sinónimos",
        "Respuestas oficiales",
    ])

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
            label = f"#{fb.id} · {fb.rating} · {q.question[:90]}"
            with st.expander(label):
                st.write("**Pregunta:**", q.question)
                st.write("**Tema detectado:**", q.intent or "—")
                st.write("**Confianza:**", q.confidence or "—")
                st.write("**Documento encontrado:**", q.document_name or "—")
                st.write("**Comentario:**", fb.comment or "—")
                st.write("**Solución real:**", fb.final_solution or "—")

                c1, c2 = st.columns(2)
                if c1.button(
                    "✅ Convertir en respuesta oficial",
                    key=f"promote_{fb.id}",
                    disabled=not bool((fb.final_solution or fb.comment or "").strip()),
                    use_container_width=True,
                ):
                    try:
                        faq_id = promote_feedback_to_faq(fb.id)
                        audit(
                            user["username"],
                            "PROMOTE_FEEDBACK_TO_FAQ",
                            f"Feedback {fb.id} -> FAQ {faq_id}",
                        )
                        st.success("La solución quedó disponible como respuesta oficial.")
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))

                if c2.button(
                    "Marcar revisada sin publicar",
                    key=f"review_{fb.id}",
                    use_container_width=True,
                ):
                    with db_session() as db:
                        row = db.get(Feedback, fb.id)
                        row.reviewed = True
                        db.commit()
                    audit(user["username"], "REVIEW_FEEDBACK", str(fb.id))
                    st.rerun()

    with tabs[1]:
        st.caption(
            "Agrupa preguntas no resueltas o de confianza baja para identificar "
            "vacíos de documentación."
        )
        recurring = recurring_unresolved(limit=25)
        if not recurring:
            st.success("No hay preguntas recurrentes pendientes.")
        for i, item in enumerate(recurring, 1):
            with st.expander(
                f"{i}. {item['sample'][:100]} · {item['count']} consultas"
            ):
                st.write("**Tema:**", item["intent"] or "General")
                st.write("**Última consulta:**", item["latest"])
                st.write("**Variantes encontradas:**")
                for question_variant in item["questions"][:10]:
                    st.markdown(f"- {question_variant}")

    with tabs[2]:
        with st.form("synonym_form"):
            expression = st.text_input("Expresión del usuario", placeholder="RA")
            concept = st.text_input("Concepto oficial", placeholder="contrato")
            save = st.form_submit_button("Agregar")
        if save and expression.strip() and concept.strip():
            with db_session() as db:
                existing = db.scalar(
                    select(Synonym).where(
                        Synonym.expression == normalize(expression)
                    )
                )
                if existing:
                    existing.concept = normalize(concept)
                    existing.approved = True
                else:
                    db.add(Synonym(
                        expression=normalize(expression),
                        concept=normalize(concept),
                        approved=True,
                    ))
                db.commit()
            audit(user["username"], "UPSERT_SYNONYM", f"{expression}={concept}")
            st.success("Sinónimo guardado.")
            st.rerun()

        with db_session() as db:
            syns = db.scalars(
                select(Synonym).order_by(Synonym.concept, Synonym.expression)
            ).all()
        st.dataframe(
            pd.DataFrame([{
                "ID": s.id,
                "Expresión": s.expression,
                "Concepto": s.concept,
                "Aprobado": s.approved,
            } for s in syns]),
            use_container_width=True,
            hide_index=True,
        )

    with tabs[3]:
        with st.form("faq_form"):
            fq = st.text_input("Pregunta")
            answer = st.text_area("Respuesta oficial")
            keywords = st.text_input("Palabras clave")
            source = st.text_input("Documento fuente")
            page = st.number_input("Página PDF", min_value=0, step=1)
            save_faq = st.form_submit_button("Guardar respuesta oficial")

        if save_faq and fq.strip() and answer.strip():
            with db_session() as db:
                db.add(FAQ(
                    question=fq.strip(),
                    normalized_question=normalize(fq),
                    answer=answer.strip(),
                    keywords=keywords.strip(),
                    document_name=source.strip(),
                    page_number=int(page) if page else None,
                    active=True,
                ))
                db.commit()
            audit(user["username"], "CREATE_FAQ", fq)
            st.success("Respuesta oficial guardada.")
            st.rerun()

        with db_session() as db:
            faqs = db.scalars(select(FAQ).order_by(FAQ.id.desc())).all()

        for faq in faqs:
            with st.expander(
                f"#{faq.id} · {faq.question[:95]} · "
                f"{'Activa' if faq.active else 'Inactiva'}"
            ):
                st.write(faq.answer)
                st.caption(
                    f"Documento: {faq.document_name or '—'} · "
                    f"Palabras clave: {faq.keywords or '—'}"
                )
                c1, c2 = st.columns(2)
                if c1.button(
                    "Activar" if not faq.active else "Desactivar",
                    key=f"toggle_faq_{faq.id}",
                    use_container_width=True,
                ):
                    with db_session() as db:
                        row = db.get(FAQ, faq.id)
                        row.active = not row.active
                        db.commit()
                    audit(
                        user["username"],
                        "TOGGLE_FAQ",
                        f"{faq.id}:{not faq.active}",
                    )
                    st.rerun()

                if c2.button(
                    "Eliminar respuesta oficial",
                    key=f"delete_faq_{faq.id}",
                    use_container_width=True,
                ):
                    with db_session() as db:
                        row = db.get(FAQ, faq.id)
                        db.delete(row)
                        db.commit()
                    audit(user["username"], "DELETE_FAQ", str(faq.id))
                    st.rerun()

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
