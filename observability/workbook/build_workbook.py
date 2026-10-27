"""Build (and check) the Agent Wall cockpit workbook - observability\\workbook\\cockpit.workbook.json.

The workbook is plain Azure Workbooks JSON (Notebook/1.0). Queries live here, as Python strings, so they can be run before they ever
reach the portal:

    python observability\\workbook\\build_workbook.py build            # writes cockpit.workbook.json (consumed by infra\\06b-observability.bicep)
    python observability\\workbook\\build_workbook.py check            # runs every embedded Log Analytics / Resource Graph query

Placeholders __WORKSPACE_ID__, __SUBSCRIPTION_ID__ and __RESOURCE_GROUP__ are substituted by the Bicep template at deploy time. Every
Log Analytics query calls the ABW function pack (observability\\kql\\*.kql), so the workbook, the Sentinel rules and the CLI all read
the same definitions. The workbook TimeRange parameter bounds the data; the functions are called with their widest lookback.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import uuid

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = HERE / "cockpit.workbook.json"

WS = "__WORKSPACE_ID__"
SUB = "__SUBSCRIPTION_ID__"
RG = "__RESOURCE_GROUP__"
ASSIGNMENT = "abw-agent-platform-controls"

LA_TYPE = "microsoft.operationalinsights/workspaces"
ARG_TYPE = "microsoft.resourcegraph/resources"

_collected: list[dict] = []  # every query, for `check`


def gid(seed: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"abw-cockpit/{seed}"))


# ------------------------------------------------------------------------------------------------ item builders
def text(md: str, name: str) -> dict:
    return {"type": 1, "content": {"json": md}, "name": name}


def thresholds(column: str, mapping: dict[str, str], default: str = "blue") -> dict:
    grid = [{"operator": "==", "thresholdValue": k, "representation": v, "text": "{0}{1}"} for k, v in mapping.items()]
    grid.append({"operator": "Default", "thresholdValue": None, "representation": default, "text": "{0}{1}"})
    return {"columnMatch": column, "formatter": 18, "formatOptions": {"thresholdsOptions": "colors", "thresholdsGrid": grid}}


DECISION = {"allow": "green", "deny": "redBright", "error": "orange", "guardrail_blocked": "purple"}
LAYERS = {
    "0-agent-guardrail": "purple",
    "1-gateway": "blue",
    "2-mcp-server": "orange",
    "3-data-plane": "redBright",
}


def query(
    name: str,
    title: str,
    kql: str,
    *,
    kind: str = "la",
    vis: str = "table",
    size: int = 0,
    width: str | None = None,
    formatters: list[dict] | None = None,
    tiles: bool = False,
    export: tuple[str, str] | None = None,
    note: str | None = None,
) -> dict:
    kql = kql.strip()
    _collected.append({"name": name, "kind": kind, "query": kql, "title": title})
    content: dict = {
        "version": "KqlItem/1.0",
        "query": kql,
        "size": size,
        "title": title,
        "queryType": 0 if kind == "la" else 1,
        "resourceType": LA_TYPE if kind == "la" else ARG_TYPE,
        "crossComponentResources": [WS] if kind == "la" else [f"/subscriptions/{SUB}"],
        "visualization": "tiles" if tiles else vis,
    }
    if kind == "la":
        content["timeContextFromParameter"] = "TimeRange"
    if formatters:
        content["gridSettings"] = {"formatters": formatters, "filter": True}
    if tiles:
        content["tileSettings"] = {
            "titleContent": {"columnMatch": "Label", "formatter": 1},
            "leftContent": {
                "columnMatch": "Value",
                "formatter": 12,
                "formatOptions": {"palette": "auto"},
                "numberFormat": {"unit": 17, "options": {"maximumSignificantDigits": 4, "maximumFractionDigits": 0}},
            },
            "showBorder": True,
        }
    if vis in ("barchart", "areachart", "timechart"):
        content["chartSettings"] = {"showLegend": True}
    if export:
        content["exportFieldName"] = export[0]
        content["exportParameterName"] = export[1]
        content["exportDefaultValue"] = "none"
    if note:
        content["noDataMessage"] = note
    item: dict = {"type": 3, "content": content, "name": name}
    if width:
        item["customWidth"] = width
    return item


def group(tab: str, items: list[dict]) -> dict:
    return {
        "type": 12,
        "content": {"version": "NotebookGroup/1.0", "groupType": "editable", "items": items},
        "conditionalVisibility": {"parameterName": "tab", "comparison": "isEqualTo", "value": tab},
        "name": f"group - {tab}",
    }


# ------------------------------------------------------------------------------------------------ tabs
def tab_overview() -> list[dict]:
    return [
        text(
            "### What is happening on the agent platform\n"
            "Every number below comes from the platform's own audit trail (APIM gateway log + MCP server audit + Foundry traces) - "
            "no agent, model or MCP server had to be modified to produce it.\n\n"
            "Decisions: `allow` green, `deny` red, `error` orange, `guardrail_blocked` purple - the Foundry guardrail stopped the agent run. "
            "A run stopped on its prompt never reaches a tool, so it shows no tool or server. In the agent grid, `User` is the identity the tool "
            "saw and `RunBy` is who started the agent run.",
            "ov-text",
        ),
        query(
            "ov-tiles",
            "Platform at a glance",
            """
