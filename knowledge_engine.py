
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher

from sqlalchemy import select

from database import Document, DocumentPage, Procedure, db_session
from knowledge import normalize, tokenize


@dataclass
class ProcedureMatch:
    procedure: Procedure
    score: float
    confidence: str
    reasons: list[str]


def _loads_list(value: str | None) -> list[str]:
    try:
        data = json.loads(value or "[]")
        return [str(item).strip() for item in data if str(item).strip()]
    except (TypeError, ValueError, json.JSONDecodeError):
        return []


def _dumps_list(items: list[str] | str | None) -> str:
    if isinstance(items, str):
        items = [line.strip(" -•\t") for line in items.splitlines() if line.strip()]
    return json.dumps(items or [], ensure_ascii=False)


def procedure_to_dict(row: Procedure) -> dict:
    return {
        "id": row.id,
        "code": row.code,
        "title": row.title,
        "domain": row.domain,
        "objective": row.objective,
        "steps": _loads_list(row.steps_json),
        "requirements": _loads_list(row.requirements_json),
        "exceptions": _loads_list(row.exceptions_json),
        "responsible": row.responsible,
        "keywords": row.keywords,
        "related": row.related,
        "source_document": row.source_document,
        "source_page": row.source_page,
        "version": row.version,
        "status": row.status,
        "created_by": row.created_by,
        "updated_at": row.updated_at,
    }


def save_procedure(
    *,
    procedure_id: int | None = None,
    code: str = "",
    title: str,
    domain: str = "General",
    objective: str = "",
    steps: list[str] | str | None = None,
    requirements: list[str] | str | None = None,
    exceptions: list[str] | str | None = None,
    responsible: str = "",
    keywords: str = "",
    related: str = "",
    source_document: str = "",
    source_page: int | None = None,
    version: str = "1.0",
    status: str = "draft",
    username: str = "",
) -> int:
    clean_title = title.strip()
    if not clean_title:
        raise ValueError("El título del procedimiento es obligatorio.")
    if status not in {"draft", "approved", "inactive"}:
        raise ValueError("Estado inválido.")

    with db_session() as db:
        row = db.get(Procedure, procedure_id) if procedure_id else None
        if row is None:
            row = Procedure(title=clean_title, normalized_title=normalize(clean_title))
            db.add(row)

        row.code = code.strip()
        row.title = clean_title
        row.normalized_title = normalize(clean_title)
        row.domain = domain.strip() or "General"
        row.objective = objective.strip()
        row.steps_json = _dumps_list(steps)
        row.requirements_json = _dumps_list(requirements)
        row.exceptions_json = _dumps_list(exceptions)
        row.responsible = responsible.strip()
        row.keywords = keywords.strip()
        row.related = related.strip()
        row.source_document = source_document.strip()
        row.source_page = source_page or None
        row.version = version.strip() or "1.0"
        row.status = status
        row.created_by = row.created_by or username
        row.updated_at = datetime.utcnow()
        db.commit()
        return row.id


def delete_procedure(procedure_id: int) -> None:
    with db_session() as db:
        row = db.get(Procedure, procedure_id)
        if not row:
            raise ValueError("Procedimiento no encontrado.")
        db.delete(row)
        db.commit()


def list_procedures(status: str | None = None, query: str = "") -> list[dict]:
    with db_session() as db:
        stmt = select(Procedure).order_by(Procedure.domain, Procedure.title)
        if status:
            stmt = stmt.where(Procedure.status == status)
        rows = db.scalars(stmt).all()

    q = normalize(query)
    output = []
    for row in rows:
        item = procedure_to_dict(row)
        haystack = normalize(" ".join([
            row.code, row.title, row.domain, row.objective,
            row.keywords, row.related, row.responsible,
        ]))
        if q and q not in haystack:
            continue
        output.append(item)
    return output


def _procedure_score(question: str, row: Procedure) -> tuple[float, list[str]]:
    qn = normalize(question)
    title = row.normalized_title or normalize(row.title)
    q_tokens = set(tokenize(question))
    title_tokens = set(tokenize(row.title))
    keyword_tokens = set(tokenize(row.keywords))
    code = normalize(row.code)

    score = 0.0
    reasons: list[str] = []

    if code and code in qn:
        score += 1.0
        reasons.append("código exacto")
    if title and title in qn:
        score += 0.95
        reasons.append("título exacto")
    elif qn and qn in title:
        score += 0.82
        reasons.append("pregunta contenida en título")

    sequence = SequenceMatcher(None, qn, title).ratio()
    score += sequence * 0.45
    if sequence >= 0.72:
        reasons.append("título muy similar")

    if q_tokens:
        title_coverage = len(q_tokens & title_tokens) / max(1, len(q_tokens))
        keyword_coverage = len(q_tokens & keyword_tokens) / max(1, len(q_tokens))
        score += title_coverage * 0.55
        score += keyword_coverage * 0.28
        if title_coverage >= 0.6:
            reasons.append("conceptos coincidentes")

    # Evita confundir pre-cierre con cierre.
    if "pre cierre" in qn and "pre cierre" not in title:
        score -= 0.75
    if "cierre" in qn and "pre cierre" not in qn and "pre cierre" in title:
        score -= 0.35

    return max(score, 0.0), reasons


