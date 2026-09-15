"""
scripts/run_search.py
CLI entrypoint for the LinkedIn Prospecting pipeline.

Usage:
    python scripts/run_search.py "VP Sales at Series B SaaS, India"
    python scripts/run_search.py "CTO at fintech startups" --max 5 --output prospects.csv
"""
import argparse
import asyncio
import csv
import json
import sys
from pathlib import Path

# Allow running from repo root
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import get_settings
from app.services import discovery, enricher, qualifier, personalizer

settings = get_settings()


async def run(query: str, max_results: int, output: str | None):
    print(f"\n🔍 LinkedIn Prospector — CLI Mode")
    print(f"   Query     : {query}")
    print(f"   Max results: {max_results}")
    print(f"   Data mode : {'MOCK (no Proxycurl key)' if settings.mock_mode else 'PROXYCURL LIVE'}")
    print(f"   LLM mode  : {'GEMINI' if settings.llm_enabled else 'RULES-BASED (no Gemini key)'}")
    print("─" * 60)

    # Step 1: Discover
    print("\n[1/4] Discovering profiles...")
    raw_profiles = await discovery.discover_prospects(query=query, max_results=max_results)
    print(f"      → Found {len(raw_profiles)} profiles")

    results = []
    for i, raw in enumerate(raw_profiles):
        name_hint = raw.get("full_name") or raw.get("linkedin_url", f"profile-{i+1}")
        print(f"\n[2-4] Processing: {name_hint}")

        # Step 2: Enrich
        enriched = await enricher.enrich_profile(raw)
        print(f"      → Enriched: {enriched.get('current_title')} at {enriched.get('current_company')}")

        # Step 3: Qualify
        qual = await qualifier.qualify_prospect(enriched)
        label_emoji = {"strong": "🟢", "possible": "🟡", "weak": "🔴"}.get(qual["fit_label"], "⚪")
        print(f"      → Fit: {label_emoji} {qual['fit_label'].upper()} ({qual['fit_score']:.2f})")
        print(f"        {qual['fit_reasoning'][:100]}...")

        # Step 4: Personalise
        copy = await personalizer.generate_outreach(enriched)
        print(f"      → Connection note ({len(copy['connection_note'])} chars):")
        print(f"        \"{copy['connection_note'][:120]}...\"")

        results.append({**enriched, **qual, **copy})

    # Output
    if output:
        _write_csv(results, output)
        print(f"\n✅ Exported {len(results)} prospects to {output}")
    else:
        print(f"\n✅ Pipeline complete. {len(results)} prospects processed.")
        print("\n── Summary ──────────────────────────────────────────────────")
        for r in results:
            emoji = {"strong": "🟢", "possible": "🟡", "weak": "🔴"}.get(r.get("fit_label", ""), "⚪")
            print(f"  {emoji} {r.get('full_name'):30s} | {r.get('fit_label'):8s} | {r.get('fit_score', 0):.2f} | {r.get('current_title', '')[:35]}")


def _write_csv(results: list[dict], path: str):
    fieldnames = [
        "full_name", "linkedin_url", "current_title", "current_company",
        "location", "industry", "fit_score", "fit_label", "fit_reasoning",
        "recent_post_snippet", "role_change_detected", "tenure_months",
        "connection_note", "followup_dm",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)


def main():
    parser = argparse.ArgumentParser(
        description="LinkedIn Prospecting CLI — discover, enrich, qualify and personalise.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/run_search.py "VP Sales at Series B SaaS, India"
  python scripts/run_search.py "CTO at fintech startups" --max 5
  python scripts/run_search.py "Head of Growth" --output prospects.csv
        """,
    )
    parser.add_argument("query", help="Natural language search query")
    parser.add_argument("--max", type=int, default=10, dest="max_results", help="Max results (default: 10)")
    parser.add_argument("--output", type=str, default=None, help="Output CSV file path")
    args = parser.parse_args()

    asyncio.run(run(args.query, args.max_results, args.output))


if __name__ == "__main__":
    main()
