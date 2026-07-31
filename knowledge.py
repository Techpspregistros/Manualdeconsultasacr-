
from __future__ import annotations

import math
import re
import time
import unicodedata
from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

import fitz
from sqlalchemy import delete, select

from database import Document, DocumentPage, FAQ, QueryLog, Synonym, db_session


STOPWORDS = {
    "a","al","algo","como","con","cual","cuando","de","del","desde","donde","el",
    "ella","en","es","esta","este","hacer","la","las","lo","los","me","mi","para",
    "por","que","se","sin","sobre","su","un","una","y","puedo","debo","quiero",
    "necesito","favor","hay","tengo","tiene","esto","eso","ese","esa"
}

DEFAULT_SYNONYMS = {
    "ra": "contrato",
    "renta": "contrato",
    "carro": "vehiculo",
    "auto": "vehiculo",
    "unidad": "vehiculo",
    "cerrar": "cierre",
    "finalizar": "cierre",
    "terminar": "cierre",
    "pegado": "error",
    "bloqueado": "error",
    "no funciona": "error",
    "reservacion": "reserva",
    "email": "correo",
    "matricula": "placa",
    "facturacion": "factura",
    "deposito": "garantia",
}

INTENTS = {
    "Apertura de contrato": ["abrir contrato", "apertura contrato", "contrato nuevo"],
    "Cierre de contrato": ["cerrar contrato", "cierre contrato", "finalizar contrato", "pre cierre"],
    "Cambio de vehículo": ["cambio vehiculo", "cambiar carro", "reemplazar vehiculo"],
    "Pagos y garantía": ["registrar pago", "metodo pago", "deposito garantia", "tarjeta garantia"],
    "Facturación": ["factura", "imprimir factura", "enviar factura"],
    "Cortes": ["crear corte", "anular corte", "corte contabilidad"],
    "Reservas": ["buscar reserva", "reservacion", "numero reserva"],
    "Consulta de contrato": ["buscar contrato", "numero contrato", "consulta contrato"],
    "Firma": ["firma digital", "firmar contrato", "contrato firmado"],
    "Problema técnico": ["error", "no permite", "bloqueado", "no funciona"],
}


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFD", (text or "").lower())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = re.sub(r"[^a-z0-9\s-]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def tokenize(text: str) -> list[str]:
    return [t for t in normalize(text).replace("-", " ").split() if len(t) > 2 and t not in STOPWORDS]


def page_title(text: str) -> str:
    lines = [re.sub(r"\s+", " ", x).strip() for x in text.splitlines() if x.strip()]
    for line in lines:
        if re.match(r"^\d+(?:\.\d+)*(?:\s|-)", line) and len(line) < 260:
            return line
    for line in lines:
        if 6 <= len(line) <= 220 and "Adobe Rent a Car" not in line:
            return line
    return "Sección del manual"


def internal_page(text: str):
    m = re.search(r"Página\s+(\d+)\s+de\s+\d+", text, re.I)
    return int(m.group(1)) if m else None


@dataclass
class SearchResult:
    document_name: str
    filename: str
    page_number: int
    internal_page: int | None
    title: str
    excerpt: str
    score: float
    confidence: str
    matches: list[str]


def seed_synonyms() -> None:
    with db_session() as db:
        existing = {x.expression for x in db.scalars(select(Synonym)).all()}
        for expression, concept in DEFAULT_SYNONYMS.items():
            if expression not in existing:
                db.add(Synonym(expression=expression, concept=concept, approved=True))
        db.commit()


def index_pdf(path: Path, name: str | None = None, category: str = "General", version: str = "") -> int:
    name = name or path.stem
    doc = fitz.open(path)
    with db_session() as db:
        existing = db.scalar(select(Document).where(Document.name == name))
        if existing:
            db.execute(delete(DocumentPage).where(DocumentPage.document_id == existing.id))
            document = existing
            document.filename = path.name
            document.category = category
            document.version = version
            document.page_count = len(doc)
            document.active = True
        else:
            document = Document(
                name=name, filename=path.name, category=category,
                version=version, page_count=len(doc), active=True
            )
            db.add(document)
            db.flush()

        for i, page in enumerate(doc):
            raw = page.get_text("text") or ""
            clean = re.sub(r"\s+", " ", raw).strip()
            db.add(DocumentPage(
                document_id=document.id,
                page_number=i + 1,
                internal_page=internal_page(raw),
                title=page_title(raw),
                text=clean,
                normalized=normalize(clean),
            ))
        db.commit()
        document_id = document.id
    doc.close()
    return document_id


def index_manual_directory(directory: Path) -> list[str]:
    indexed = []
    for pdf in sorted(directory.glob("*.pdf")):
        index_pdf(pdf)
        indexed.append(pdf.name)
    return indexed


def expand_terms(tokens: list[str]) -> set[str]:
    expanded = set(tokens)
    with db_session() as db:
        rows = db.scalars(select(Synonym).where(Synonym.approved == True)).all()
    for row in rows:
        exp = normalize(row.expression)
        con = normalize(row.concept)
        if exp in expanded or con in expanded or any(t in exp.split() for t in tokens):
            expanded.update(tokenize(exp))
            expanded.update(tokenize(con))
    return expanded


