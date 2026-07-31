
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher

from sqlalchemy import select

from database import BusinessIntent, Procedure, db_session
from knowledge import normalize, tokenize
from knowledge_engine import ProcedureMatch, _procedure_score


DEFAULT_INTENTS = [
    {
        "code": "PRE_CIERRE",
        "name": "Realizar pre-cierre",
        "aliases": [
            "pre cierre", "pre-cierre", "realizar pre cierre",
            "hacer pre cierre", "iniciar pre cierre",
            "datos preliminares de cierre",
        ],
        "blocked_terms": [
            "cierre definitivo", "cerrar contrato",
            "reabrir contrato", "reapertura",
        ],
        "target": "Realizar pre-cierre",
        "strict": True,
    },
    {
        "code": "CIERRE_CONTRATO",
        "name": "Realizar cierre del contrato",
        "aliases": [
            "cerrar contrato", "cierre del contrato",
            "realizar cierre", "cierre definitivo",
        ],
        "blocked_terms": ["pre cierre", "pre-cierre", "reapertura"],
        "target": "Realizar cierre del contrato",
        "strict": True,
    },
    {
        "code": "REAPERTURA_CONTRATO",
        "name": "Reapertura del contrato",
        "aliases": [
            "reabrir contrato", "reapertura", "reapertura del contrato",
            "abrir contrato cerrado",
        ],
        "blocked_terms": ["pre cierre", "pre-cierre"],
        "target": "Reapertura del contrato",
        "strict": True,
    },
    {
        "code": "CAMBIO_VEHICULO",
        "name": "Cambio de vehículo",
        "aliases": [
            "cambio de vehículo", "cambio de vehiculo",
            "cambio de carro", "reemplazo de vehículo",
            "reemplazo de vehiculo",
        ],
        "blocked_terms": [],
        "target": "Cambio de vehículo",
        "strict": False,
    },
    {
        "code": "DEPOSITO_GARANTIA",
        "name": "Depósito de garantía",
        "aliases": [
            "depósito de garantía", "deposito de garantia",
            "registrar depósito", "registrar deposito",
        ],
        "blocked_terms": [],
        "target": "Depósito de garantía",
        "strict": False,
    },
]


@dataclass
class IntentMatch:
    intent_id: int
    code: str
    name: str
    target_procedure_title: str
    strict: bool
    score: float
    matched_alias: str
    reasons: list[str]


@dataclass
class RouteDecision:
    intent: IntentMatch | None
    procedure: ProcedureMatch | None
    route: str
    message: str = ""


def _loads(value: str | None) -> list[str]:
    try:
        data = json.loads(value or "[]")
        return [str(item).strip() for item in data if str(item).strip()]
    except (TypeError, ValueError, json.JSONDecodeError):
        return []


def _dumps(values: list[str] | str | None) -> str:
    if isinstance(values, str):
        values = [
            part.strip()
            for line in values.splitlines()
            for part in line.split(",")
            if part.strip()
        ]
    return json.dumps(values or [], ensure_ascii=False)


def seed_business_intents() -> None:
    with db_session() as db:
        existing_codes = set(db.scalars(select(BusinessIntent.code)).all())
        changed = False
        for spec in DEFAULT_INTENTS:
            if spec["code"] in existing_codes:
                continue
            db.add(BusinessIntent(
                code=spec["code"],
                name=spec["name"],
                normalized_name=normalize(spec["name"]),
                aliases_json=_dumps(spec["aliases"]),
                blocked_terms_json=_dumps(spec["blocked_terms"]),
                target_procedure_title=spec["target"],
                strict=spec["strict"],
                active=True,
            ))
            changed = True
        if changed:
            db.commit()


def list_intents(active_only: bool = False) -> list[dict]:
    seed_business_intents()
    with db_session() as db:
        stmt = select(BusinessIntent).order_by(BusinessIntent.name)
        if active_only:
            stmt = stmt.where(BusinessIntent.active == True)
        rows = db.scalars(stmt).all()
    return [{
        "id": row.id,
        "code": row.code,
        "name": row.name,
        "aliases": _loads(row.aliases_json),
        "blocked_terms": _loads(row.blocked_terms_json),
        "target_procedure_title": row.target_procedure_title,
        "strict": row.strict,
        "active": row.active,
    } for row in rows]