let u = AbwUsageByUser(30d);
let d = AbwDenials(30d);
let k = AbwZeroKeys(30d) | where KeyBased | summarize v = sum(Requests);
union
    (u | summarize Value = tolong(sum(Calls)) | extend Label = 'Agent tool calls', Ord = 1),
    (u | where User != '(no user context)' | summarize Value = tolong(dcount(User)) | extend Label = 'People using agents', Ord = 2),
    (u | summarize Value = tolong(sum(Denied)) | extend Label = 'Calls refused', Ord = 3),
    (d | where Layer == '0-agent-guardrail' | summarize Value = tolong(count()) | extend Label = 'Agent runs stopped by the guardrail', Ord = 4),
    (d | summarize Value = tolong(dcount(Layer)) | extend Label = 'Defence layers that fired', Ord = 5),
    (k | project Value = tolong(coalesce(v, 0)), Label = 'Key / SAS storage requests', Ord = 6)
| order by Ord asc
| project Label, Value
""",
            tiles=True,
            width="100",
        ),
        query(
            "ov-trend",
            "Tool calls and guardrail stops over time, by decision",
            """
let calls = AbwMcpAudit(30d)
    | where Event != 'tool_listed'
    | summarize Calls = count() by bin(TimeGenerated, {TimeRange:grain}), Decision;
let stopped = AbwDenials(30d)
    | where Layer == '0-agent-guardrail'
    | summarize Calls = count() by bin(TimeGenerated, {TimeRange:grain}), Decision = 'guardrail_blocked';
union calls, stopped
""",
            vis="areachart",
            size=1,
            width="50",
        ),
        query(
            "ov-tools",
            "Calls by tool and decision (guardrail stops included)",
            """
let calls = AbwMcpAudit(30d)
    | where Event != 'tool_listed'
    | summarize Calls = count() by Tool, Decision;
let stopped = AbwAgentActivity(30d)
    | where Decision == 'guardrail_blocked'
    | summarize Calls = count() by Tool = iff(isempty(Tool), '(stopped before any tool call)', Tool), Decision;
union calls, stopped
| order by Calls desc
| take 30
""",
            vis="barchart",
            size=1,
            width="50",
        ),
        query(
            "ov-users",
            "Who uses agents (per Entra user)",
            """
AbwUsageByUser(30d)
| project User, Calls, Allowed, Denied, DenyRatePct, DistinctTools, Servers = tostring(Servers), LastSeen
""",
        ),
        query(
            "ov-guardrail",
            "Agent runs stopped by the Foundry guardrail",
            """