def detect_intent(question: str) -> str:
    q = normalize(question)
    q_tokens = set(tokenize(q))
    best_name, best_score = "General", 0.0
    for name, phrases in INTENTS.items():
        score = 0.0
        for phrase in phrases:
            p = normalize(phrase)
            if p in q:
                score += 6
            score += 1.6 * len(q_tokens & set(tokenize(p)))
            score += SequenceMatcher(None, q, p).ratio()
        if score > best_score:
            best_name, best_score = name, score
    return best_name if best_score >= 2 else "General"


def search_faq(question: str):
    q = normalize(question)
    qt = set(tokenize(q))
    best = None
    with db_session() as db:
        faqs = db.scalars(select(FAQ).where(FAQ.active == True)).all()
    for faq in faqs:
        ft = set(tokenize(faq.normalized_question + " " + (faq.keywords or "")))
        sim = SequenceMatcher(None, q, faq.normalized_question).ratio()
        coverage = len(qt & ft) / max(1, len(qt))
        score = 0.65 * sim + 0.35 * coverage
        if score >= 0.55 and (best is None or score > best[0]):
            best = (score, faq)
    return best


def _excerpt(text: str, query_tokens: set[str], length: int = 1050) -> str:
    norm = normalize(text)
    positions = [norm.find(t) for t in query_tokens if norm.find(t) >= 0]
    center = min(positions) if positions else 0
    start = max(0, center - 220)
    end = min(len(text), start + length)
    return ("..." if start else "") + text[start:end].strip() + ("..." if end < len(text) else "")


def search(question: str, limit: int = 8, categories: list[str] | None = None):
    started = time.perf_counter()
    q_norm = normalize(question)
    base = tokenize(question)
    terms = expand_terms(base)
    intent = detect_intent(question)
    terms.update(tokenize(intent))

    with db_session() as db:
        stmt = (
            select(DocumentPage, Document)
            .join(Document, Document.id == DocumentPage.document_id)
            .where(Document.active == True)
        )
        if categories:
            stmt = stmt.where(Document.category.in_(categories))
        rows = db.execute(stmt).all()

    total = max(1, len(rows))
    df = Counter()
    for page, _ in rows:
        for term in terms:
            if term in page.normalized:
                df[term] += 1

    scored = []
    for page, document in rows:
        matches = [t for t in terms if t in page.normalized]
        if not matches:
            continue
        score = 0.0
        if q_norm and q_norm in page.normalized:
            score += 20
        for term in terms:
            freq = page.normalized.count(term)
            if freq:
                idf = math.log((total + 1) / (df[term] + 1)) + 1
                score += min(freq, 7) * idf * 1.45
        title_norm = normalize(page.title)
        score += sum(3.2 for t in base if t in title_norm)
        positions = [page.normalized.find(t) for t in base if page.normalized.find(t) >= 0]
        if len(positions) >= 2 and max(positions) - min(positions) < 800:
            score += 5
        score += SequenceMatcher(None, q_norm, page.normalized[:1200]).ratio() * 5
        scored.append((score, page, document, matches))

    scored.sort(key=lambda x: -x[0])
    first = scored[0][0] if scored else 0
    second = scored[1][0] if len(scored) > 1 else 0
    if first >= 25 and first - second >= 2:
        confidence = "Alta"
    elif first >= 13:
        confidence = "Media"
    else:
        confidence = "Baja"

    results = [
        SearchResult(
            document_name=document.name,
            filename=document.filename,
            page_number=page.page_number,
            internal_page=page.internal_page,
            title=page.title,
            excerpt=_excerpt(page.text, set(base) or terms),
            score=round(score, 2),
            confidence=confidence,
            matches=sorted(matches),
        )
        for score, page, document, matches in scored[:limit]
    ]
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return results, intent, confidence, elapsed_ms


def compose_answer(question: str, results: list[SearchResult], faq_match=None) -> str:
    if faq_match:
        score, faq = faq_match
        source = ""
        if faq.document_name:
            source = f"\n\n**Fuente aprobada:** {faq.document_name}"
            if faq.page_number:
                source += f", página PDF {faq.page_number}"
            source += "."
        return f"### Respuesta oficial\n\n{faq.answer}{source}\n\n_Confianza de coincidencia FAQ: {score:.0%}._"

    if not results:
        return (
            "### No encontré una respuesta documentada\n\n"
            "La pregunta quedó registrada para revisión. Incluya el nombre de la pantalla, "
            "el botón, el número de proceso o el mensaje de error para mejorar la búsqueda."
        )

    lines = [
        "### Respuesta basada exclusivamente en la documentación",
        f"**Pregunta:** {question}",
        f"**Confianza:** {results[0].confidence}",
        "",
        "Revise estos pasos o referencias en el orden mostrado:",
    ]
    for i, r in enumerate(results[:4], 1):
        lines += [
            f"**{i}. {r.title}**",
            r.excerpt,
            f"_Fuente: {r.document_name}, página PDF {r.page_number}"
            + (f", página interna {r.internal_page}._" if r.internal_page else "._"),
            "",
        ]
    if results[0].confidence == "Baja":
        lines.append("> La coincidencia es débil. No aplique un procedimiento crítico sin verificar la página fuente.")
    else:
        lines.append("> El asistente no agrega pasos que no estén presentes en los documentos indexados.")
    return "\n\n".join(lines)


def render_page(manual_dir: Path, filename: str, page_number: int) -> bytes:
    path = manual_dir / filename
    doc = fitz.open(path)
    pix = doc[page_number - 1].get_pixmap(matrix=fitz.Matrix(1.45, 1.45), alpha=False)
    data = pix.tobytes("png")
    doc.close()
    return data