def save_intent(
    *,
    intent_id: int | None = None,
    code: str,
    name: str,
    aliases: list[str] | str,
    blocked_terms: list[str] | str = "",
    target_procedure_title: str = "",
    strict: bool = True,
    active: bool = True,
) -> int:
    clean_code = normalize(code).upper().replace(" ", "_")
    clean_name = name.strip()
    if not clean_code or not clean_name:
        raise ValueError("El código y el nombre son obligatorios.")

    with db_session() as db:
        row = db.get(BusinessIntent, intent_id) if intent_id else None
        if row is None:
            duplicate = db.scalar(
                select(BusinessIntent).where(BusinessIntent.code == clean_code)
            )
            if duplicate:
                raise ValueError("Ya existe una intención con ese código.")
            row = BusinessIntent(code=clean_code, name=clean_name)
            db.add(row)

        row.code = clean_code
        row.name = clean_name
        row.normalized_name = normalize(clean_name)
        row.aliases_json = _dumps(aliases)
        row.blocked_terms_json = _dumps(blocked_terms)
        row.target_procedure_title = target_procedure_title.strip() or clean_name
        row.strict = bool(strict)
        row.active = bool(active)
        row.updated_at = datetime.utcnow()
        db.commit()
        return row.id


def delete_intent(intent_id: int) -> None:
    with db_session() as db:
        row = db.get(BusinessIntent, intent_id)
        if not row:
            raise ValueError("Intención no encontrada.")
        db.delete(row)
        db.commit()


def detect_intent(question: str, minimum: float = 0.56) -> IntentMatch | None:
    seed_business_intents()
    qn = normalize(question)
    qtokens = set(tokenize(question))

    with db_session() as db:
        rows = db.scalars(
            select(BusinessIntent).where(BusinessIntent.active == True)
        ).all()

    candidates = []
    for row in rows:
        aliases = [row.name] + _loads(row.aliases_json)
        blocked = _loads(row.blocked_terms_json)

        best_score = 0.0
        best_alias = ""
        reasons: list[str] = []

        for alias in aliases:
            an = normalize(alias)
            atokens = set(tokenize(alias))
            score = 0.0

            if an and an in qn:
                score += 1.0
            if qn and qn in an:
                score += 0.72

            sequence = SequenceMatcher(None, qn, an).ratio()
            score += sequence * 0.42

            if qtokens:
                coverage = len(qtokens & atokens) / max(1, len(atokens))
                score += coverage * 0.48

            if score > best_score:
                best_score = score
                best_alias = alias

        blocked_hits = [term for term in blocked if normalize(term) in qn]
        if blocked_hits:
            best_score -= 0.9
            reasons.append("término excluido: " + ", ".join(blocked_hits))

        if best_alias and normalize(best_alias) in qn:
            reasons.append("expresión funcional exacta")
        if best_score >= minimum:
            candidates.append((best_score, row, best_alias, reasons))

    if not candidates:
        return None

    candidates.sort(key=lambda item: -item[0])
    score, row, alias, reasons = candidates[0]
    second = candidates[1][0] if len(candidates) > 1 else 0.0

    # If two different intents are almost tied, do not guess.
    if second and score - second < 0.10:
        return None

    return IntentMatch(
        intent_id=row.id,
        code=row.code,
        name=row.name,
        target_procedure_title=row.target_procedure_title,
        strict=row.strict,
        score=round(score, 3),
        matched_alias=alias,
        reasons=reasons,
    )


def _find_target_procedure(intent: IntentMatch, question: str) -> ProcedureMatch | None:
    with db_session() as db:
        rows = db.scalars(
            select(Procedure).where(Procedure.status == "approved")
        ).all()

    target_n = normalize(intent.target_procedure_title)
    scored = []
    for row in rows:
        row_title = row.normalized_title or normalize(row.title)
        score, reasons = _procedure_score(question, row)

        if target_n and row_title == target_n:
            score += 1.25
            reasons.append("procedimiento objetivo exacto")
        elif target_n and (
            target_n in row_title or row_title in target_n
        ):
            score += 0.72
            reasons.append("procedimiento objetivo relacionado")

        if intent.code == "PRE_CIERRE" and "pre cierre" not in row_title:
            score -= 1.0
        if intent.code == "CIERRE_CONTRATO" and "pre cierre" in row_title:
            score -= 0.8

        if score > 0.55:
            scored.append((score, row, reasons))

    if not scored:
        return None

    scored.sort(key=lambda item: -item[0])
    score, row, reasons = scored[0]
    second = scored[1][0] if len(scored) > 1 else 0.0
    confidence = (
        "Alta" if score >= 1.3 and score - second >= 0.15
        else "Media" if score >= 0.85
        else "Baja"
    )
    return ProcedureMatch(row, round(score, 3), confidence, reasons)



def _procedure_aliases(row: Procedure) -> list[str]:
    aliases = [row.title]
    aliases.extend(
        part.strip()
        for part in re.split(r"[,;\n]+", row.keywords or "")
        if part.strip()
    )
    aliases.extend([
        f"como hacer {row.title}",
        f"como realizar {row.title}",
        f"cual es {row.title}",
        f"cuales son {row.title}",
        f"informacion sobre {row.title}",
    ])

    unique = []
    seen = set()
    for value in aliases:
        key = normalize(value)
        if key and key not in seen:
            seen.add(key)
            unique.append(value)
    return unique


