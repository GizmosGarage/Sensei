"""Choose the next learning step from evidence within a study guide."""

from datetime import datetime, timezone


def guide_progress(topics, contexts, *, now=None):
    """Survey unseen concepts, then teach gaps and revisit independent practice.

    No attempt means unknown, not weak. A completed lesson is followed by a
    practice check; reading a lesson alone never establishes mastery.
    """
    now = now or datetime.now(timezone.utc)
    concepts = []
    for topic in topics:
        signal = contexts[topic["id"]]
        recent = signal["recent_outcomes"]
        unknown = signal["attempts_count"] == 0
        gap = bool(signal["misconceptions"]) or signal.get("last_attempt_supported", False) or (bool(recent) and recent[-1] != "correct")
        concepts.append({
            "skill_id": topic["id"], "name": topic["name"],
            "status": "Not checked yet" if unknown else "Needs practice" if gap else signal["mastery_label"],
            "mistakes": signal["misconceptions"],
        })
    if not topics:
        return {"concepts": [], "next": None, "checked": 0}

    def priority(topic):
        signal = contexts[topic["id"]]
        if not signal["attempts_count"]:
            return (0, 0)
        recent = signal["recent_outcomes"]
        if signal["misconceptions"] or signal.get("last_attempt_supported", False) or (recent and recent[-1] != "correct"):
            return (1, signal["mastery_score"])
        if topic.get("next_review_at") and datetime.fromisoformat(topic["next_review_at"]) <= now:
            return (2, signal["mastery_score"])
        return (3, signal["mastery_score"])

    topic = min(topics, key=priority)
    signal = contexts[topic["id"]]
    category = priority(topic)[0]
    action = "practice"
    if category == 0:
        reason = "Try one short check so Sensei can learn what you already understand."
        label = "Start check-in"
    elif category == 1:
        action = "learn" if topic.get("lesson_status") != "complete" else "practice"
        reason = "Your recent answers or use of help suggest this needs another look. " + (
            "Work through an explanation, then try it yourself." if action == "learn"
            else "Check whether you can now apply the explanation independently."
        )
        label = "Work through this gap" if action == "learn" else "Check understanding"
    elif category == 2:
        reason = "This concept is due for a fresh check to see what has stuck."
        label = "Review understanding"
    else:
        reason = "Build more independent evidence in the concept with the least mastery so far."
        label = "Continue studying"
    return {"concepts": concepts,
            "checked": sum(contexts[t["id"]]["attempts_count"] > 0 for t in topics),
            "next": {"skill_id": topic["id"], "name": topic["name"],
                     "action": action, "label": label, "reason": reason}}
