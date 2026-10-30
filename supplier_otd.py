"""Explainable supplier on-time delivery scorecard; standard library only."""
from __future__ import annotations

import argparse
import csv
import json
import random
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

REQUIRED = ("order_id", "supplier", "ordered_at", "promised_at", "delivered_at")


def _date(value: str, row: int, field: str) -> date:
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        raise ValueError(f"Ligne {row}: {field} doit être une date ISO AAAA-MM-JJ") from None


def load_orders(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or any(name not in reader.fieldnames for name in REQUIRED):
            raise ValueError("Colonnes requises: " + ", ".join(REQUIRED))
        rows, seen = [], set()
        for line, raw in enumerate(reader, 2):
            order_id, supplier = (raw.get("order_id") or "").strip(), (raw.get("supplier") or "").strip()
            if not order_id or not supplier:
                raise ValueError(f"Ligne {line}: order_id et supplier sont obligatoires")
            if order_id in seen:
                raise ValueError(f"Ligne {line}: commande dupliquée {order_id}")
            seen.add(order_id)
            ordered, promised = _date(raw.get("ordered_at", ""), line, "ordered_at"), _date(raw.get("promised_at", ""), line, "promised_at")
            if promised < ordered:
                raise ValueError(f"Ligne {line}: promised_at précède ordered_at")
            delivered_text = (raw.get("delivered_at") or "").strip()
            delivered = _date(delivered_text, line, "delivered_at") if delivered_text else None
            if delivered and delivered < ordered:
                raise ValueError(f"Ligne {line}: delivered_at précède ordered_at")
            rows.append({"order_id": order_id, "supplier": supplier, "ordered_at": ordered,
                         "promised_at": promised, "delivered_at": delivered})
    return rows


def percentile(values: list[int], q: float) -> int | None:
    """Nearest-rank percentile (1-indexed), returning None for an empty set."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, min(len(ordered) - 1, int((q * len(ordered) + .999999999) - 1)))]


def score(rows: list[dict], min_deliveries: int = 20, watch_gap: float = .10) -> dict:
    if min_deliveries < 1 or not 0 <= watch_gap <= 1:
        raise ValueError("min_deliveries doit être positif et watch_gap entre 0 et 1")
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        groups[row["supplier"]].append(row)
    completed = [r for r in rows if r["delivered_at"] is not None]
    overall_rate = (sum(r["delivered_at"] <= r["promised_at"] for r in completed) / len(completed)) if completed else None
    suppliers = []
    for name, orders in sorted(groups.items()):
        done = [r for r in orders if r["delivered_at"] is not None]
        delays = [(r["delivered_at"] - r["promised_at"]).days for r in done]
        rate = (sum(d <= 0 for d in delays) / len(done)) if done else None
        suppliers.append({"supplier": name, "orders": len(orders), "delivered": len(done),
            "open": len(orders) - len(done), "on_time_rate": rate,
            "mean_delay_days": (sum(delays) / len(delays)) if delays else None,
            "median_delay_days": percentile(delays, .5), "p90_delay_days": percentile(delays, .9),
            "status": ("insufficient" if len(done) < min_deliveries else
                       "watch" if overall_rate is not None and rate is not None and rate < overall_rate - watch_gap else "ok")})
    return {"orders": len(rows), "delivered": len(completed), "open": len(rows) - len(completed),
            "overall_on_time_rate": overall_rate, "min_deliveries": min_deliveries,
            "watch_gap_percentage_points": watch_gap * 100, "suppliers": suppliers}


def write_report(result: dict, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    (output / "scorecard.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    with (output / "supplier_metrics.csv").open("w", encoding="utf-8", newline="") as stream:
        fields = list(result["suppliers"][0]) if result["suppliers"] else ["supplier", "orders", "delivered", "open", "on_time_rate", "mean_delay_days", "median_delay_days", "p90_delay_days", "status"]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(result["suppliers"])
    lines = ["# Supplier OTD scorecard", "", f"- Commandes: **{result['orders']}** ({result['delivered']} livrées, {result['open']} ouvertes exclues du taux).",
             f"- Taux global à l'heure: **{_pct(result['overall_on_time_rate'])}**.",
             f"- Surveillance: au moins {result['min_deliveries']} livraisons et taux inférieur de plus de {result['watch_gap_percentage_points']:.0f} points au global.", "",
             "| Fournisseur | Livrées | À l'heure | Retard médian (j) | P90 retard (j) | Statut |", "|---|---:|---:|---:|---:|---|"]
    for s in result["suppliers"]:
        lines.append(f"| {s['supplier']} | {s['delivered']} | {_pct(s['on_time_rate'])} | {_val(s['median_delay_days'])} | {_val(s['p90_delay_days'])} | {s['status']} |")
    (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _pct(value): return "n/a" if value is None else f"{value:.1%}"
def _val(value): return "n/a" if value is None else str(value)


def generate(path: Path, seed: int = 20261030) -> None:
    rng = random.Random(seed)
    delays = {"Alpine Parts": (0.91, 1), "Cobalt Components": (.76, 3), "Delta Packaging": (.95, 0),
              "Eastern Freight": (.68, 5), "Fjord Materials": (.86, 2), "Greenline Supply": (.98, -1)}
    start = date(2026, 1, 1)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream); writer.writerow(REQUIRED)
        index = 0
        for supplier, (on_time_chance, extra) in delays.items():
            for i in range(55):
                ordered = start + timedelta(days=i * 5 + rng.randrange(4))
                promised = ordered + timedelta(days=7 + rng.randrange(4))
                delivered = promised + (timedelta(days=0 if rng.random() < on_time_chance else rng.randint(1, 5) + extra))
                if i >= 51 and rng.random() < .35:
                    delivered_text = ""
                else:
                    delivered_text = delivered.isoformat()
                index += 1
                writer.writerow([f"PO-{index:04d}", supplier, ordered.isoformat(), promised.isoformat(), delivered_text])


def main() -> None:
    parser = argparse.ArgumentParser(description="Scorecard OTD auditable par fournisseur")
    sub = parser.add_subparsers(dest="command", required=True)
    demo = sub.add_parser("demo", help="génère des PO fictifs et un rapport reproductibles")
    demo.add_argument("--output", type=Path, default=Path("demo-output"))
    run = sub.add_parser("score", help="analyse un CSV de commandes fournisseur")
    run.add_argument("csv", type=Path); run.add_argument("--output", type=Path, default=Path("report"))
    run.add_argument("--min-deliveries", type=int, default=20); run.add_argument("--watch-gap", type=float, default=.10, help="écart minimal au taux global, entre 0 et 1")
    args = parser.parse_args()
    if args.command == "demo":
        args.output.mkdir(parents=True, exist_ok=True)
        data = args.output / "purchase_orders.csv"; generate(data)
        result = score(load_orders(data)); write_report(result, args.output)
        print(f"{result['orders']} commandes; {result['delivered']} livrées; taux global {_pct(result['overall_on_time_rate'])}; rapport: {args.output / 'report.md'}")
    else:
        result = score(load_orders(args.csv), args.min_deliveries, args.watch_gap)
        write_report(result, args.output)
        print(f"{result['orders']} commandes; {result['delivered']} livrées; taux global {_pct(result['overall_on_time_rate'])}; rapport: {args.output / 'report.md'}")


if __name__ == "__main__": main()