def search_procedure(question: str, minimum: float = 0.64) -> ProcedureMatch | None:
    with db_session() as db:
        rows = db.scalars(
            select(Procedure).where(Procedure.status == "approved")
        ).all()

    scored = []
    for row in rows:
        score, reasons = _procedure_score(question, row)
        if score >= minimum:
            scored.append((score, row, reasons))
    if not scored:
        return None

    scored.sort(key=lambda item: -item[0])
    score, row, reasons = scored[0]
    second = scored[1][0] if len(scored) > 1 else 0.0
    confidence = (
        "Alta" if score >= 1.1 and score - second >= 0.12
        else "Media" if score >= 0.78
        else "Baja"
    )
    return ProcedureMatch(row, round(score, 3), confidence, reasons)


def compose_procedure_answer(match: ProcedureMatch, style: str = "Normal") -> str:
    item = procedure_to_dict(match.procedure)
    max_steps = {
        "Ejecutiva": 3,
        "Normal": 5,
        "Detallada": 9,
        "Capacitación": 12,
    }.get(style, 5)

    lines = [f"### {item['title']}"]
    if item["objective"]:
        lines.extend(["", item["objective"]])

    if item["steps"]:
        lines.extend(["", "**Pasos principales**"])
        lines.extend(
            f"{index}. {step}"
            for index, step in enumerate(item["steps"][:max_steps], 1)
        )

    if style in {"Detallada", "Capacitación"}:
        if item["requirements"]:
            lines.extend(["", "**Requisitos**"])
            lines.extend(f"- {value}" for value in item["requirements"])
        if item["exceptions"]:
            lines.extend(["", "**Excepciones o consideraciones**"])
            lines.extend(f"- {value}" for value in item["exceptions"])
        if item["responsible"]:
            lines.extend(["", f"**Responsable:** {item['responsible']}"])
    return "\n".join(lines)


HEADING_RE = re.compile(
    r"^(?P<code>\d+(?:\.\d+){1,6})\s*[-–:]?\s*(?P<title>.{4,180})$"
)


def detect_procedure_candidates() -> list[dict]:
    with db_session() as db:
        rows = db.execute(
            select(DocumentPage, Document)
            .join(Document, Document.id == DocumentPage.document_id)
            .where(Document.active == True)
        ).all()
        existing = {
            (normalize(row.code), normalize(row.title))
            for row in db.scalars(select(Procedure)).all()
        }

    candidates = []
    seen = set()
    for page, document in rows:
        title = re.sub(r"\s+", " ", page.title or "").strip()
        match = HEADING_RE.match(title)
        if not match:
            continue
        code = match.group("code").strip()
        clean_title = match.group("title").strip(" -–:")
        key = (normalize(code), normalize(clean_title))
        if key in existing or key in seen:
            continue
        seen.add(key)
        candidates.append({
            "code": code,
            "title": clean_title,
            "domain": document.category or "General",
            "objective": "",
            "steps": [],
            "requirements": [],
            "exceptions": [],
            "responsible": "",
            "keywords": clean_title,
            "related": "",
            "source_document": document.name,
            "source_page": page.page_number,
            "version": document.version or "1.0",
            "status": "draft",
            "excerpt": page.text[:900],
        })
    return candidates


def import_candidate(candidate: dict, username: str = "") -> int:
    return save_procedure(
        code=candidate.get("code", ""),
        title=candidate.get("title", ""),
        domain=candidate.get("domain", "General"),
        objective=candidate.get("objective", ""),
        steps=candidate.get("steps", []),
        requirements=candidate.get("requirements", []),
        exceptions=candidate.get("exceptions", []),
        responsible=candidate.get("responsible", ""),
        keywords=candidate.get("keywords", ""),
        related=candidate.get("related", ""),
        source_document=candidate.get("source_document", ""),
        source_page=candidate.get("source_page"),
        version=candidate.get("version", "1.0"),
        status="draft",
        username=username,
    )