AbwAgentActivity(30d)
| where Decision == 'guardrail_blocked'
| project TimeGenerated, Agent, AgentVersion, RunBy, Tool = iff(isempty(Tool), '(none: stopped before any tool call)', Tool), Guardrail, DurationMs, TraceId
| order by TimeGenerated desc
| take 100
""",
            note="No agent run was stopped by the Foundry guardrail in this time range. Widen the range, or send the jailbreak from the Demo Console (Act 6) and refresh in a few minutes.",
        ),
        query(
            "ov-agents",
            "Agent -> user -> tool (Foundry trace joined to the audit trail)",
            """
AbwAgentActivity(30d)
| project TimeGenerated, Agent, AgentVersion, RunBy, User, Tool, Decision, Reason, Guardrail, Server, DataClass, OnBehalfOf, DurationMs, RequestId
| take 200
""",
            formatters=[thresholds("Decision", DECISION)],
        ),
    ]


def tab_identity() -> list[dict]:
    return [
        text(
            "### One request, every hop: from the Entra sign-in to the data plane\n"
            "Select a tool call, or an agent run the Foundry guardrail stopped. The chain stitches the layers together on the key each one logs: "
            "the `request_id` (APIM gateway, MCP server, Storage data plane), the Entra token id (ties the sign-in and token issue to the tool call) "
            "and the Foundry trace id (the agent run and the guardrail verdict). Each layer shows the principal it saw - that is the answer to "
            "*\"who actually touched this data, on whose behalf?\"*\n\n"
            "The interactive Entra sign-in that started a session can be days older than the call, because later tokens are refreshed from it without "
            "a prompt, so the Entra rows carry their own timestamps. A run stopped on its prompt never reaches a tool, so it is listed by its trace id.",
            "id-text",
        ),
        query(
            "id-recent",
            "Recent tool calls and guardrail stops (click a row)",
            """
let calls = AbwMcpAudit(30d)
    | where Event != 'tool_listed' and isnotempty(RequestId)
    | project TimeGenerated, User = UserUpn, Server, Tool, Decision, Reason, RequestId
    | order by TimeGenerated desc
    | take 100;
let stopped = AbwAgentActivity(30d)
    | where Decision == 'guardrail_blocked'
    | project TimeGenerated, User = RunBy, Server = iff(isempty(Server), '(guardrail)', Server),
        Tool = iff(isempty(Tool), '(stopped before any tool call)', Tool), Decision, Reason,
        RequestId = iff(isnotempty(RequestId), RequestId, TraceId)
    | order by TimeGenerated desc
    | take 30;
union calls, stopped
| order by TimeGenerated desc
""",
            formatters=[thresholds("Decision", DECISION)],
            export=("RequestId", "RequestId"),
        ),
        {
            **query(
                "id-chain",
                "Every hop for the selected request",
                """
AbwFullChain('{RequestId}', 30d)
| project Time, Step, Layer, Actor, Action, Detail
""",
            ),
            "conditionalVisibility": {"parameterName": "RequestId", "comparison": "isNotEqualTo", "value": "none"},
        },
        query(
            "id-tokens",
            "Different people, different tokens (what the MCP servers verified)",
            """
let t = AbwMcpAudit(30d)
    | where Event != 'tool_listed' and isnotempty(UserUpn) and isnotempty(TokenId);
let r = t
    | mv-expand Role = Roles to typeof(string)
    | where isnotempty(Role)
    | summarize Roles = strcat_array(make_set(Role), ', ') by User = UserUpn;
