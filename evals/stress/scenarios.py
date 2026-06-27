"""Generate multi-turn stress conversations with per-turn fact trackers.

Three profiles, each designed to force a specific session behaviour:

- **grow** — requirements accumulate turn-by-turn; measures cost curve and
  whether ``project_name`` survives to turn 20.
- **pivot** — turn 5 replaces the frontend stack; measures whether metadata
  updates cleanly or ``mentioned_technologies`` accumulates both stacks.
- **contradict** — turn 3 caps budget at 30 k€, turn 8 locks it at 80 k€;
  measures which value wins in metadata, which becomes an anchor, and which
  lands in the cumulative summary.

Each profile is a list of ``(turn_index, transcript, fact_to_remember)``.
After turn *N*, subsequent calls should recall every ``fact_to_remember`` from
turns 1…*N* (cumulative fact-tracker).

Usage::

    uv run python -m evals.stress.scenarios --list
    uv run python -m evals.stress.scenarios --profile grow --turns 10
    uv run python -m evals.stress.scenarios --export /tmp/stress_scenarios.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


TURN_COUNTS: tuple[int, ...] = (1, 3, 6, 10, 20)

# (turn_index, transcript, fact_to_remember)
ProfileScript = list[tuple[int, str, str]]


class TurnSpec(BaseModel):
    turn: int = Field(ge=1)
    transcript: str = Field(min_length=20, max_length=80_000)
    fact_to_remember: str = Field(min_length=3, max_length=200)


class FactTrackerRow(BaseModel):
    after_turn: int = Field(ge=1)
    must_remember: list[str]


class ProfileMeasurements(BaseModel):
    track_cost_curve: bool = False
    track_project_name_at_turn_20: str | None = None
    track_technology_accumulation: bool = False
    track_budget_conflict: bool = False
    pivot_turn: int | None = None
    contradiction_turns: tuple[int, int] | None = None


class StressProfile(BaseModel):
    id: str
    name: str
    description: str
    project_type: Literal["mobile_app", "web_saas", "internal_tool", "data_pipeline"]
    detail_level: Literal["summary", "medium", "detailed"] = "medium"
    output_format: Literal["phases_table", "line_items", "narrative"] = "phases_table"
    script: list[TurnSpec]
    fact_tracker: list[FactTrackerRow]
    measurements: ProfileMeasurements


class StressScenario(BaseModel):
    scenario_id: str
    profile_id: str
    profile_name: str
    turn_count: int
    project_type: str
    detail_level: str
    output_format: str
    turns: list[TurnSpec]
    fact_tracker: list[FactTrackerRow]
    measurements: ProfileMeasurements


# ---------------------------------------------------------------------------
# Profile scripts — source of truth
# ---------------------------------------------------------------------------

GROW_SCRIPT: ProfileScript = [
    (
        1,
        "We want a B2B CRM called Nimbus for the sales team. Core scope: contacts, "
        "deal pipeline, basic reporting. Stack: React + Postgres. Team of 3 developers.",
        "project name: Nimbus",
    ),
    (
        2,
        "Add OAuth2 authentication with Google Workspace SSO. Every user must belong "
        "to exactly one organisation account.",
        "feature: OAuth2 SSO",
    ),
    (
        3,
        "Nimbus must be multi-tenant: each customer organisation gets isolated data "
        "with row-level security in Postgres.",
        "feature: multi-tenant",
    ),
    (
        4,
        "We need a full audit log — every create, update and delete on contacts and "
        "deals must be recorded with actor, timestamp and diff.",
        "feature: audit log",
    ),
    (
        5,
        "Sales managers want CSV export for contacts and open deals, filterable by "
        "pipeline stage and owner.",
        "feature: CSV export",
    ),
    (
        6,
        "Introduce role-based access control: admin, sales rep and read-only viewer. "
        "Admins manage users; reps edit their own deals only.",
        "feature: RBAC",
    ),
    (
        7,
        "Wire transactional email through SendGrid: deal stage changes and weekly "
        "pipeline digests.",
        "stack includes: SendGrid",
    ),
    (
        8,
        "Read-only Salesforce sync: pull accounts and contacts nightly, never push "
        "changes back.",
        "integration: Salesforce read-only",
    ),
    (
        9,
        "Executive dashboard with KPI widgets: pipeline value, win rate, average "
        "deal cycle length.",
        "feature: executive dashboard",
    ),
    (
        10,
        "GDPR data-retention policies: auto-purge inactive contacts after 24 months "
        "with an admin override queue.",
        "compliance: GDPR retention",
    ),
    (
        11,
        "Public webhook API so customers can subscribe to deal-won and contact-created "
        "events.",
        "feature: webhooks",
    ),
    (
        12,
        "Bulk import from Excel/CSV with column mapping and duplicate detection on "
        "email address.",
        "feature: bulk import",
    ),
    (
        13,
        "Custom fields on contacts — text, number and pick-list — configurable per "
        "tenant without code changes.",
        "feature: custom fields",
    ),
    (
        14,
        "Pipeline automation rules: when a deal hits 'Proposal sent', create a follow-up "
        "task due in 3 days.",
        "feature: pipeline automation",
    ),
    (
        15,
        "Ship a mobile-responsive PWA so reps can update deals from the field.",
        "feature: mobile PWA",
    ),
    (
        16,
        "Rate-limit the REST API at 100 requests/minute per API key.",
        "feature: API rate limiting",
    ),
    (
        17,
        "Mandatory two-factor authentication for admin and sales-rep roles.",
        "feature: 2FA",
    ),
    (
        18,
        "Scheduled PDF reports every Monday: pipeline snapshot emailed to each "
        "tenant's admins.",
        "feature: scheduled PDF reports",
    ),
    (
        19,
        "Provide a sandbox tenant for customer training — seeded with fake data, "
        "reset weekly.",
        "feature: sandbox tenant",
    ),
    (
        20,
        "Performance SLA: p95 API latency under 200 ms for the core read endpoints "
        "under normal load.",
        "SLA: p95 under 200ms",
    ),
]

PIVOT_SCRIPT: ProfileScript = [
    (
        1,
        "Inventory management web app called StockFlow. React frontend, Node.js API, "
        "Postgres. Barcode scanning via browser camera, stock levels, low-stock alerts.",
        "project name: StockFlow",
    ),
    (
        2,
        "Add supplier catalogue import from CSV and a purchase-order workflow with "
        "approval steps.",
        "feature: purchase orders",
    ),
    (
        3,
        "Warehouse staff need a picking list view optimised for tablets — large touch "
        "targets, offline queue for scan events.",
        "feature: picking lists",
    ),
    (
        4,
        "Integrate with their existing Shopify store: sync SKU quantities every 15 "
        "minutes.",
        "integration: Shopify",
    ),
    (
        5,
        "Major pivot: the client cancelled the React web app. Re-scope StockFlow as a "
        "Flutter mobile app for iOS and Android — warehouse staff will use rugged "
        "handheld scanners instead of browsers. Drop the React SPA; Flutter is the "
        "only frontend going forward.",
        "stack is Flutter only (React dropped)",
    ),
    (
        6,
        "Flutter app must support Zebra Bluetooth scanners and batch pick lists "
        "assigned per operator.",
        "stack includes: Zebra scanners",
    ),
    (
        7,
        "Offline-first: scans queue locally and sync when connectivity returns; "
        "conflict resolution favours server timestamp.",
        "feature: offline-first sync",
    ),
    (
        8,
        "Push notifications when a pick list is assigned or a SKU hits reorder point.",
        "feature: push notifications",
    ),
    (
        9,
        "Admin web console stays on Node + Postgres but is read-only analytics — no "
        "React, just a minimal internal dashboard they already have.",
        "backend: Node + Postgres analytics only",
    ),
    (
        10,
        "Biometric login (Face ID / fingerprint) for warehouse operators on shared "
        "devices.",
        "feature: biometric login",
    ),
    (
        11,
        "Photo capture on receipt discrepancies — attach images to adjustment records.",
        "feature: photo capture",
    ),
    (
        12,
        "Multi-warehouse support: operators select active warehouse at login.",
        "feature: multi-warehouse",
    ),
    (
        13,
        "Cycle-count module: blind counts with variance reporting.",
        "feature: cycle counts",
    ),
    (
        14,
        "Export stock snapshot to CSV for finance every night.",
        "feature: nightly CSV export",
    ),
    (
        15,
        "Dark-mode UI for night shifts.",
        "feature: dark mode",
    ),
    (
        16,
        "Localization: Spanish and English UI strings.",
        "feature: ES/EN localization",
    ),
    (
        17,
        "Performance target: scan-to-confirmation under 500 ms on mid-range Android.",
        "SLA: scan under 500ms",
    ),
    (
        18,
        "Role split: picker, supervisor, read-only auditor.",
        "feature: role split",
    ),
    (
        19,
        "Supervisor can reassign pick lists and override quantity adjustments with "
        "a reason code.",
        "feature: supervisor overrides",
    ),
    (
        20,
        "Go-live hard deadline: Flutter app in production stores before Black Friday.",
        "deadline: Black Friday",
    ),
]

CONTRADICT_SCRIPT: ProfileScript = [
    (
        1,
        "Internal HR onboarding portal called PeopleBridge. Okta SSO, checklist per "
        "role, document upload. Team of 2 developers.",
        "project name: PeopleBridge",
    ),
    (
        2,
        "Add DocuSign integration for offer letters and policy acknowledgements.",
        "integration: DocuSign",
    ),
    (
        3,
        "Finance capped phase 1 at 30,000 EUR — keep the estimate within that budget "
        "for the MVP (SSO, checklist, uploads, DocuSign).",
        "budget cap: 30000 EUR",
    ),
    (
        4,
        "Managers need a dashboard showing onboarding progress per new hire.",
        "feature: manager dashboard",
    ),
    (
        5,
        "Employee self-service: update emergency contacts and bank details.",
        "feature: employee self-service",
    ),
    (
        6,
        "IT provisioning hooks: create Google Workspace and Slack accounts when HR "
        "marks someone as hired.",
        "integration: Google Workspace + Slack",
    ),
    (
        7,
        "Compliance training module with quiz completion tracking.",
        "feature: compliance training",
    ),
    (
        8,
        "Update: finance approved 80,000 EUR total — budget is locked at 80k for the "
        "full project including dashboard, provisioning and training.",
        "budget locked: 80000 EUR",
    ),
    (
        9,
        "Bulk import of new hires from their BambooHR export.",
        "integration: BambooHR import",
    ),
    (
        10,
        "Automated reminders for managers when tasks are overdue.",
        "feature: overdue reminders",
    ),
    (
        11,
        "Audit trail for every change to employee records — who, when, what.",
        "feature: audit trail",
    ),
    (
        12,
        "Mobile-friendly responsive UI for new hires on phones.",
        "feature: mobile responsive UI",
    ),
    (
        13,
        "Sandbox environment with anonymised sample employees for demos.",
        "feature: sandbox",
    ),
    (
        14,
        "Reporting pack: time-to-productivity metrics per department.",
        "feature: productivity reporting",
    ),
    (
        15,
        "Integration with their ServiceNow ticket queue for hardware requests.",
        "integration: ServiceNow",
    ),
    (
        16,
        "Multi-language support: English and French employee-facing screens.",
        "feature: EN/FR localization",
    ),
    (
        17,
        "Accessibility: WCAG 2.1 AA on all employee-facing flows.",
        "compliance: WCAG 2.1 AA",
    ),
    (
        18,
        "Archive completed onboarding folders after 7 years per HR policy.",
        "policy: 7-year retention",
    ),
    (
        19,
        "Supervisor override to reopen a completed checklist with justification.",
        "feature: supervisor override",
    ),
    (
        20,
        "Go-live target: all EU offices on PeopleBridge before Q3.",
        "deadline: Q3 EU go-live",
    ),
]


def _build_fact_tracker(script: ProfileScript) -> list[FactTrackerRow]:
    rows: list[FactTrackerRow] = []
    accumulated: list[str] = []
    for turn_idx, _transcript, fact in script:
        if turn_idx != len(accumulated) + 1:
            msg = f"turn_index {turn_idx} out of sequence in profile script"
            raise ValueError(msg)
        accumulated.append(fact)
        rows.append(FactTrackerRow(after_turn=turn_idx, must_remember=list(accumulated)))
    return rows


def _profile_from_script(
    *,
    id: str,
    name: str,
    description: str,
    project_type: Literal["mobile_app", "web_saas", "internal_tool", "data_pipeline"],
    script: ProfileScript,
    measurements: ProfileMeasurements,
) -> StressProfile:
    turns = [
        TurnSpec(turn=turn_idx, transcript=transcript, fact_to_remember=fact)
        for turn_idx, transcript, fact in script
    ]
    return StressProfile(
        id=id,
        name=name,
        description=description,
        project_type=project_type,
        script=turns,
        fact_tracker=_build_fact_tracker(script),
        measurements=measurements,
    )


GROW_PROFILE = _profile_from_script(
    id="grow",
    name="Proyecto que crece",
    description=(
        "Turn-by-turn addition of coherent CRM requirements. Measures the cost "
        "curve across turns and whether the original project name (Nimbus) survives "
        "compression at turn 20."
    ),
    project_type="web_saas",
    script=GROW_SCRIPT,
    measurements=ProfileMeasurements(
        track_cost_curve=True,
        track_project_name_at_turn_20="Nimbus",
    ),
)

PIVOT_PROFILE = _profile_from_script(
    id="pivot",
    name="Proyecto que pivota",
    description=(
        "Turn 5 replaces React with Flutter. Measures whether metadata reflects the "
        "new stack or mentioned_technologies keeps both frontend frameworks."
    ),
    project_type="mobile_app",
    script=PIVOT_SCRIPT,
    measurements=ProfileMeasurements(
        track_technology_accumulation=True,
        pivot_turn=5,
    ),
)

CONTRADICT_PROFILE = _profile_from_script(
    id="contradict",
    name="Proyecto que se contradice",
    description=(
        "Turn 3 caps budget at 30 k€; turn 8 locks it at 80 k€. Measures which "
        "value wins in metadata, which becomes an anchor, and which survives only "
        "in the cumulative summary."
    ),
    project_type="internal_tool",
    script=CONTRADICT_SCRIPT,
    measurements=ProfileMeasurements(
        track_budget_conflict=True,
        contradiction_turns=(3, 8),
    ),
)

STRESS_PROFILES: dict[str, StressProfile] = {
    p.id: p for p in (GROW_PROFILE, PIVOT_PROFILE, CONTRADICT_PROFILE)
}


def generate_scenario(profile: StressProfile, turn_count: int) -> StressScenario:
    if turn_count not in TURN_COUNTS:
        msg = f"turn_count must be one of {TURN_COUNTS}, got {turn_count}"
        raise ValueError(msg)
    if turn_count > len(profile.script):
        msg = f"profile {profile.id} has only {len(profile.script)} turns"
        raise ValueError(msg)

    return StressScenario(
        scenario_id=f"{profile.id}-t{turn_count:02d}",
        profile_id=profile.id,
        profile_name=profile.name,
        turn_count=turn_count,
        project_type=profile.project_type,
        detail_level=profile.detail_level,
        output_format=profile.output_format,
        turns=profile.script[:turn_count],
        fact_tracker=[row for row in profile.fact_tracker if row.after_turn <= turn_count],
        measurements=profile.measurements,
    )


def generate_all_scenarios() -> list[StressScenario]:
    return [
        generate_scenario(profile, n)
        for profile in STRESS_PROFILES.values()
        for n in TURN_COUNTS
    ]


def load_scenario(profile_id: str, turn_count: int) -> StressScenario:
    try:
        profile = STRESS_PROFILES[profile_id]
    except KeyError as exc:
        known = ", ".join(sorted(STRESS_PROFILES))
        raise KeyError(f"Unknown profile {profile_id!r}; choose from: {known}") from exc
    return generate_scenario(profile, turn_count)


def _print_list() -> None:
    for profile in STRESS_PROFILES.values():
        print(f"\n{profile.id}: {profile.name}")
        print(f"  {profile.description}")
        print(f"  turns: {len(profile.script)}  |  slices: {list(TURN_COUNTS)}")
        print(f"  measurements: {profile.measurements.model_dump()}")
        last = profile.fact_tracker[-1]
        print(f"  facts at turn 20: {len(last.must_remember)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="Summarise profiles and exit.")
    parser.add_argument("--profile", choices=sorted(STRESS_PROFILES), default=None)
    parser.add_argument("--turns", type=int, choices=TURN_COUNTS, default=None)
    parser.add_argument(
        "--export",
        type=Path,
        default=None,
        help="Write all profile × turn-count scenarios to JSON.",
    )
    args = parser.parse_args()

    if args.list:
        _print_list()
        return 0

    if args.export:
        payload = [s.model_dump(mode="json") for s in generate_all_scenarios()]
        args.export.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Exported {len(payload)} scenarios to {args.export}")
        return 0

    if args.profile and args.turns:
        scenario = load_scenario(args.profile, args.turns)
        print(scenario.model_dump_json(indent=2))
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
