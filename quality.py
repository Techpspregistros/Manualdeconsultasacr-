from __future__ import annotations

from collections import Counter
from difflib import SequenceMatcher

from sqlalchemy import func, select

from database import FAQ, Feedback, QueryLog, db_session
from knowledge import normalize, tokenize


def question_similarity(left: str, right: str) -> float:
    left_n = normalize(left)
    right_n = normalize(right)
    left_t = set(tokenize(left))
    right_t = set(tokenize(right))
    overlap = len(left_t & right_t) / max(1, len(left_t | right_t))
    sequence = SequenceMatcher(None, left_n, right_n).ratio()
    return round((0.55 * overlap) + (0.45 * sequence), 4)


def similar_questions(question: str, limit: int = 5, minimum: float = 0.38) -> list[dict]:
    with db_session() as db:
        rows = db.scalars(
            select(QueryLog).order_by(QueryLog.id.desc()).limit(1500)
        ).all()

    matches = []
    for row in rows:
        if normalize(row.question) == normalize(question):
            continue
        score = question_similarity(question, row.question)
        if score >= minimum:
            matches.append({
                "id": row.id,
                "question": row.question,
                "intent": row.intent,
                "confidence": row.confidence,
                "resolved": row.resolved,
                "score": score,
                "created_at": row.created_at,
            })
    matches.sort(key=lambda item: (-item["score"], -item["id"]))
    return matches[:limit]


def promote_feedback_to_faq(feedback_id: int) -> int:
    with db_session() as db:
        pair = db.execute(
            select(Feedback, QueryLog)
            .join(QueryLog, QueryLog.id == Feedback.query_id)
            .where(Feedback.id == feedback_id)
        ).first()
        if not pair:
            raise ValueError("Retroalimentación no encontrada.")

        feedback, query = pair
        answer = (feedback.final_solution or feedback.comment or "").strip()
        if not answer:
            raise ValueError("La retroalimentación no contiene una solución útil.")

        existing = db.scalar(
            select(FAQ).where(FAQ.normalized_question == normalize(query.question))
        )
        if existing:
            existing.answer = answer
            existing.keywords = " ".join(tokenize(query.question))
            existing.document_name = query.document_name or existing.document_name
            existing.page_number = query.page_number or existing.page_number
            existing.active = True
            faq_id = existing.id
        else:
            faq = FAQ(
                question=query.question.strip(),
                normalized_question=normalize(query.question),
                answer=answer,
                keywords=" ".join(tokenize(query.question)),
                document_name=query.document_name or "",
                page_number=query.page_number,
                active=True,
            )
            db.add(faq)
            db.flush()
            faq_id = faq.id

        feedback.reviewed = True
        query.resolved = True
        db.commit()
        return faq_id


def quality_metrics() -> dict:
    with db_session() as db:
        total = db.scalar(select(func.count(QueryLog.id))) or 0
        resolved = db.scalar(
            select(func.count(QueryLog.id)).where(QueryLog.resolved == True)
        ) or 0
        low = db.scalar(
            select(func.count(QueryLog.id)).where(QueryLog.confidence == "Baja")
        ) or 0
        pending_feedback = db.scalar(
            select(func.count(Feedback.id)).where(Feedback.reviewed == False)
        ) or 0
        official_faqs = db.scalar(
            select(func.count(FAQ.id)).where(FAQ.active == True)
        ) or 0

    return {
        "total": total,
        "resolved": resolved,
        "resolution_rate": round((resolved / total * 100) if total else 0, 1),
        "low_confidence": low,
        "pending_feedback": pending_feedback,
        "official_faqs": official_faqs,
    }


def recurring_unresolved(limit: int = 20) -> list[dict]:
    with db_session() as db:
        rows = db.scalars(
            select(QueryLog)
            .where((QueryLog.resolved == False) | (QueryLog.confidence == "Baja"))
            .order_by(QueryLog.id.desc())
            .limit(3000)
        ).all()

    grouped: list[dict] = []
    for row in rows:
        for group in grouped:
            if question_similarity(row.question, group["sample"]) >= 0.56:
                group["count"] += 1
                group["questions"].append(row.question)
                group["latest"] = max(group["latest"], row.created_at)
                break
        else:
            grouped.append({
                "sample": row.question,
                "count": 1,
                "questions": [row.question],
                "latest": row.created_at,
                "intent": row.intent,
            })

    grouped.sort(key=lambda item: (-item["count"], item["latest"]), reverse=False)
    grouped = sorted(grouped, key=lambda item: (-item["count"], -item["latest"].timestamp()))
    return grouped[:limit]