t
| summarize Calls = count(), Tokens = dcount(TokenId), FirstCall = min(TimeGenerated), LastCall = max(TimeGenerated) by User = UserUpn
| lookup kind=leftouter r on User
| project User, Tokens, Calls, Roles, FirstCall, LastCall
| order by LastCall desc
""",
            note="No user tokens were verified by an MCP server in this time range.",
        ),
    ]


def tab_governance() -> list[dict]:
    states = (
        "policyresources\n| where type =~ 'microsoft.policyinsights/policystates'\n"
        "| where tostring(properties.policyAssignmentName) =~ '" + ASSIGNMENT + "'\n"
        "| where tostring(properties.resourceGroup) =~ '__RESOURCE_GROUP__'"
    )
    return [
        text(
            "### Governance posture - Azure Policy on the agent platform\n"
            "One initiative (`" + ASSIGNMENT + "`) carries the platform controls: no keys, private-only data planes, approved MCP targets and models, "
            "guardrail policies. Deny-effect controls refuse non-compliant deployments; every exemption is explicit and listed below.",
            "gov-text",
        ),
        query(
            "gov-summary",
            "Compliance of the demo resource group",
            states + "\n| summarize Value = tolong(count()) by Label = tostring(properties.complianceState)\n| order by Label asc",
            kind="arg",
            tiles=True,
            width="100",
        ),
        query(
            "gov-groups",
            "Control groups",
            states
            + """
| extend State = tostring(properties.complianceState)
| mv-expand Group = properties.policyDefinitionGroupNames to typeof(string)
| summarize Evaluations = count(), Compliant = countif(State == 'Compliant'), NonCompliant = countif(State == 'NonCompliant'), Exempt = countif(State == 'Exempt') by Group
| order by Group asc""",
            kind="arg",
            width="50",
        ),
        query(
            "gov-effects",
            "Assignment and effects",
            """
policyresources
| where type =~ 'microsoft.authorization/policyassignments'
| where name =~ '"""
            + ASSIGNMENT
            + """'
| project Assignment = name, Enforcement = tostring(properties.enforcementMode),
    HardControls = coalesce(tostring(properties.parameters.denyEffect.value), 'initiative default (Deny)'),
    AuditControls = coalesce(tostring(properties.parameters.auditEffect.value), 'initiative default (Audit)'),
    AgentToolControls = coalesce(tostring(properties.parameters.toolsEffect.value), 'initiative default (Audit)')""",
            kind="arg",
            width="50",
        ),
        query(
            "gov-noncompliant",
            "Non-compliant evaluations (what would have been refused if created today)",
            states
            + """
| where tostring(properties.complianceState) =~ 'NonCompliant'
| project Resource = tostring(split(tostring(properties.resourceId), '/')[-1]), Type = tostring(properties.resourceType),
    Control = tostring(properties.policyDefinitionReferenceId), Group = tostring(properties.policyDefinitionGroupNames),
    Since = todatetime(properties.timestamp)
| order by Resource asc""",
            kind="arg",
            note="Nothing is non-compliant (or the first policy scan has not finished yet).",
        ),
        query(
            "gov-exemptions",
            "Exemptions - every exception is explicit, justified and (where possible) time-boxed",
            """
policyresources
| where type =~ 'microsoft.authorization/policyexemptions'
| where id contains '/resourcegroups/__RESOURCE_GROUP__/'
| extend Scope = tostring(split(tostring(split(id, '/providers/Microsoft.Authorization/')[0]), '/')[-1])
| project Exemption = name, Category = tostring(properties.exemptionCategory), Scope, Expires = todatetime(properties.expiresOn),
    Controls = tostring(properties.policyDefinitionReferenceIds), Reason = tostring(properties.description)
| order by Category asc, Exemption asc""",
            kind="arg",
            formatters=[thresholds("Category", {"Waiver": "orange", "Mitigated": "yellow"})],
        ),
    ]


