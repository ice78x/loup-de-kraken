"""Catalyseurs : relie les news vérifiées à un actif et en déduit un apport au score (jamais un déclencheur seul)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..news.engine import NewsItem


@dataclass
class CatalystContext:
    base: str
    used: list[NewsItem] = field(default_factory=list)        # vérifiées, prises en compte
    ignored: list[NewsItem] = field(default_factory=list)     # non vérifiées / rumeurs : affichées, pas utilisées
    points: dict[str, float] = field(default_factory=lambda: {"LONG": 0.0, "SHORT": 0.0})
    blocks: dict[str, str] = field(default_factory=dict)      # direction -> raison bloquante
    warnings: list[str] = field(default_factory=list)

    @property
    def main(self) -> NewsItem | None:
        return self.used[0] if self.used else None

    @property
    def has_major(self) -> bool:
        return any(n.impact >= 3 for n in self.used)

    def label(self) -> str:
        n = self.main
        if not n:
            return "Aucun catalyseur vérifié — setup purement technique"
        return f"{', '.join(n.categories) or 'News'} — {n.title}"


def _recency_weight(age_h: float) -> float:
    return 1.0 if age_h <= 2 else 0.7 if age_h <= 6 else 0.4 if age_h <= 24 else 0.0


def catalyst_for(base: str, asset_class: str, news: list[NewsItem], now: datetime | None = None) -> CatalystContext:
    now = now or datetime.now(timezone.utc)
    ctx = CatalystContext(base)
    rel: list[tuple[NewsItem, float]] = []
    for n in news:
        specific = base in n.assets
        macro = n.macro and n.impact >= 2 and (asset_class != "commodity" or "Géopolitique" in n.categories
                                                or "Taux" in n.categories or "Fed" in n.categories)
        if not (specific or macro):
            continue
        if not n.verified or n.is_rumor:
            ctx.ignored.append(n)
            continue
        age_h = max(0.0, (now - n.published_at).total_seconds() / 3600)
        w = (1.0 if specific else 0.6) * (1.0 if n.scope == "calendar" else _recency_weight(age_h))
        if w <= 0:
            continue
        rel.append((n, w))
        if specific and "Delisting" in n.categories:
            ctx.blocks["LONG"] = f"delisting annoncé ({n.source})"
        if specific and n.scope == "calendar":
            ctx.warnings.append(f"résultats d'entreprise imminents ({n.title}) — risque d'écart de prix")
    rel.sort(key=lambda x: (x[0].impact * x[1], x[0].published_at), reverse=True)
    ctx.used = [n for n, _ in rel]
    for n, w in rel:
        if n.scope == "calendar":
            continue
        base_pts = n.impact * 3.0 * w
        if n.direction_hint == "haussier":
            ctx.points["LONG"] += base_pts
            ctx.points["SHORT"] -= base_pts
        elif n.direction_hint == "baissier":
            ctx.points["SHORT"] += base_pts
            ctx.points["LONG"] -= base_pts
        else:
            ctx.points["LONG"] += base_pts * 0.35
            ctx.points["SHORT"] += base_pts * 0.35
    for d in ctx.points:
        ctx.points[d] = max(-15.0, min(20.0, round(ctx.points[d], 2)))
    return ctx
