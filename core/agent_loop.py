"""
agent_loop.py — M4 Bounded Agent/Tool Loop

Governing spine: ibm_watsonx_cohesive_trajectory_gameplan.md M4
Milestone: M4 bounded agent/tool loop
Concept: Bound autonomy (max iterations, tool allowlist, timeout) so a
         reasoning loop cannot become an uncontrolled execution loop.
         Wraps M1's provider boundary (watsonx_ping's bounded manifest tool)
         and M3's retrieval pipeline (RagStore) into a single
         Observe -> Reason -> Act -> Observe cycle.

Evidence: A structured trajectory log showing explicit termination state
          (success | max_iterations | timeout | disallowed_action), with
          at least one deterministic test proving the loop actually stops
          at max_iterations rather than running unbounded, and one proving
          a disallowed action fails closed rather than being silently
          executed.

Bounded tools (the ONLY actions the model may choose):
    - read_kitty_hawk_manifest  (from M1 — no arguments)
    - retrieve_context          (from M3 — one query string argument)
    - final_answer              (terminates the loop with a result)

NOT_YET_MODELED (explicit, per gameplan Section 6a — no self-certified
"done" without naming what this milestone does not cover):
    - No cost/token-budget termination condition (Section 6/M4 lists only
      max iterations + timeout + allowlist; a budget cap is M5/M6 territory
      per the gameplan's own observability milestone).
    - No mid-loop human-in-the-loop interrupt/approval gate.
    - No persistence of trajectories across process runs (each run's log
      is returned to the caller and/or written to _debug/ for this run only).
    - No multi-agent handoff — this is a single reasoning loop, not the
      4-seat AVM Syndicate pipeline used elsewhere in this repository.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

# Allow import from kitty-hawk/core, /scripts, and repo root (for rag package)
THIS_DIR = Path(__file__).resolve().parent
REPO_ROOT = THIS_DIR.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
for p in (str(THIS_DIR), str(SCRIPTS_DIR), str(REPO_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from provider_protocol import SynapseProvider  # noqa: E402
from watsonx_client import WatsonXClient  # noqa: E402
import watsonx_ping  # noqa: E402  (reuses the bounded M1 tool + one-call boundary)
from rag.store import RagStore  # noqa: E402
from rag.corpus import load_controlled_corpus  # noqa: E402

MAX_ITERATIONS = 3
DEFAULT_TIMEOUT_SECONDS = 30.0

ACTION_MANIFEST = "read_kitty_hawk_manifest"
ACTION_RETRIEVE = "retrieve_context"
ACTION_FINAL = "final_answer"
ALLOWED_ACTIONS = (ACTION_MANIFEST, ACTION_RETRIEVE, ACTION_FINAL)

TERMINATION_SUCCESS = "success"
TERMINATION_MAX_ITERATIONS = "max_iterations"
TERMINATION_TIMEOUT = "timeout"
TERMINATION_DISALLOWED_ACTION = "disallowed_action"

LOOP_SYSTEM_PROMPT = (
    "You are a bounded reasoning agent for Kitty Hawk M4. You have exactly "
    "two tools plus a way to finish: "
    f'"{ACTION_MANIFEST}" (no input needed), '
    f'"{ACTION_RETRIEVE}" (input is a search query string), and '
    f'"{ACTION_FINAL}" (input is your final answer text). '
    "On every turn, respond ONLY with valid JSON containing exactly these "
    'keys: thought, action, action_input. "action" must be exactly one of '
    f'{list(ALLOWED_ACTIONS)}. Never invent a tool name. If you have enough '
    f'information to answer, use "{ACTION_FINAL}" -- do not keep calling '
    "tools once you can already answer."
)


class DisallowedActionError(RuntimeError):
    """Raised when a step's action is not in ALLOWED_ACTIONS. Fail-closed:
    the loop terminates immediately rather than executing an unknown tool."""


def _parse_step(raw: str) -> dict[str, Any]:
    """Parses and validates one reasoning step's JSON. Raises ValueError for
    malformed JSON/missing keys, DisallowedActionError for an unknown action
    -- callers must treat these as distinct termination causes, not the same
    failure, since a disallowed action is a fail-closed policy decision, not
    a transport error."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"step must be valid JSON, got: {raw!r}") from e
    if not isinstance(data, dict):
        raise ValueError(f"step JSON must be an object, got {type(data)}")
    for k in ("thought", "action", "action_input"):
        if k not in data:
            raise ValueError(f"step JSON missing required key: {k!r} in {data}")
    if data["action"] not in ALLOWED_ACTIONS:
        raise DisallowedActionError(
            f"action {data['action']!r} is not in the allowlist {ALLOWED_ACTIONS}"
        )
    return data