def tab_threats() -> list[dict]:
    return [
        text(
            "### Defence in depth - which layer stopped what\n"
            "`0-agent-guardrail` Foundry content safety (jailbreak, indirect prompt injection)  |  `1-gateway` APIM (token, client, role, rate limit, kill-switch)  |  "
            "`2-mcp-server` the tool itself (entitlement, data class, restricted list)  |  `3-data-plane` Azure RBAC on the data store, evaluated for the **user**.\n\n"
            "Not in these four layers: sign-in refusals (bad password, failed MFA, Conditional Access) are logged by Entra, in the Entra sign-in log. "
            "Microsoft Sentinel incidents are listed below; Defender XDR (Security for AI agents), Agent 365 and Purview DSPM for AI report in their "
            "own admin portals and are not pulled into this workbook.",
            "th-text",
        ),
        query(
            "th-incidents",
            "Microsoft Sentinel incidents raised by the ABW analytics rules",
            """
SecurityIncident
| where Title startswith 'ABW'
| summarize arg_max(TimeGenerated, *) by IncidentNumber
| project Created = CreatedTime, IncidentNumber, Title, Severity, Status, Owner = tostring(Owner.assignedTo), Alerts = array_length(AlertIds)
| order by Created desc""",
            note="No Sentinel incidents in this window.",
        ),
        query(
            "th-trend",
            "Refusals over time, by layer",
            """
AbwDenials(30d)
| summarize Refusals = count() by bin(TimeGenerated, {TimeRange:grain}), Layer
""",
            vis="areachart",
            size=1,
            width="50",
        ),
        query(
            "th-control",
            "Refusals by control",
            """
AbwDenials(30d)
| summarize Refusals = count(), Principals = dcount(Principal) by Layer, Control, Reason
| order by Refusals desc
""",
            size=1,
            width="50",
            formatters=[thresholds("Layer", LAYERS)],
        ),
        query(
            "th-recent",
            "Recent refusals",
            """
AbwDenials(30d)
| project TimeGenerated, Layer, Control, Principal, Target, Reason, RequestId
| order by TimeGenerated desc
| take 100
""",
            formatters=[thresholds("Layer", LAYERS)],
        ),
        query(
            "th-wall",
            "Wall violations and blocked orders (the signals the Sentinel rules key on)",
            """
AbwMcpAudit(30d)
| where Event in ('wall_violation_attempt', 'order_blocked')
| project TimeGenerated, User = UserUpn, Event, Server, Tool, Reason, DataClass, RequestId
| order by TimeGenerated desc
""",
        ),
    ]


def tab_gateway() -> list[dict]:
    return [
        text("### Gateway and MCP servers - health, latency and the identity that was used downstream", "gw-text"),
        query(
            "gw-outcomes",
            "Gateway requests by outcome",
            """
AbwGateway(30d)
| summarize Requests = count() by bin(TimeGenerated, {TimeRange:grain}), Outcome
""",
            vis="areachart",
            size=1,
            width="50",
        ),
        query(
            "gw-servers",
            "Per MCP server (APIM)",
            """
AbwGateway(30d)
| summarize Requests = count(), P50ms = round(percentile(TotalTimeMs, 50)), P95ms = round(percentile(TotalTimeMs, 95)),
    Allowed = countif(Outcome == 'allowed'), Denied = countif(Outcome == 'denied'), Throttled = countif(Outcome == 'rate_limited'),
    Unauthenticated = countif(Outcome == 'unauthenticated'), Errors = countif(Outcome == 'gateway_or_backend_error') by Server
| order by Requests desc
""",
            size=1,
            width="50",
        ),
        query(
            "gw-obo",
            "Whose identity reached the tool? (on-behalf-of vs shared)",
            """
AbwMcpAudit(30d)
| where Event != 'tool_listed'
| summarize Calls = count() by Server, Identity = iff(OnBehalfOf == true, 'user (on-behalf-of)', 'shared / no user')
| order by Server asc
""",
            vis="barchart",
            size=1,
            width="50",
        ),
        query(
            "gw-downstream",
            "MCP server -> data store calls (the user's token is exchanged, never a key)",
            """
AbwMcpAudit(30d)
| where isnotempty(DownstreamService)
| summarize Calls = count(), Failures = countif(toint(DownstreamStatus) >= 400) by Server, DownstreamService, DownstreamTarget
| order by Calls desc
""",
            size=1,
            width="50",
        ),
    ]


