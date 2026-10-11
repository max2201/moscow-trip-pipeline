"""A ranking for every offer, with explicit evidence and uncertainty."""
import math


def rating_components(score, count, analysis, risks, median=8):
    n = analysis["n"]
    valid_score = isinstance(score, (int, float)) and math.isfinite(score) and 0 < score <= 10
    basis = "texts" if n else "platform" if valid_score else "none"
    count = max(0, int(count or 0))
    # An unrated property gets a reserved sorting value, not a claim about quality.
    # Reading a small visible sample does not erase the evidence in the
    # published aggregate. Text counts govern complaint rates, not its weight.
    weight = min(max(count, n), 1000) or 5
    base = round((weight * score + 25 * median) / (weight + 25), 2) if valid_score else 6.0
    c = analysis["c"]
    penalty = negative = trend = 0
    if n:
        per = lambda x: x / (n + 50) * 100
        penalty = min(2, .30 * per(c["roach"]) + .10 * per(c["ants"]) + .12 * per(c["smell"]) + .20 * per(c["damp"]))
        # Money, booking and hygiene warnings also affect the ranking.
        severe = sum(risks.get(k, 0) for k in ("theft", "scam", "deposit", "booking", "rodents"))
        hygiene = sum(risks.get(k, 0) for k in ("linen", "hotwater", "notrec"))
        penalty = min(3, penalty + min(1.5, severe * .3 + hygiene / (n + 25) * 4))
        share = analysis["neg"] / n * 100
        negative = max(-.5, min(.15, -(share - 5) * .03)) if n >= 60 else max(-.5, min(0, -(share - 5) * .03))
        if valid_score and n >= 120 and analysis["recent"]:
            trend = max(-.3, min(.2, (analysis["recent"] - score) * .5))
        uncertainty = -.3 if n < 15 else 0
    elif basis == "platform":
        uncertainty = -.15 - (.3 if count < 15 else 0)
    else:
        uncertainty = 0
    confidence = "high" if n >= 30 else "medium" if n >= 5 or (basis == "platform" and count >= 100) else "low" if basis != "none" else "none"
    return [base, round(-penalty, 2), round(negative, 2), round(trend, 2), uncertainty], {
        "basis": basis, "confidence": confidence, "textCount": n, "reviewCount": count,
        "prior": median if valid_score else 6.0,
    }
