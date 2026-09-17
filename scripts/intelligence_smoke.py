#!/usr/bin/env python3
"""Safe smoke harness for the Universal Brain Intelligence Fabric.

The script performs no network/model invocation unless --allow-live-invocation is
explicitly supplied. Catalog credentials remain environment-variable references.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from universal_brain.executive.budget import BudgetGatekeeper
from universal_brain.intelligence import (  # noqa: E402
    ModelCapability,
    ModelMessage,
    ModelRequest,
    SensitivityLevel,
    TaskProfile,
    build_intelligence_stack,
    load_catalog,
)


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Intelligence Fabric smoke harness")
    p.add_argument("--catalog", default="config/intelligence_catalog.example.json")
    p.add_argument("--route", help="Require a specific eligible route id")
    p.add_argument(
        "--allow-live-invocation",
        action="store_true",
        help="Actually contact/use the selected configured model route",
    )
    p.add_argument(
        "--prompt",
        default="Return exactly UB_SMOKE_OK and nothing else.",
        help="A0 smoke prompt; do not put secrets here",
    )
    return p


async def main_async(args: argparse.Namespace) -> int:
    catalog_path = (ROOT / args.catalog).resolve() if not Path(args.catalog).is_absolute() else Path(args.catalog)
    catalog = load_catalog(catalog_path)
    state_root = ROOT / ".universal_brain" / "intelligence"
    stack = build_intelligence_stack(
        catalog,
        budget=BudgetGatekeeper(monthly_budget_usd=20),
        telemetry_path=state_root / "telemetry.json",
        performance_path=state_root / "performance.json",
        conversation_registry_path=state_root / "conversations.json",
    )
    task = TaskProfile(
        task_kind="smoke",
        required_capabilities={ModelCapability.REASONING},
        sensitivity=SensitivityLevel.PUBLIC,
    )
    try:
        decision = stack.router.select(task)
    except Exception as exc:
        print(json.dumps({"status": "no_eligible_route", "error": str(exc)}, indent=2))
        return 2

    candidates = [decision.selected_score, *decision.alternatives]
    selected = decision.selected_score
    if args.route:
        matches = [candidate for candidate in candidates if candidate.route_id == args.route]
        if not matches:
            print(
                json.dumps(
                    {
                        "status": "requested_route_not_eligible",
                        "route": args.route,
                        "eligible_routes": [candidate.route_id for candidate in candidates],
                    },
                    indent=2,
                )
            )
            return 2
        selected = matches[0]

    preview = {
        "status": "dry_run" if not args.allow_live_invocation else "ready_to_invoke",
        "model_key": selected.model_key,
        "route_id": selected.route_id,
        "transport": catalog.require_route(selected.route_id).transport.value,
        "score": selected.total_score,
        "live_invocation_authorized": bool(args.allow_live_invocation),
    }
    if not args.allow_live_invocation:
        print(json.dumps(preview, indent=2))
        return 0

    request = ModelRequest(
        messages=[ModelMessage(role="user", content=args.prompt)],
        metadata={"task_kind": "smoke", "sensitivity": "public", "action_class": "A0"},
        max_output_tokens=64,
    )
    route_decision = stack.fabric._decision_for_candidate(decision, selected)
    try:
        result = await stack.fabric.invoke_decision(route_decision, request, task)
    finally:
        await stack.supervisor.close_all()
    print(
        json.dumps(
            {
                **preview,
                "status": "success",
                "output": result.output_text[:500],
                "usage": result.usage.model_dump(mode="json"),
                "evidence_keys": sorted(result.evidence),
            },
            indent=2,
        )
    )
    return 0


def main() -> int:
    return asyncio.run(main_async(parser().parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