def tab_finops() -> list[dict]:
    return [
        text(
            "### Who spends the tokens - and what stops a runaway agent\n"
            "Measured at the APIM agent front door (`llm-emit-token-metric`) and keyed by the same Entra user the hourly token budget "
            "(`llm-token-limit`) is enforced on, so a cost line and a quota line always name the same person. "
            "Dollar spend per Azure service lives in Cost Management for this resource group, where the budget alert is also set.",
            "fo-text",
        ),
        query(
            "fo-tiles",
            "Agent spend at a glance",
            """
let t = AbwTokenUsage(30d);
let d = AbwDenials(30d) | where Control == 'llm-token-limit';
union
    (t | summarize Value = tolong(sum(TotalTokens)) | extend Label = 'Model tokens', Ord = 1),
    (t | summarize Value = tolong(sum(Runs)) | extend Label = 'Agent runs', Ord = 2),
    (t | summarize Value = tolong(dcount(UserOid)) | extend Label = 'People who spent tokens', Ord = 3),
    (d | summarize Value = tolong(count()) | extend Label = 'Runs refused: token budget used up', Ord = 4)
| order by Ord asc
| project Label, Value
""",
            tiles=True,
            width="100",
        ),
        query(
            "fo-trend",
            "Tokens per person over time",
            """
AbwTokenUsage(30d)
| summarize Tokens = sum(TotalTokens) by TimeGenerated = bin(Hour, {TimeRange:grain}), User
""",
            vis="barchart",
            size=1,
            width="50",
        ),
        query(
            "fo-by-user",
            "Per person: runs and tokens",
            """
AbwTokenUsage(30d)
| summarize Runs = sum(Runs), InputTokens = sum(InputTokens), OutputTokens = sum(OutputTokens), TotalTokens = sum(TotalTokens), LastSeen = max(LastSeen) by User
| extend TokensPerRun = round(todouble(TotalTokens) / iff(Runs == 0, 1, Runs))
| order by TotalTokens desc
""",
            size=1,
            width="50",
        ),
        query(
            "fo-by-agent",
            "Per agent: which agent costs what",
            """
AbwTokenUsage(30d)
| summarize Runs = sum(Runs), InputTokens = sum(InputTokens), OutputTokens = sum(OutputTokens), TotalTokens = sum(TotalTokens), People = dcount(UserOid) by Agent
| extend TokensPerRun = round(todouble(TotalTokens) / iff(Runs == 0, 1, Runs))
| order by TotalTokens desc
""",
            size=1,
            width="50",
        ),
        query(
            "fo-refusals",
            "Refused at the agent front door (token budget, per-minute limit, revoked user, bad token)",
            """
AbwDenials(30d)
| where Layer == '1-gateway' and Target startswith 'agents '
| project TimeGenerated, Principal, Control, Reason, RequestId
| order by TimeGenerated desc
| take 100
""",
            size=1,
            width="50",
        ),
    ]


