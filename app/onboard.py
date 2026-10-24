"""Onboarding orchestration for RevenueLens."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.llm import LLM


def onboard(
    dsn: str,
    schema: str,
    llm: LLM | None = None,
) -> dict:
    """Run complete onboarding pipeline."""
    from app.adapters.postgres_readonly import ReadOnlyAdapter
    from app.discovery import discover
    from app.learning import conflicts, learn_catalog
    from app.mapping import map_schema
    from app.replay import replay_bills

    with ReadOnlyAdapter(dsn, schema) as adapter:
        profile = discover(adapter)
        mapping = map_schema(profile, llm)
        catalog = learn_catalog(adapter, mapping)
        conflict_list = conflicts(catalog)
        replay_result = replay_bills(adapter, mapping, catalog)

        return {
            "schema": schema,
            "tables": len(profile.tables),
            "joins": len(profile.joins),
            "mapping": mapping.to_dict(),
            "rules": len(catalog.rules),
            "conflicts": conflict_list,
            "replay": {
                "match_rate": replay_result.match_rate,
                "matched": replay_result.matched,
                "total": replay_result.total,
                "mismatches": replay_result.to_dict()["mismatches"][:20],
            },
        }


def main(argv: list[str] | None = None) -> int:
    """Main entry point for onboarding CLI."""
    parser = argparse.ArgumentParser(description="RevenueLens onboarding")
    parser.add_argument(
        "--dsn",
        default=os.environ.get("LEGACY_DATABASE_URL") or os.environ.get("DATABASE_URL"),
        help="PostgreSQL DSN",
    )
    parser.add_argument(
        "--schema",
        default="nimbus",
        help="Database schema",
    )
    parser.add_argument(
        "--out",
        help="Output JSON file path",
    )
    args = parser.parse_args(argv)

    if not args.dsn:
        print("Error: DSN required (--dsn or LEGACY_DATABASE_URL/DATABASE_URL env)", file=sys.stderr)
        return 1

    from app.llm import free_llm_from_env
    from app.llm_cache import CachedLLM

    llm = CachedLLM(free_llm_from_env())
    result = onboard(args.dsn, args.schema, llm)

    if args.out:
        with open(args.out, "w") as f:
            json.dump(result, f, indent=2)
    else:
        print(json.dumps(result, indent=2))

    print(
        f"Schema: {result['schema']}, Tables: {result['tables']}, Joins: {result['joins']}",
        file=sys.stderr,
    )
    print(
        f"Rules: {result['rules']}, Conflicts: {len(result['conflicts'])}, "
        f"Replay match: {result['replay']['match_rate']:.2%} ({result['replay']['matched']}/{result['replay']['total']})",
        file=sys.stderr,
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