def detect_procedure_intent(question: str, minimum: float = 0.58) -> ProcedureMatch | None:
    """Detect any approved procedure from title, keywords and natural variants."""
    qn = normalize(question)
    qtokens = set(tokenize(question))

    with db_session() as db:
        rows = db.scalars(
            select(Procedure).where(Procedure.status == "approved")
        ).all()

    candidates = []
    for row in rows:
        best_alias_score = 0.0
        best_alias = ""
        for alias in _procedure_aliases(row):
            an = normalize(alias)
            atokens = set(tokenize(alias))
            score = 0.0

            if an and an in qn:
                score += 1.0
            if qn and qn in an:
                score += 0.76
            score += SequenceMatcher(None, qn, an).ratio() * 0.42

            if qtokens and atokens:
                common = qtokens & atokens
                score += (len(common) / max(1, len(qtokens))) * 0.34
                score += (len(common) / max(1, len(atokens))) * 0.44

            if score > best_alias_score:
                best_alias_score = score
                best_alias = alias

        title_score, reasons = _procedure_score(question, row)
        total = max(best_alias_score, title_score)

        all_tokens = set(tokenize(row.title + " " + (row.keywords or "")))
        overlap = qtokens & all_tokens
        if len(overlap) >= 2:
            total += 0.25
            reasons.append("múltiples conceptos del procedimiento")
        elif len(overlap) == 1 and len(qtokens) >= 3:
            total -= 0.12

        if total >= minimum:
            if best_alias:
                reasons.append(f"alias: {best_alias}")
            candidates.append((total, row, reasons))

    if not candidates:
        return None

    candidates.sort(key=lambda item: -item[0])
    score, row, reasons = candidates[0]
    second = candidates[1][0] if len(candidates) > 1 else 0.0
    if second and score - second < 0.10:
        return None

    confidence = (
        "Alta" if score >= 1.15 and score - second >= 0.14
        else "Media" if score >= 0.78
        else "Baja"
    )
    return ProcedureMatch(row, round(score, 3), confidence, reasons)


def ensure_intent_for_procedure(procedure_id: int) -> int:
    """Create or update the functional intent for an approved procedure."""
    with db_session() as db:
        procedure = db.get(Procedure, procedure_id)
        if not procedure:
            raise ValueError("Procedimiento no encontrado.")
        if procedure.status != "approved":
            raise ValueError("Solo se sincronizan procedimientos aprobados.")

        code_base = normalize(procedure.code or procedure.title).upper().replace(" ", "_")
        code_base = re.sub(r"[^A-Z0-9_]+", "_", code_base).strip("_")
        code = f"AUTO_{code_base}"[:80]

        row = db.scalar(
            select(BusinessIntent).where(
                BusinessIntent.target_procedure_title == procedure.title
            )
        )
        if row is None:
            row = db.scalar(
                select(BusinessIntent).where(BusinessIntent.code == code)
            )
        if row is None:
            row = BusinessIntent(code=code, name=procedure.title)
            db.add(row)

        row.name = procedure.title
        row.normalized_name = normalize(procedure.title)
        row.aliases_json = _dumps(_procedure_aliases(procedure))
        row.blocked_terms_json = _dumps([])
        row.target_procedure_title = procedure.title
        row.strict = False
        row.active = True
        row.updated_at = datetime.utcnow()
        db.commit()
        return row.id


def sync_approved_procedure_intents() -> int:
    with db_session() as db:
        procedure_ids = db.scalars(
            select(Procedure.id).where(Procedure.status == "approved")
        ).all()

    for procedure_id in procedure_ids:
        ensure_intent_for_procedure(procedure_id)
    return len(procedure_ids)

def route_question(question: str) -> RouteDecision:
    intent = detect_intent(question)
    if intent:
        procedure = _find_target_procedure(intent, question)
        if procedure:
            return RouteDecision(intent=intent, procedure=procedure, route="procedure")

        if intent.strict:
            return RouteDecision(
                intent=intent,
                procedure=None,
                route="blocked",
                message=(
                    f"Identifiqué la consulta como **{intent.name}**, pero todavía no "
                    "existe un procedimiento estructurado aprobado para ese proceso. "
                    "Para evitar una respuesta incorrecta o mezclarla con otro proceso, "
                    "la búsqueda documental fue detenida."
                ),
            )

    dynamic = detect_procedure_intent(question)
    if dynamic:
        dynamic_intent = IntentMatch(
            intent_id=0,
            code=f"PROC_{dynamic.procedure.id}",
            name=dynamic.procedure.title,
            target_procedure_title=dynamic.procedure.title,
            strict=False,
            score=dynamic.score,
            matched_alias=dynamic.procedure.title,
            reasons=dynamic.reasons,
        )
        return RouteDecision(
            intent=dynamic_intent,
            procedure=dynamic,
            route="procedure",
        )

    if intent:
        return RouteDecision(intent=intent, procedure=None, route="document")

    return RouteDecision(intent=None, procedure=None, route="document")