def tab_keys() -> list[dict]:
    return [
        text(
            "### Zero keys - proven two ways\n"
            "**Configuration**: key authentication is switched off on every data plane (and Azure Policy denies turning it back on).  "
            "**Behaviour**: every Storage data-plane request is logged with its authentication type - `AccountKey` / `SAS` must stay at zero.",
            "zk-text",
        ),
        query(
            "zk-storage",
            "Storage requests by authentication type",
            """
AbwZeroKeys(30d)
| extend Authentication = iff(KeyBased, 'KEY / SAS (violation)', 'keyless')
| project Account, AuthType, Authentication, Requests, Denied, LastSeen
""",
            formatters=[thresholds("Authentication", {"KEY / SAS (violation)": "redBright", "keyless": "green"})],
            width="50",
            size=1,
        ),
        query(
            "zk-posture",
            "Key authentication switches (Azure Resource Graph, live)",
            """
resources
| where resourceGroup =~ '__RESOURCE_GROUP__'
| where type in~ ('microsoft.storage/storageaccounts', 'microsoft.documentdb/databaseaccounts', 'microsoft.search/searchservices', 'microsoft.cognitiveservices/accounts', 'microsoft.keyvault/vaults', 'microsoft.containerregistry/registries')
| extend KeyAuth = case(
    type =~ 'microsoft.storage/storageaccounts', iff(tobool(properties.allowSharedKeyAccess) == false, 'disabled', 'ENABLED'),
    type =~ 'microsoft.documentdb/databaseaccounts', iff(tobool(properties.disableLocalAuth) == true, 'disabled', 'ENABLED'),
    type =~ 'microsoft.search/searchservices', iff(tobool(properties.disableLocalAuth) == true, 'disabled', 'ENABLED'),
    type =~ 'microsoft.cognitiveservices/accounts', iff(tobool(properties.disableLocalAuth) == true, 'disabled', 'ENABLED'),
    type =~ 'microsoft.keyvault/vaults', iff(tobool(properties.enableRbacAuthorization) == true, 'disabled', 'ENABLED'),
    type =~ 'microsoft.containerregistry/registries', iff(tobool(properties.adminUserEnabled) == false, 'disabled', 'ENABLED'),
    'n/a')
| project Resource = name, Type = tostring(split(type, '/')[1]), KeyAuth, PublicNetwork = coalesce(tostring(properties.publicNetworkAccess), 'n/a')
| order by Type asc, Resource asc""",
            kind="arg",
            formatters=[
                thresholds("KeyAuth", {"disabled": "green", "ENABLED": "redBright"}),
                thresholds("PublicNetwork", {"Disabled": "green", "Enabled": "yellow"}, default="gray"),
            ],
            width="50",
            size=1,
        ),
    ]


def tab_changes() -> list[dict]:
    return [
        text(
            "### Who changed the platform?\n"
            "Azure Resource Graph change history for the demo resource group (control-plane changes, last 14 days) - the infosec view of "
            "*configuration drift*. Combined with Azure Policy `Deny`, a control that was turned off is either refused or shows up here.",
            "ch-text",
        ),
        query(
            "ch-changes",
            "Resource changes",
            """
resourcechanges
| extend target = tostring(properties.targetResourceId), ts = todatetime(properties.changeAttributes.timestamp)
| where target contains '/resourcegroups/__RESOURCE_GROUP__/'
| project Time = ts, Change = tostring(properties.changeType), Resource = tostring(split(target, '/')[-1]),
    Type = tostring(properties.targetResourceType), ChangedBy = tostring(properties.changeAttributes.changedBy),
    Properties = toint(properties.changeAttributes.changesCount)
| order by Time desc
| take 100""",
            kind="arg",
            formatters=[thresholds("Change", {"Create": "green", "Update": "blue", "Delete": "redBright"}, default="gray")],
        ),
    ]


TABS = [
    ("overview", "Overview", tab_overview),
    ("identity", "Identity chain", tab_identity),
    ("governance", "Governance", tab_governance),
    ("threats", "Threats & layers", tab_threats),
    ("gateway", "Gateway & MCP", tab_gateway),
    ("finops", "Cost & tokens", tab_finops),
    ("keys", "Zero keys", tab_keys),
    ("changes", "Changes", tab_changes),
]


