
from __future__ import annotations

import math
import re
import time
import unicodedata
from datetime import datetime
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
            document.indexed_at = datetime.utcnow()
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


def _clean_for_summary(text: str) -> str:
    """Remove common PDF noise while preserving the manual's wording."""
    text = re.sub(r"P[aá]gina\s+\d+\s+de\s+\d+", " ", text, flags=re.I)
    text = re.sub(r"\b(?:p[aá]g(?:ina)?\.?\s*)\d+\b", " ", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip(" .-–—")
    return text


def _sentence_candidates(text: str) -> list[str]:
    cleaned = _clean_for_summary(text)
    parts = re.split(r"(?<=[.!?;:])\s+|\s+[•▪◦]\s+", cleaned)
    sentences = []
    for part in parts:
        part = part.strip(" -–—•▪◦\t\n")
        if 35 <= len(part) <= 330 and len(tokenize(part)) >= 4:
            sentences.append(part)
    return sentences


def concise_summary(question: str, texts: list[str], max_points: int = 3, max_chars: int = 700) -> list[str]:
    """Create a short extractive answer using only sentences found in the sources."""
    q_terms = set(expand_terms(tokenize(question)))
    candidates: list[tuple[float, int, str]] = []
    order = 0
    for source_rank, text in enumerate(texts):
        for sentence in _sentence_candidates(text):
            terms = set(tokenize(sentence))
            overlap = len(q_terms & terms)
            if overlap == 0 and q_terms:
                continue
            score = overlap * 4.0
            score += min(len(terms), 30) / 30
            score += max(0, 2.0 - source_rank * 0.35)
            if any(word in normalize(sentence) for word in ("debe", "seleccione", "ingrese", "registre", "verifique", "realice", "presione")):
                score += 1.25
            candidates.append((score, order, sentence))
            order += 1

    candidates.sort(key=lambda item: (-item[0], item[1]))
    selected: list[tuple[int, str]] = []
    used_norm: list[str] = []
    total = 0
    for _, original_order, sentence in candidates:
        norm = normalize(sentence)
        if any(SequenceMatcher(None, norm, previous).ratio() > 0.82 for previous in used_norm):
            continue
        projected = total + len(sentence)
        if selected and projected > max_chars:
            continue
        selected.append((original_order, sentence))
        used_norm.append(norm)
        total = projected
        if len(selected) >= max_points:
            break

    selected.sort(key=lambda item: item[0])
    return [sentence for _, sentence in selected]


def compose_answer(question: str, results: list[SearchResult], faq_match=None) -> str:
    if faq_match:
        _, faq = faq_match
        points = concise_summary(question, [faq.answer], max_points=3, max_chars=650)
        if not points:
            answer = _clean_for_summary(faq.answer)
            points = [answer[:650].rsplit(" ", 1)[0] + ("…" if len(answer) > 650 else "")]
        return "### Respuesta breve\n\n" + "\n\n".join(f"- {point}" for point in points)

    if not results:
        return (
            "### No encontré una respuesta documentada\n\n"
            "Describa la pantalla, el botón, el proceso o el mensaje de error para precisar la búsqueda."
        )

    points = concise_summary(question, [r.excerpt for r in results[:4]], max_points=3, max_chars=700)
    if not points:
        fallback = _clean_for_summary(results[0].excerpt)
        fallback = fallback[:700].rsplit(" ", 1)[0] + ("…" if len(fallback) > 700 else "")
        points = [fallback]

    answer = "### Respuesta breve\n\n" + "\n\n".join(f"- {point}" for point in points)
    if results[0].confidence == "Baja":
        answer += "\n\n_La coincidencia es limitada; confirme el procedimiento antes de aplicarlo._"
    return answer


def render_page(manual_dir: Path, filename: str, page_number: int) -> bytes:
    path = manual_dir / filename
    doc = fitz.open(path)
    pix = doc[page_number - 1].get_pixmap(matrix=fitz.Matrix(1.45, 1.45), alpha=False)
    data = pix.tobytes("png")
    doc.close()
    return data


def update_document_metadata(document_id: int, name: str, category: str, version: str, active: bool) -> None:
    """Update document metadata without rebuilding its page index."""
    clean_name = (name or "").strip()
    if not clean_name:
        raise ValueError("El nombre del documento es obligatorio.")
    with db_session() as db:
        document = db.get(Document, document_id)
        if not document:
            raise ValueError("El documento ya no existe.")
        duplicate = db.scalar(
            select(Document).where(Document.name == clean_name, Document.id != document_id)
        )
        if duplicate:
            raise ValueError("Ya existe otro documento con ese nombre.")
        document.name = clean_name
        document.category = (category or "General").strip() or "General"
        document.version = (version or "").strip()
        document.active = bool(active)
        db.commit()


def delete_document(document_id: int, manuals_directory: Path, delete_file: bool = True) -> tuple[str, bool]:
    """Delete a document and its index; remove the PDF only when no other record uses it."""
    with db_session() as db:
        document = db.get(Document, document_id)
        if not document:
            raise ValueError("El documento ya no existe.")
        filename = document.filename
        name = document.name
        db.execute(delete(DocumentPage).where(DocumentPage.document_id == document_id))
        db.delete(document)
        db.commit()

    removed_file = False
    if delete_file:
        with db_session() as db:
            still_used = db.scalar(select(Document).where(Document.filename == filename))
        path = manuals_directory / filename
        if not still_used and path.exists():
            path.unlink()
            removed_file = True
    return name, removed_file
