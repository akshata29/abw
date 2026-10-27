"""Publish the Agents Behind the Wall agents (v0 legacy POC, v1 governed Wall Desk, red-team build, shielded red-team build) to the Foundry project.

    python src\\agent\\create_agents.py                 # legacy, governed and red-team agents (no guardrail)
    python src\\agent\\create_agents.py --rai abw-agent-guardrails   # + attach the guardrail and publish the shielded red-team agent
    python src\\agent\\create_agents.py --list
"""

from __future__ import annotations

import argparse
import json
import logging
import pathlib
import sys

from azure.identity import AzureCliCredential
from azure.ai.projects import AIProjectClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import netfix  # noqa: E402
from abw_agents import GEN, POC_AGENT, REDTEAM_AGENT, SHIELDED_AGENT, WALL_AGENT, project_endpoint, publish  # noqa: E402

netfix.install()

logger = logging.getLogger(__name__)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rai", help="guardrail (RAI policy) name or full ARM id to attach to the governed agent and the shielded red-team agent")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    project = AIProjectClient(endpoint=project_endpoint(), credential=AzureCliCredential(process_timeout=90))
    if args.list:
        for agent in project.agents.list():
            print(agent.name)
        return 0
    result = publish(project, rai_policy=args.rai)
    (GEN / "agents.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    for name in (POC_AGENT, WALL_AGENT, REDTEAM_AGENT, SHIELDED_AGENT):
        if name not in result:
            continue
        print(f"published {name} v{result[name]['version']}  ({result[name]['id']})")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    sys.exit(main())