def build() -> dict:
    _collected.clear()
    ranges = [3_600_000, 21_600_000, 86_400_000, 259_200_000, 604_800_000, 1_209_600_000, 2_592_000_000]
    items: list[dict] = [
        text(
            "# Agent Wall - Cockpit\n"
            "Observability, governance and security for agents that reach regulated data - **keyless**, **on-behalf-of**, "
            "**enforced at the MCP tool**. Built entirely from Azure-native telemetry: APIM, Container Apps, Foundry (Application Insights), Storage, "
            "Azure Policy, Resource Graph and Microsoft Sentinel.",
            "title",
        ),
        {
            "type": 9,
            "content": {
                "version": "KqlParameterItem/1.0",
                "parameters": [
                    {
                        "id": gid("p-time"),
                        "version": "KqlParameterItem/1.0",
                        "name": "TimeRange",
                        "label": "Time range",
                        "type": 4,
                        "isRequired": True,
                        "value": {"durationMs": 604_800_000},
                        "typeSettings": {"selectableValues": [{"durationMs": ms} for ms in ranges], "allowCustom": True},
                        "timeContext": {"durationMs": 604_800_000},
                    },
                    {
                        "id": gid("p-tab"),
                        "version": "KqlParameterItem/1.0",
                        "name": "tab",
                        "type": 1,
                        "isRequired": False,
                        "value": "overview",
                        "isHiddenWhenLocked": True,
                    },
                ],
                "style": "pills",
                "queryType": 0,
                "resourceType": LA_TYPE,
            },
            "name": "parameters - global",
        },
        {
            "type": 11,
            "content": {
                "version": "LinkItem/1.0",
                "style": "tabs",
                "links": [
                    {
                        "id": gid(f"link-{key}"),
                        "cellValue": "tab",
                        "linkTarget": "parameter",
                        "linkLabel": label,
                        "subTarget": key,
                        "style": "link",
                    }
                    for key, label, _ in TABS
                ],
            },
            "name": "links - tabs",
        },
    ]
    for key, _, fn in TABS:
        items.append(group(key, fn()))
    return {
        "version": "Notebook/1.0",
        "items": items,
        "fallbackResourceIds": [WS],
        "$schema": "https://github.com/Microsoft/Application-Insights-Workbooks/blob/master/schema/workbook.json",
    }


# ------------------------------------------------------------------------------------------------ commands
def cmd_build(_: argparse.Namespace) -> None:
    payload = build()
    OUT.write_text(json.dumps(payload, separators=(",", ":"), ensure_ascii=True) + "\n", encoding="utf-8")
    kinds = {k: sum(1 for q in _collected if q["kind"] == k) for k in ("la", "arg")}
    print(f"wrote {OUT.relative_to(ROOT)}  ({OUT.stat().st_size:,} bytes; {len(_collected)} queries: {kinds['la']} Log Analytics, {kinds['arg']} Resource Graph)")


def _config() -> dict:
    return json.loads((ROOT / "infra" / "generated" / "config.json").read_text(encoding="utf-8"))


def cmd_check(args: argparse.Namespace) -> None:
    build()
    cfg = _config()
    rg = cfg["rgName"]
    sys.path.insert(0, str(ROOT / "observability" / "kql"))
    sys.path.insert(0, str(ROOT / "demo"))
    import pack  # noqa: E402
    from arg import query_rows  # noqa: E402

    sample = pack._run("AbwMcpAudit(30d) | where Event != 'tool_listed' and isnotempty(RequestId) | take 1 | project RequestId", args.hours)
    request_id = sample[0]["RequestId"] if sample else "00000000-0000-0000-0000-000000000000"
    failed = 0
    for q in _collected:
        kql = q["query"].replace("__RESOURCE_GROUP__", rg).replace("__SUBSCRIPTION_ID__", cfg["subscriptionId"])
        kql = kql.replace("{TimeRange:grain}", "1h").replace("{RequestId}", request_id)
        if re.search(r"\{[A-Za-z]+(:[a-z]+)?\}", kql):
            print(f"  FAIL {q['name']:<16} unresolved workbook parameter")
            failed += 1
            continue
        try:
            rows = pack._run(kql, args.hours) if q["kind"] == "la" else query_rows(kql)
            print(f"  ok   {q['name']:<16} {q['kind']:<3} {len(rows)} row(s)")
        except BaseException as exc:  # noqa: BLE001  (SystemExit from the ARG helper)
            failed += 1
            print(f"  FAIL {q['name']:<16} {q['kind']:<3} {str(exc).replace(chr(10), ' ')[:300]}")
    raise SystemExit(1 if failed else 0)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build").set_defaults(fn=cmd_build)
    p_check = sub.add_parser("check")
    p_check.add_argument("--hours", type=float, default=720.0)
    p_check.set_defaults(fn=cmd_check)
    args = parser.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