def _execute_tool(action: str, action_input: str, *, rag_store: RagStore) -> str:
    """Executes exactly one allowlisted tool and returns its observation as
    a string. final_answer is handled by the caller before this is reached
    -- this function only ever sees the two real tools."""
    if action == ACTION_MANIFEST:
        return watsonx_ping._read_kitty_hawk_manifest()
    if action == ACTION_RETRIEVE:
        retrieved = rag_store.retrieve(action_input)
        return rag_store.to_context(retrieved)
    raise DisallowedActionError(f"_execute_tool received an unexpected action: {action!r}")


def _build_prompt(goal: str, trajectory: list[dict[str, Any]]) -> str:
    lines = [f"Goal: {goal}"]
    if trajectory:
        lines.append("Trajectory so far:")
        for i, step in enumerate(trajectory, start=1):
            lines.append(
                f"Step {i}: thought={step['thought']!r} action={step['action']!r} "
                f"action_input={step['action_input']!r} observation={step.get('observation', '')!r}"
            )
    lines.append(
        "Respond with the next step as JSON (thought, action, action_input)."
    )
    return "\n".join(lines)


def run_agent_loop(
    goal: str,
    *,
    client: SynapseProvider | None = None,
    rag_store: RagStore | None = None,
    max_iterations: int = MAX_ITERATIONS,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """M4 entry: goal -> bounded Observe->Reason->Act->Observe loop -> result dict.

    Returns a dict with keys: goal, termination, answer (or None), trajectory
    (list of step dicts), iterations_used, elapsed_seconds.

    Bounds enforced, in the order they can trip:
      1. timeout_seconds wall-clock budget across the whole run.
      2. max_iterations reasoning/tool steps.
      3. allowlist check on every single step -- an unknown action terminates
         the loop immediately rather than being executed.

    Never raises on a bounded failure (max_iterations/timeout/disallowed
    action) -- those are valid, expected terminal states reported in the
    return value, not exceptions. Still raises ValueError for a goal that
    is empty, and for malformed step JSON the model itself cannot recover
    from (distinct from an allowlist violation, which the model chose).
    """
    if not goal or not goal.strip():
        raise ValueError("goal must be non-empty")

    c = client or WatsonXClient()
    try:
        c.set_agent("ECHO-PROPHET")
    except Exception:
        pass
    c.system_prompt = LOOP_SYSTEM_PROMPT

    store = rag_store
    owns_store = False
    if store is None:
        store = RagStore(persist_path=None)
        store.add_documents(load_controlled_corpus())
        owns_store = True

    trajectory: list[dict[str, Any]] = []
    start = time.monotonic()
    termination: str | None = None
    answer: str | None = None
    iterations_used = 0

    try:
        for iteration in range(1, max_iterations + 1):
            elapsed = time.monotonic() - start
            if elapsed >= timeout_seconds:
                termination = TERMINATION_TIMEOUT
                break

            prompt = _build_prompt(goal.strip(), trajectory)
            raw = c.ask(prompt)

            # The ask() call itself may have consumed the whole budget --
            # check immediately, before trusting or acting on its result,
            # regardless of what action the model chose. A model that
            # finalizes on a call that ran over budget still timed out.
            if time.monotonic() - start >= timeout_seconds:
                termination = TERMINATION_TIMEOUT
                iterations_used = iteration
                break

            try:
                step = _parse_step(raw)
            except DisallowedActionError:
                termination = TERMINATION_DISALLOWED_ACTION
                iterations_used = iteration
                break

            iterations_used = iteration

            if step["action"] == ACTION_FINAL:
                answer = step["action_input"]
                step["observation"] = "(terminal step -- no tool executed)"
                trajectory.append(step)
                termination = TERMINATION_SUCCESS
                break

            observation = _execute_tool(step["action"], step["action_input"], rag_store=store)
            step["observation"] = observation
            trajectory.append(step)

            if time.monotonic() - start >= timeout_seconds:
                termination = TERMINATION_TIMEOUT
                break
        else:
            termination = None  # loop exhausted range() without an explicit break

        if termination is None:
            termination = TERMINATION_MAX_ITERATIONS
    finally:
        if owns_store:
            store.clear()

    return {
        "goal": goal.strip(),
        "termination": termination,
        "answer": answer,
        "trajectory": trajectory,
        "iterations_used": iterations_used,
        "elapsed_seconds": round(time.monotonic() - start, 4),
    }


def main() -> None:
    import argparse

    p = argparse.ArgumentParser(description="M4 bounded agent/tool loop")
    p.add_argument("--goal", default="What is the Kitty Hawk capstone target per the gameplan?")
    p.add_argument("--max-iterations", type=int, default=MAX_ITERATIONS)
    p.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    p.add_argument("--json", action="store_true", help="print JSON only")
    args = p.parse_args()

    result = run_agent_loop(args.goal, max_iterations=args.max_iterations, timeout_seconds=args.timeout)
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    print(f"\nM4 proof: terminated via {result['termination']!r} after {result['iterations_used']} iteration(s).")


if __name__ == "__main__":
    main()
