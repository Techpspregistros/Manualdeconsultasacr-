
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from intent_engine import route_question
from knowledge import compose_answer, search, search_faq
from knowledge_engine import compose_procedure_answer, procedure_to_dict


@dataclass
class KnowledgeAnswer:
    answer: str
    origin: str
    intent_label: str
    confidence: str
    elapsed_ms: int
    results: list
    procedure: dict | None
    business_intent: dict | None
    faq_match: Any = None
    warnings: list[str] | None = None


def answer_question(
    question: str,
    *,
    style: str = "Normal",
    limit: int = 7,
    categories: list[str] | None = None,
) -> KnowledgeAnswer:
    """
    Single entry point for every assistant query.

    Priority:
      1. Approved FAQ / official answer.
      2. Approved structured procedure.
      3. Safe PDF/document search.
      4. Explicit blocked response for strict business intents.
    """
    warnings: list[str] = []

    # Search the PDF engine once so it remains available as fallback and evidence.
    results, document_intent, document_confidence, elapsed = search(
        question,
        limit=limit,
        categories=categories or None,
    )

    # 1. Official answer.
    faq = search_faq(question)
    if faq:
        return KnowledgeAnswer(
            answer=compose_answer(question, results, faq, style=style),
            origin="Respuesta oficial",
            intent_label=document_intent or "Respuesta oficial",
            confidence="Alta",
            elapsed_ms=elapsed,
            results=results,
            procedure=None,
            business_intent=None,
            faq_match=faq,
            warnings=warnings,
        )

    # 2. Business router / approved procedure.
    decision = route_question(question)
    if decision.route == "procedure" and decision.procedure:
        match = decision.procedure
        business_intent = None
        if decision.intent:
            business_intent = {
                "code": decision.intent.code,
                "name": decision.intent.name,
                "score": decision.intent.score,
                "matched_alias": decision.intent.matched_alias,
            }

        return KnowledgeAnswer(
            answer=compose_procedure_answer(match, style=style),
            origin="Procedimiento estructurado",
            intent_label=(
                f"Proceso: {decision.intent.name}"
                if decision.intent
                else f"Procedimiento: {match.procedure.title}"
            ),
            confidence=match.confidence,
            elapsed_ms=elapsed,
            results=results,
            procedure=procedure_to_dict(match.procedure),
            business_intent=business_intent,
            warnings=warnings,
        )

    # 3. Strict intent without approved procedure: do not guess from the PDF.
    if decision.route == "blocked":
        return KnowledgeAnswer(
            answer=(
                "### Conocimiento pendiente de aprobación\n\n"
                + decision.message
            ),
            origin="Protección contra respuesta incorrecta",
            intent_label=(
                f"Proceso detectado: {decision.intent.name}"
                if decision.intent
                else "Proceso no disponible"
            ),
            confidence="Baja",
            elapsed_ms=elapsed,
            results=[],
            procedure=None,
            business_intent=(
                {
                    "code": decision.intent.code,
                    "name": decision.intent.name,
                    "score": decision.intent.score,
                    "matched_alias": decision.intent.matched_alias,
                }
                if decision.intent else None
            ),
            warnings=[
                "La búsqueda documental fue bloqueada para evitar mezclar procesos."
            ],
        )

    # 4. PDF fallback only when no official or structured answer exists.
    answer = compose_answer(question, results, None, style=style)
    if not results:
        warnings.append(
            "No se encontró un procedimiento aprobado ni suficiente información documental."
        )

    return KnowledgeAnswer(
        answer=answer,
        origin="Manual PDF",
        intent_label=document_intent or "Búsqueda documental",
        confidence=document_confidence,
        elapsed_ms=elapsed,
        results=results,
        procedure=None,
        business_intent=(
            {
                "code": decision.intent.code,
                "name": decision.intent.name,
                "score": decision.intent.score,
                "matched_alias": decision.intent.matched_alias,
            }
            if decision.intent else None
        ),
        warnings=warnings,
    )
