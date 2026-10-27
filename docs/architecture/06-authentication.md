[Index](../ARCHITECTURE-AND-DESIGN.md) | Previous: [5. Identity objects and entitlement model](05-identity-objects.md) | Next: [7. Authorization: the four walls and policy-as-code](07-authorization.md)

## 6. Authentication: identities, tokens and trust

This section follows one governed request from a human sign-in to a data-plane read and names every principal, credential and token on the way: who mints it, who accepts it, how long it lives, and which code, Bicep or policy proves it. The design intent is a single chain of tokens with no shared secret between the user and the data (`DESIGN.md:100-112#OBO`). What a validated token is *allowed to do* (roles, scopes, container and row rules) belongs to the authorization part of this reference; this section stops at "the token is valid and belongs to this user" and shows where the authorization layers read their inputs from.

Every substantial statement carries a provenance label:

- **Implemented** - proven by code in this repo.
- **Configured** - proven by Bicep, policy XML or a provisioning script.
- **Designed** - stated in `DESIGN.md`, `README.md` or `docs\` but not independently proven by code.
- **Platform behaviour** - confirmed on Microsoft Learn (the URL is given).
- "Not in this repo" marks anything the repo neither configures nor proves.

Identifiers are placeholders: `<tenant-id>`, `<client-id>` (the application (client) ID of the app registration named in the sentence) and `<user-oid>`. The public Microsoft Entra sign-in host `login.microsoftonline.com` is written in full. No secret value appears anywhere in this document.

**The chain at a glance.** One governed tool call crosses seven authentication steps; each is expanded in the subsection named in brackets.

1. A person signs in to Microsoft Entra ID. The console uses the device-code flow through the public client `abw-test-client`; Foundry uses the authorization-code flow through the confidential client `abw-agent-client` (6.3, 6.4).
2. On the agent front-door path, the caller first passes APIM, which validates an Entra token whose aud is the Foundry data plane and forwards it unchanged (6.9). Foundry then authorizes the person with Azure RBAC.
3. Foundry holds the user's per-connection access token and presents it as a bearer token to the MCP API at the APIM gateway (6.4, 6.5).
4. APIM validates signature, issuer, aud, tenant, client allow-list, scope, role and the kill switch before anything reaches the MCP app (6.5).
5. The MCP server validates the same token again, independently of APIM (6.6).
6. The MCP server exchanges that token on-behalf-of the user. It proves itself with a managed-identity assertion, so there is no secret on the app (6.7).
7. Storage, Cosmos DB and AI Search accept the exchanged token and apply their own role checks to the user's identity, not the server's (6.8). Lifetimes and revocation are in 6.10; the whole walk, token by token, is in 6.11.

The six "identities" used in the demo are five persona users plus the operator. Managed identities are a different class of principal: they never act as a user and only vouch for the app (6.7).

### 6.1 Principals and credentials inventory

**What this section proves.** Every principal that can authenticate in the estate is listed with its credential and the place that credential lives. The headline is that no MCP app holds a secret: a user's identity travels as a token, platform identities are managed identities, and the few static secrets are named explicitly at the end so none is a surprise (`infra/04-apps.bicep:37-50#vendorKeySecret`).

| principal | type | credential | where the credential lives (never the value) | used for |
|---|---|---|---|---|
| Five persona users `abw.<persona>@<tenant-domain>` (priya, wes, tara, carla, ian) | Entra member users | A generated strong password that never expires (`DisablePasswordExpiration`); a TOTP authenticator seed enrolled by hand | `.secrets\personas.json` and `.secrets\totp.json` on the operator workstation; their cached sign-ins in `.secrets\msal-test-<id>.json`; copies on the jump box only when `-IncludePersonaFiles` is passed. Sources: `identity/Setup-Entra.ps1:198-222#DisablePasswordExpiration`, `scripts/jumpbox-console.ps1:18-23#IncludePersonaFiles` | Signing in as a real user: device code in the console, interactive sign-in in the browser. Designed: each persona holds its own Foundry consents; in the demo tenant only the operator has consented to the agent connections so far (`DESIGN.md:241-241#consented`) (6.3, 6.4) |
| The operator `<operator-upn>` | Entra member user | The person's own interactive sign-in (with the tenant's MFA); no ABW-specific secret | The Azure CLI MSAL cache in the user profile (encrypted persistence file), read by `demo/mcpclient.py:65-73#build_encrypted_persistence` | Deploys the platform, runs the console and the kill switch. Holds Foundry User on the Foundry account, Key Vault Administrator, AcrPush and Search Service Contributor; "no blob, index or document access" (`infra/03-platform.bicep:733-764#raOpKv`, `infra/02-foundry-rbac.bicep:26-34#roleFoundryUser`) |
| `abw-agent-client` | Entra app registration, confidential web client, plus its service principal | Client secret, 80-day lifetime (display name `foundry-connection`) | `.secrets\agent-client.json` on the operator workstation; a copy inside each Foundry connection `mcp-*-oauth`. Source: `identity/Setup-Entra.ps1:150-169#addPassword` | Foundry redeems authorization codes and refresh tokens against Entra with it (token C3 in 6.2) |
| `abw-test-client` | Entra app registration, public client (`isFallbackPublicClient`) | None (public client); the user's refresh token is the long-lived artefact | `.secrets\msal-test-<id>.json`, one file per persona. Source: `identity/Setup-Entra.ps1:171-178#isFallbackPublicClient` | Persona device-code sign-in for the Demo Console (`console/personas.py:4-5#abw-test-client`) and for `demo/mcpclient.py` with `--persona` (`demo/mcpclient.py:89-95#abw-test-client`). Not the CLI, which uses the Azure CLI client (6.3.1), and not `demo/prove.py`, which does not sign personas in: it makes the operator's token mirror a persona's app roles (`demo/prove.py:303-303#mirrors`). The comment at the source line still says the proofs use it (`identity/Setup-Entra.ps1:171-171#prove.py`) |
| Azure CLI first-party client (a well-known Microsoft public application id, kept in `$azCliAppId` at `identity/Setup-Entra.ps1:190-190#azCliAppId`) | Microsoft first-party public client | None | The per-user Azure CLI MSAL cache; pre-authorized on the five MCP APIs by `identity/Setup-Entra.ps1:189-196#preAuthorizedApplications` | The operator's own tokens for the MCP APIs, ARM, Graph and Foundry; `src/agent/ask.py:43-71#PersonaCredential` also uses it for the CLI persona sign-in |
| Five API app registrations: research, wall, actions, private, vendorgw (`abw-mcp-<name>`) | Entra app registrations, single tenant, access-token version 2 | None. Four of them (research, wall, actions, private) carry one federated identity credential; vendorgw has none | Entra. Source: `identity/Setup-Entra.ps1:121-143#oauth2PermissionScopes` | The resource each token is minted for (the app's client ID is the `aud`); define scopes and app roles; each MCP server is the OBO client for its own app (6.7) |
| Six MCP user-assigned managed identities `id-abw-mcp-<key>-<region>-<instance>` (research, wall, actions, private, legacy, vendor) | UAMI | None: tokens are issued by the platform to the running container | Azure. Names: `infra/03-platform.bicep:74-78#uamis` | Pull the image, append the audit blob, supply the OBO client assertion (the four governed servers), act directly where OBO is not used (legacy broad; the actions server reading the restricted container), read Key Vault (vendor) |
| Seed identity `id-abw-seed-<region>-<instance>` | UAMI scoped to the in-VNet seeding job | None | Azure. Source: `infra/04b-seed-job.bicep:45-99#seedId` | Writes the synthetic data (Storage Blob Data Contributor, Search Service and Index Data Contributor, Cosmos Data Contributor); removed by teardown |
| The APIM system-assigned identity | System-assigned managed identity | None | Azure. Source: `infra/05-apim.bicep:51-53#SystemAssigned` | Reads the Key Vault secret behind the named value `abw-vendor-key` (Key Vault Secrets User, `infra/05-apim.bicep:225-233#raApimKv`). It does not authenticate APIM to the MCP servers or to Foundry: a search of `infra`, `scripts`, `src` and `identity` finds no `authentication-managed-identity`, certificate or basic-authentication policy, so the user's own token is what reaches the backends (6.5, 6.9) |
| APIM subscription `sub-abw-legacy-poc` | APIM subscription key | Primary key | APIM; copied into the Foundry connection `mcp-legacy-key`; the console reads it through ARM `listSecrets` when needed. Source: `infra/05-apim-apis.bicep:204-213#sub-abw-legacy-poc` | The deliberately weak legacy path (token C5) |
| The vendor key | Shared secret | 40-character generated value | `.secrets\vendor-api-key.txt`; the Key Vault secret `vendor-api-key`; the APIM named value `abw-vendor-key`; an ACA secret on the vendor app. Sources: `scripts/deploy.ps1:182-186#Get-VendorKey`, `infra/05-apim-apis.bicep:81-91#secretIdentifier` | Gateway-to-vendor calls only (token C6) |
| The Foundry agent identity of `abw-wall-desk` | Entra agent identity with its own blueprint; the new Foundry agent model already created both (`scripts/extras-agent-identity.ps1:10-12#blueprint`) | None held by ABW | Entra | Not the principal of any tool call in this build: tool calls carry the signed-in user's passthrough token, and disabling the identity did not stop them. Source: `scripts/extras-agent-identity.ps1:343-348#identityLeverTest` |
| Jump box VM | Windows VM with one local administrator account (parameters `adminUsername` and `adminPassword`) and no managed identity block | The local administrator password | `.secrets\jumpbox.json` on the operator workstation; never in the VM package. Sources: `infra/07-jumpbox.bicep:14-17#Secrets`, `infra/07-jumpbox.bicep:61-66#adminPassword`, `scripts/jumpbox.ps1:24-26#keyless` | Hosts the console behind Bastion Developer; the operator signs in on it with a device code (6.3.2) |
| Six Entra groups `sg-abw-*` | Security groups | n/a | Entra. Source: `identity/Setup-Entra.ps1:48-48#sg-abw-demo-all` | The subjects of data-plane role assignments and of Foundry Agent Consumer; app roles themselves go to users (see Why below) |
| Application Insights connection string | Ingestion secret | Connection string | ACA secret `appi-conn` on every MCP app. Source: `infra/04-apps.bicep:53-66#appi-conn` | Telemetry ingestion; disclosed in `README.md:142#connection` |
| Storage shared key, Cosmos keys, Search API keys | Switched off | n/a | Storage `allowSharedKeyAccess: false`, Cosmos `disableLocalAuth: true`, Search `disableLocalAuth: true`. Sources: `infra/03-platform.bicep:134-138#allowSharedKeyAccess`, `infra/03-platform.bicep:227-230#disableLocalAuth`, `infra/03-platform.bicep:314-315#disableLocalAuth` | The three data planes accept only Entra tokens (6.8) |

**Static secrets in the estate (the complete list).** These are the only long-lived secrets; everything else is a token or a managed identity.

1. The `abw-agent-client` secret: `.secrets\agent-client.json` and every `mcp-*-oauth` Foundry connection (`DESIGN.md:234-241#secret`).
2. Persona passwords, TOTP seeds and cached persona refresh tokens: `.secrets\`, optionally copied to the jump box (`docs/RUNBOOK.md:118#opt-in`).
3. The APIM legacy subscription key: APIM and the `mcp-legacy-key` connection.
4. The vendor key: Key Vault, the KV-backed named value, an ACA secret on the vendor app, and `.secrets\vendor-api-key.txt` (`infra/04-apps.bicep:37-38#ONE`).
5. The Application Insights connection string: an ACA secret on each MCP app, and Log Analytics shared keys that remain enabled (`DESIGN.md:238#connection`).
6. The jump box local account password: `.secrets\jumpbox.json`.

**Why.** App roles are assigned directly to users because group-based app-role assignment needs Entra ID P1 and the core demo is meant to run on a plain tenant (`README.md:144#P1`). Groups are still used where the platform supports them natively, for Azure RBAC and Cosmos data-plane roles. The jump-box package scan treats a staged file with any of these names as a blocked finding and stops with "Nothing was sent" (`scripts/jumpbox-console.ps1:243-259#$blockedName`, `scripts/jumpbox-console.ps1:334-337#Nothing`).

**Trade-off / limitation.** The Foundry connection copy of the `abw-agent-client` secret is the one place where a confidential credential sits inside a Microsoft-managed service for the whole life of the connection; Section 6.4 covers rotation. The persona caches are plaintext JSON under `.secrets\` (`console/personas.py:119-123#os.replace`), unlike the operator's Azure CLI cache, which uses encrypted persistence; a copy of that folder is a copy of five persona sessions until the refresh tokens lapse or are revoked.

### 6.2 Token inventory

**What this section proves.** There are fourteen distinct tokens or token-like credentials in the estate: seven working tokens in four families (T1; T2a and T2b; T3; T4a, T4b and T4c) that the diagrams draw as T1 to T4, and seven other credentials (C1 to C7). T2 and T4 without a letter mean any member of the family. Diagram 07 draws the four working tokens as T1 to T4 and shows the other credentials as cards without a tag; C1 to C7 are used only in this document. For each one the table names the issuer, the aud, the subject, the claims that matter, the lifetime, where it is held, who validates it and the code that handles it. Section 6.11 refers back to these identifiers (`src/mcp/abw_mcp/auth.py:108-170#verify_token`).

Diagram: docs/diagrams/07-token-anatomy.excalidraw

#### 6.2.1 The token table

Sources are tagged [L1]-[L13] and listed after the table.

| token | issued by | Audience (aud) | subject | key claims | lifetime / refresh | held by | validated by | code |
|---|---|---|---|---|---|---|---|---|
| T1 Front-door token | Entra, acquired by the Azure SDK from the caller's credential (the console uses the operator's Azure CLI cache) | `https://ai.azure.com` (the Foundry resource: Learn says the `AzureRbac` endpoint scheme accepts tokens for exactly this resource [L10]) | The signed-in user | `aud`, `iss` (v1 `https://sts.windows.net/<tenant-id>/` or v2), `tid`, `oid`; the policy reads the first of `upn`, `unique_name`, `preferred_username` | 60-90 minutes | The caller's credential object; forwarded unchanged to the Foundry endpoint | APIM `validate-jwt` (two issuers), then Foundry (Azure RBAC: the principal needs the `interact/action` permission that Foundry Agent Consumer includes [L10]) | `infra/apim/policies/agent-frontdoor.policy.xml:18-43#validate-jwt` |
| T2a User access token for an MCP API (direct and console path) | Entra v2 token endpoint, by silent redemption of the refresh token [L2] | The API app's client ID (a GUID) of `abw-mcp-<server>` (v2 `aud` is always the client ID [L3]); requested as scope `api://<client-id>/Tools.Read` | The user | `ver` 2.0, `iss` `https://login.microsoftonline.com/<tenant-id>/v2.0`, `tid`, `oid`, `scp` (`Tools.Read`, plus `Tools.Execute` for actions), `roles`, `azp`, `uti`, `exp`, `nbf`, `preferred_username` | Random 60-90 minutes [L1]; no CAE is built (the README says custom APIs cannot get it, not verified here); the console forces the first token per persona, server and scope to be fresh after it starts | The console process (and the MSAL cache); sent as the `Authorization` header to the gateway | APIM `validate-jwt`, then `verify_token` in the server | `console/personas.py:193-212#acquire_token_silent`, `src/mcp/abw_mcp/auth.py:108-170#verify_token` |
| T2b Foundry-held passthrough token | Entra v2 token endpoint, through the authorization-code flow that Foundry runs for a `mcp-<server>-oauth` connection with `abw-agent-client` and its secret [L8] | One API app per connection (v2 tokens are single-resource) | The user who consented | `azp` = the `abw-agent-client` app id, `scp` per the connection's scopes, `roles`, `oid`, `uti` | Entra lifetime 60-90 minutes. Foundry mints it at the first agent call after the previous one expired and reuses it for its whole life: measured from the MCP audit, token sets were each used for 39-51 minutes and a third set until it expired at about 73 and 90 minutes (`DESIGN.md:223-223#jti`). Renewed through the connection's refresh URL when `offline_access` was requested [L8] | Foundry Agent Service, one per user and per MCP server (`docs/RUNBOOK.md:49-49#jti`); not inspectable in this repo | APIM, then the server; not by Foundry | `scripts/foundry-connections.ps1:44-66#tokenUrl` |
| T3 UAMI federated assertion | The managed-identity token service that the Container Apps runtime exposes to the container (`IDENTITY_ENDPOINT`, asked for the resource `api://AzureADTokenExchange`) [L12] | `api://AzureADTokenExchange` | The UAMI (`sub` and `oid` are its principal id) | `iss` `https://login.microsoftonline.com/<tenant-id>/v2.0`, `aud`, `sub` | Set by the platform; the managed-identity back end caches per resource for about 24 hours and a token cannot be force-refreshed [L9] | The server process, in memory only; the callable `_get_client_assertion` fetches it each time MSAL asks for a client assertion | Entra at the OBO endpoint, against the federated identity credential | `src/mcp/abw_mcp/obo.py:77-79#_get_client_assertion` |
| T4a OBO access token for Storage | Entra v2 token endpoint, on-behalf-of | `https://storage.azure.com` (the resource decides the token version and the exact `aud` form; the server never decodes this token) | The same user (`oid`) | `scp` `user_impersonation`, `oid`, `tid`, `azp` or `appid` = the MCP app's own client id | 60-90 minutes; held in MSAL's in-memory cache; `expires_on` = now + `expires_in` | The server process (a static credential object); never returned to the caller | The Storage service: Entra authentication, then Azure RBAC | `src/mcp/abw_mcp/obo.py:39-79#OboBroker`, `src/mcp/abw_mcp/data.py:59-59#user_impersonation` |
| T4b OBO access token for Cosmos DB | As T4a | `https://cosmos.azure.com`; scope from `COSMOS_OBO_SCOPE` (default `https://cosmos.azure.com/user_impersonation`) | The same user | As T4a | As T4a | As T4a | Cosmos DB data-plane roles (not Azure RBAC) | `src/mcp/abw_mcp/config.py:154-155#cosmos_obo_scope` |
| T4c OBO access token for AI Search | As T4a | `https://search.azure.com` | The same user | As T4a | As T4a | As T4a | AI Search data-plane RBAC | `src/mcp/abw_mcp/data.py:84-84#user_impersonation` |
| C1 User ID token | The Entra v2 token endpoint, in the same response as the access token (MSAL always adds `openid`, `profile` and `email`, so an ID token comes back with every access token [L11]) | The client's own app id: `abw-test-client`, or the Azure CLI client for the operator [L4] | The user (`sub` is pairwise per app, `oid` is the stable id) | `iss`, `aud`, `tid`, `oid`, `preferred_username`, `amr` | ID tokens default to 1 hour [L1]; replaced when the refresh token is redeemed | The MSAL cache of the signing-in client | Nobody in ABW. The console reads `id_token_claims` once, to check which account signed in | `console/personas.py:280-286#id_token_claims` |
| C2 Refresh token | Entra, with the first sign-in (MSAL always requests `offline_access` [L11]) | None: bound to the user and the client, not to a resource or tenant [L2] | The user | Opaque | 90 days of inactivity by default and replaced on every use; the lifetimes of refresh and session tokens can no longer be configured [L1, L2] | `.secrets\msal-test-<id>.json` (console and CLI share it) or the Azure CLI cache | Entra only | `console/personas.py:108-123#_cache_path` |
| C3 `abw-agent-client` client credentials | Entra (`addPassword` on the app) | Not a token: a secret presented at the tenant token endpoint | The app `abw-agent-client` | Client id and secret; secret display name `foundry-connection` | 80 days; re-minted by re-running Phase 1 when the saved secret is missing, gone from the app or has fewer than 10 days left; the Foundry copy is only replaced by re-running `foundry-connections.ps1` | `.secrets\agent-client.json`; each `mcp-*-oauth` connection | Entra | `identity/Setup-Entra.ps1:158-169#addPassword` |
| C4 Device-code artefacts | Entra `devicecode` and `token` endpoints [L7] | Not JWTs: `device_code`, `user_code`, `verification_uri` | The person who enters the code | `expires_in` (15 minutes by default), `interval` | 15 minutes; the console can cancel by setting `expires_at` to 0 | The console process memory and the presenter's screen | Entra | `console/personas.py:241-260#initiate_device_flow` |
| C5 APIM subscription key | APIM (subscription `sub-abw-legacy-poc`) | Not a token: header `Ocp-Apim-Subscription-Key` | The subscription, no user | Opaque | No expiry is set on the subscription in Bicep; rotate by hand. It is scoped to the legacy API only | The `mcp-legacy-key` connection; the console (read through ARM) | APIM (`subscriptionRequired`) | `infra/05-apim-apis.bicep:169-193#subscriptionRequired`, `infra/05-apim-apis.bicep:204-213#allowTracing` |
| C6 Vendor key | `scripts/deploy.ps1` (generated once) | Not a token: header `x-vendor-key`, injected by APIM | The gateway | Opaque | No expiry; rotate by hand | Key Vault, APIM named value, vendor ACA secret | The vendor mock, constant-time compare | `src/mcp/abw_mcp/app.py:115-142#compare_digest` |
| C7 Deploy-time tokens | Entra. ARM and Graph tokens come from the Azure CLI; the agent scripts use `AzureCliCredential` for the Foundry project; azd signs in on its own or delegates to `az login` (not visible in this repo) | `https://management.azure.com`, `https://graph.microsoft.com`, and `https://ai.azure.com` for the Foundry project [L13] | The operator | Delegated tokens of the operator | 60-90 minutes; the Graph token is cached in the script process for 40 minutes | The script process | ARM, Graph, Foundry | `scripts/common.ps1:63-69#Get-GraphToken`, `src/agent/create_agents.py:34-34#AzureCliCredential` |

Learn sources for the table (all verified; [L1]-[L13]):

- [L1] Configurable token lifetimes: https://learn.microsoft.com/entra/identity-platform/configurable-token-lifetimes
- [L2] Refresh tokens: https://learn.microsoft.com/entra/identity-platform/refresh-tokens
- [L3] Access token claims reference: https://learn.microsoft.com/entra/identity-platform/access-token-claims-reference
- [L4] ID token claims reference: https://learn.microsoft.com/entra/identity-platform/id-token-claims-reference
- [L5] On-behalf-of flow: https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-on-behalf-of-flow
- [L6] Federated identity credential on an app, trusting a managed identity: https://learn.microsoft.com/entra/workload-id/workload-identity-federation-config-app-trust-managed-identity
- [L7] Device-code flow: https://learn.microsoft.com/entra/identity-platform/v2-oauth2-device-code
- [L8] Foundry MCP authentication: https://learn.microsoft.com/azure/foundry/agents/how-to/mcp-authentication
- [L9] Managed-identity token caching: https://learn.microsoft.com/entra/identity/managed-identities-azure-resources/managed-identity-best-practice-recommendations#limitation-of-using-managed-identities-for-authorization
- [L10] Agent endpoint authorization in Foundry (the `AzureRbac` scheme, token resource `https://ai.azure.com`, the `interact/action` permission, Foundry Agent Consumer): https://learn.microsoft.com/azure/foundry/agents/concepts/agent-endpoint-authorization
- [L11] MSAL always adds `openid`, `profile`, `email` and `offline_access`: https://learn.microsoft.com/security/zero-trust/develop/token-management#use-token-claims-in-your-apps
- [L12] Container Apps managed identity, token from `IDENTITY_ENDPOINT`: https://learn.microsoft.com/azure/container-apps/managed-identity#connect-to-azure-services-in-app-code
- [L13] Foundry tokens "must be issued with scope `https://ai.azure.com/.default`": https://learn.microsoft.com/azure/foundry/foundry-models/how-to/configure-entra-id#use-microsoft-entra-id-in-your-code

#### 6.2.2 Claims reference

**Implemented.** The two validators read the same claims but apply different rules; the table shows what each does with every claim that matters. APIM runs `validate-jwt` plus a deny expression (`infra/apim/policies/mcp-jwt.policy.xml:17-46#validate-jwt`); the server runs `verify_token` (`src/mcp/abw_mcp/auth.py:119-157#jwt.decode`).

| claim | what Entra puts there [L3] | APIM (`mcp-jwt.policy.xml`) | MCP server (`auth.py`) |
|---|---|---|---|
| `iss` | For v2 tokens `https://login.microsoftonline.com/<tenant-id>/v2.0` | `issuers` must contain exactly that URL | PyJWT `issuer=` exact match; failure is `bad_issuer` |
| `aud` | For v2 tokens always the API app's client ID (a GUID) | The policy's `audiences` list holds one GUID | PyJWT is given a list of two accepted values as `audience`, the GUID and `api://<client-id>`; failure is `bad_audience` (`src/mcp/abw_mcp/auth.py:131-132#bad_audience`) |
| `tid` | The tenant that issued the token | `required-claims` `tid` must equal the tenant id | Must equal `TENANT_ID`; failure is `bad_tenant` |
| `ver` | `1.0` or `2.0` | Not read (the v2 issuer match implies it) | Must be `2.0`; any other value is reported as `bad_issuer` |
| `exp`, `nbf` | Validity window | `require-expiration-time` true, `clock-skew` 60 s | `exp`, `nbf`, `iss`, `aud` required, `leeway` 60 s |
| `scp` | Space-separated delegated scopes; present in user tokens only | Must contain `Tools.Read` or the call is refused as `missing_scope` | Must contain `MCP_REQUIRED_SCOPE` (default `Tools.Read`); `Tools.Execute` is checked later, per tool |
| `roles` | The app roles assigned to the user on this API | At least one of the server's roles (except for discovery methods) | Sorted into `Caller.roles`; enforced per tool in the registry |
| `azp` | The client app that obtained the token (v2) | Must be in the named value `abw-allowed-azp` | Checked against `MCP_ALLOWED_AZP` only when that variable is non-empty |
| `oid` | The user's immutable object id | Deny list `abw-deny-oids`; rate-limit key | `Caller.oid`; a token with no `oid` is treated as app-only |
| `uti` / `jti` | A unique token id (`uti` is equivalent to `jti`) | Not used | `Caller.jti` = `uti` or `jti`; written into every audit event |
| `idtyp` | `app` for app-only tokens (an optional claim, emitted by default for app-only tokens) | Not read | `idtyp` equal to `app` is refused as `app_only` |
| `amr`, `acr` | How the user authenticated (for example `pwd`, `otp`, `mfa`) | Not read | Not read; proven by a search of `src` for `amr`, `acr`, `xms_cc` and claims-challenge handling that found none |
| `preferred_username` | A mutable display name | Copied to a header or variable at the front door only | Stored as `Caller.upn` for audit; never used for authorization |

Platform behaviour: `idtyp` is described at https://learn.microsoft.com/entra/identity-platform/optional-claims-reference#v10-and-v20-optional-claims-set. `uti` and `xms_cc` are described in [L3].

#### 6.2.3 Anatomy notes

- **v1 versus v2** (Platform behaviour, [L3]). Which version an API receives is set by the API app. ABW sets the manifest's access-token version to 2 on all five (`identity/Setup-Entra.ps1:129-130#oauth2PermissionScopes`), so `aud` is the client ID (a GUID) and the caller appears as `azp`. The `aud` of the Foundry data-plane token is not controlled by ABW, which is why the front-door policy accepts both the v1 and v2 issuers (`infra/apim/policies/agent-frontdoor.policy.xml:18-32#validate-jwt`).
- **`scp` versus `roles`.** The tokens here are delegated tokens, so both appear: `scp` is what the client app may ask the API to do on the user's behalf; `roles` is what the user holds on that API. An app-only token would have `roles` but no `scp`, which is why the server also refuses `idtyp = app` (`src/mcp/abw_mcp/auth.py:148-149#app_only`).
- **`oid`, `sub`, `uti`.** `oid` is the same in every app and is the join key for the kill switch and the audit; `sub` is pairwise per app and is not used. `uti` equals `jti` and is how one token is followed across Entra sign-in logs and the MCP audit (6.10).
- **No MFA evidence in the token path.** MFA is enforced when the token is issued, by whatever policy the tenant has. Neither validator reads `amr`, so a token minted through a weaker path would be accepted (Findings).
- **Tokens that are never validated in ABW code.** The ID token, the refresh token and the managed-identity assertion are consumed by Entra, not by any ABW service. The console decodes access tokens without verification for display only (`demo/mcpclient.py:51-59#claims`); that helper must never be used for a decision.

### 6.3 User sign-in

**What this section proves.** People reach the estate in three ways: a device-code sign-in in the console and CLI, an interactive browser sign-in in the portals, and (for the operator) the Azure CLI. MFA comes from the tenant, not from this repo, and exactly one Conditional Access policy is created by the repo, in report-only mode, never observed to evaluate (`scripts/extras-agent-identity.ps1:243-248#enabledForReportingButNotEnforced`).

#### 6.3.1 Device code in the console through abw-test-client

**Implemented.** The console signs a persona in once, then every job asks for tokens silently. Observed status: the console's persona sign-in is built but only partly observed; three of the five personas have not yet signed in through it, so what they see on a gateway beat is the designed result (`README.md:147-147#partly`, `DESIGN.md:241-241#designed`). The flow, in order:

1. The presenter presses Sign in for a persona. `start_login` reuses a pending flow if there is one, otherwise loads that persona's cache file (`console/personas.py:241-252#start_login`).
2. It calls `initiate_device_flow` with exactly one scope, `api://<client-id>/Tools.Read` of the research API (`console/personas.py:253-255#initiate_device_flow`). The other four APIs get their tokens later from the refresh token, which works because `abw-test-client` has tenant-wide consent (`consentType` `AllPrincipals`) for all five APIs (`identity/Setup-Entra.ps1:79-88#AllPrincipals`, `identity/Setup-Entra.ps1:180-185#Ensure-Grant`).
3. Platform behaviour [L7]: the client POSTs `client_id` and `scope` to the tenant's `devicecode` endpoint and receives `device_code`, `user_code`, `verification_uri`, `expires_in` (15 minutes by default), `interval` and `message`. MSAL then polls the token endpoint with `grant_type` set to `urn:ietf:params:oauth:grant-type:device_code`; the endpoint answers `authorization_pending` until the person finishes, and `expired_token` or `authorization_declined` otherwise.
4. The console shows `userCode`, `uri` and the seconds left (`console/personas.py:305-323#login_view`). A helper opens Edge or Chrome in a throwaway browser profile at the verification URL after checking that it is https on a Microsoft host, and copies the user code to the clipboard (`console/personas.py:554-583#user-data-dir`).
5. The presenter signs in as the persona: user name, password (copied by the console from `.secrets\personas.json`, never shown) and the six-digit code (6.3.4).
6. A worker thread blocks in `acquire_token_by_device_flow`; an expired code is mapped to a friendly "expired" state (`console/personas.py:263-279#acquire_token_by_device_flow`).
7. Before anything is saved, the worker compares `preferred_username` (or `upn`) of the ID token with the persona's expected user name and refuses a sign-in by a different account: "Nothing was saved" (`console/personas.py:280-286#preferred_username`). Only then is the cache written atomically with a temp file and `os.replace` (`console/personas.py:287-293#_atomic_write`).
8. From then on a job thread calls `token()`, which never prompts: it runs `acquire_token_silent` for the exact API scope with the stored account and raises `NeedsSignIn` if there is no account or the refresh token is gone (`console/personas.py:193-212#acquire_token_silent`).
9. The first token per persona, server and scope after the console starts is requested with `force_refresh=True`, which makes MSAL skip its access-token cache and redeem the refresh token, so role changes made since the last token are visible (`console/personas.py:193-212#force_refresh`). Platform behaviour: https://learn.microsoft.com/python/api/msal/msal.application.clientapplication?view=msal-py-latest describes `force_refresh` that way.

**Why.** Device code needs no redirect listener, so it works on the jump box as well as the laptop; the code can be typed in a private window while the console stays unattended. The wrong-account check exists because a presenter's own signed-in session in the same browser would otherwise silently become the persona. Nothing secret leaves the module except the one-time code the presenter asks for (`console/personas.py:1-12#abw-test-client`).

**Trade-off / limitation.** The CLI path in `src/agent/ask.py` signs personas in with the Azure CLI public client and a different cache file (`msal-<persona>.json`), while the console and `demo/mcpclient.py` use `abw-test-client` and `msal-test-<id>.json`, so a persona can hold two independent refresh tokens. Device code flow is also the flow Microsoft recommends blocking wherever possible: Conditional Access can target it with an authentication-flows condition, and a session that used it stays "protocol tracked" through later refreshes, so a tenant that adds such a block would also stop the console's silent token refresh with `AADSTS530036` (Platform behaviour: https://learn.microsoft.com/entra/identity/conditional-access/concept-authentication-flows). This repo configures no such policy.

#### 6.3.2 The operator: Azure CLI sign-in and the pre-authorized client

**Implemented and Configured.** The operator never uses `abw-test-client`. Every operator token comes from the Azure CLI's own MSAL cache.

- The five MCP API apps list the Azure CLI client as a pre-authorized application with all their delegated scopes, so no consent prompt appears (`identity/Setup-Entra.ps1:189-196#preAuthorizedApplications`).
- `admin_token` in `demo/mcpclient.py` opens the Azure CLI's MSAL cache file `.azure/msal_token_cache.bin` in the user profile through `build_encrypted_persistence` and `PersistedTokenCache` (inside `_az_cli_app`), and calls `acquire_token_silent` for `api://<client-id>/Tools.Read`; the console passes `force=True` for the first token per server and scope (`demo/mcpclient.py:62-85#admin_token`, `console/jobs.py:428-436#token_for`).
- On the jump box the first start runs `az login --tenant <tenant-id> --use-device-code`, after switching off the Windows broker (`core.enable_broker_on_windows=false`) because the console reads the Azure CLI cache, and then starts the console with `--skip-az-check` (`scripts/jumpbox-console-start.ps1:61-85#use-device-code`).
- Operator-as-persona ("Path B") exists because MFA blocks scripted persona sign-in: `identity/Use-AdminAsPersona.ps1` mirrors a persona's app roles and group memberships onto the signed-in operator (`identity/Use-AdminAsPersona.ps1:1-5#SYNOPSIS`), then the presenter waits about 40 seconds for the role claims to settle and requests a new operator token (`README.md:88-88#mirrors`, `docs/RUNBOOK.md:47-47#flip`).

Platform behaviour: `az login` opens a browser or the Windows broker and falls back to device code; `--use-device-code` forces it (https://learn.microsoft.com/cli/azure/authenticate-azure-cli-interactively). azd either signs in on its own or, with `azd config set auth.useAzCliAuth true`, delegates to `az login` (https://learn.microsoft.com/azure/developer/azure-developer-cli/use-terraform-for-azd#authenticate-to-azure). Which of the two the operator uses is not visible in this repo.

**Trade-off / limitation.** Agent beats always run as the operator, because only gateway-level beats can be switched to a persona (`console/jobs.py:420-420#PERSONA_KINDS`, `docs/RUNBOOK.md:45-45#operator`). Path B flips the gateway instantly but cannot flip the agent path, because Foundry holds its own token for the user and reuses it for its whole life (`docs/RUNBOOK.md:47-49#jti`).

#### 6.3.3 Interactive browser sign-in, and the console that has none

**Designed.** For the portals, ABW contains no sign-in code at all: a persona opens the Foundry portal or a consent link in a browser and the standard Entra sign-in page applies, with whatever MFA and Conditional Access the tenant enforces. The only repo-visible prerequisite is that every persona holds Foundry Agent Consumer on the project through the group `sg-abw-demo-all`, which lets a user interact with agents at runtime and nothing else (`infra/02-foundry-rbac.bicep:36-44#raConsumersProject`). The consent link is opened in a browser as the same user (`src/agent/ask.py:210-219#consent_link`).

**Implemented.** The console has no sign-in of its own. It binds to the loopback interface, accepts only `127.0.0.1` and `localhost` as `Host`, and refuses any state-changing request whose `Origin` is not its own `Host` (`console/server.py:284-298#SameOriginMiddleware`, `console/server.py:386-391#TrustedHostMiddleware`). Every token it uses comes from the operator's Azure CLI cache or from a persona's cache (`console/server.py:394-400#ensure_az_login`).

**Trade-off / limitation.** Any local process running as the same operating-system user can drive the console, including the kill switch. The guards defend against a web page in another origin, not against local code.

#### 6.3.4 MFA and the TOTP enrolment helper

**What the repo does about MFA.** Nothing enforces it. The demo tenant forces MFA for every user (Microsoft-managed Conditional Access, per `DESIGN.md:241#MFA`), which makes scripted password sign-in of a persona impossible until each persona has enrolled an authenticator once (`DESIGN.md:241-241#TOTP`, `README.md:51-51#authenticator`).

- **Enrolment.** A person enrols each persona by hand in the "different authenticator app" flow, which displays a base32 secret. `identity/Persona-Totp.py set <persona>` stores it in `.secrets\totp.json`, taking the secret as hidden input. `code` prints the current code and the seconds left, and `watch` keeps printing it; `login` prints the user name and copies the persona's password to the clipboard, and a detached PowerShell clears the clipboard after 60 seconds. It does not print a code. `selftest` runs the RFC 6238 test vectors (`identity/Persona-Totp.py:1-18#TOTP`, `identity/Persona-Totp.py:113-129#cmd_login`, `identity/Persona-Totp.py:138-144#cmd_selftest`).
- **The console does the same natively.** `totp` is RFC 6238 with HMAC-SHA1, a 30-second step and six digits. `set_totp` accepts a base32 key or an `otpauth://` link, rejects a value shorter than 10 characters or one for which it cannot compute a code ("does not look like an authenticator setup key"), and writes the same store atomically. `totp_now` returns the code and the seconds left (`console/personas.py:326-374#totp`). The clipboard helper can keep a copy out of clipboard history and the cloud clipboard (`console/personas.py:456-465#_clip_set`).
- **Platform behaviour.** Entra accepts software OATH TOTP (SHA-1, 30 or 60 second codes) from the Microsoft Authenticator app and other authenticator apps, and does not support HOTP (https://learn.microsoft.com/entra/identity/authentication/concept-authentication-oath-tokens).
- **ROPC cannot work here.** `demo/abw_tokens.py` signs personas in with the resource-owner password credentials grant (`demo/abw_tokens.py:28-34#acquire_token_by_username_password`). Platform behaviour: ROPC is not recommended and is incompatible with MFA (https://learn.microsoft.com/entra/identity-platform/v2-oauth-ropc). The helper is not imported by anything, and the jump-box package leaves it out (`scripts/jumpbox-console.ps1:148-149#imports`).

#### 6.3.5 Conditional Access: what the repo configures and what it does not

**Configured, not proven.** The table states exactly what exists.

| aspect | state in this repo | evidence |
|---|---|---|
| Policies created | One, by the optional extras script (not by the core deployment; `-SkipConditionalAccess` skips it); report-only | `scripts/extras-agent-identity.ps1:243-248#enabledForReportingButNotEnforced`, `scripts/extras-agent-identity.ps1:25-30#SkipConditionalAccess` |
| Who it covers | Members of `sg-abw-demo-all`; excludes the operator user, every directory role template whose name matches the privileged-role name pattern (a wildcard on the role-name suffix, see the cited line), and any group found by a search for `break`, `glass` or `emergency` | `scripts/extras-agent-identity.ps1:234-242#excludeRoles` |
| What it targets | The five MCP API apps, all client app types | `scripts/extras-agent-identity.ps1:246-246#includeApplications` |
| Grant control | Require MFA | `scripts/extras-agent-identity.ps1:247-247#builtInControls` |
| Safety | Other policies are listed and left untouched; `-Remove` refuses to delete a policy that is enabled | `scripts/extras-agent-identity.ps1:217-222#others` |
| Observed to evaluate | No: "no sign-in-log row references it yet" | `scripts/extras-agent-identity.ps1:354-360#notVerified` |

**Not configured by this repo.** An enforced Conditional Access policy; an authentication-flows condition that restricts device code flow; sign-in frequency or persistent-browser controls; token protection; authentication strength; device-compliance, location or named-location conditions; Identity Protection risk policies; Temporary Access Pass; sign-in-log export; any handling of claims challenges or CAE in code (`DESIGN.md:240#Configured`). The MFA that personas meet is the tenant's own.

Platform behaviour: report-only policies are evaluated at sign-in and their result appears on the Report-only tab of the sign-in log, without blocking anyone (https://learn.microsoft.com/entra/identity/conditional-access/concept-conditional-access-report-only). The policy targets the five MCP API apps and not Storage, Cosmos DB or AI Search. Conditional Access evaluates the resource being requested, so it should not fire on the downstream OBO exchanges (6.7); that is an inference from `includeApplications`, not something this repo tested.

**Why.** The policy is a reviewed starting point for an enforced rule, created in report-only mode so that it cannot lock out the demo. **Trade-off / limitation.** Until an enforced policy exists, MFA at the MCP boundary is whatever the tenant already enforces at sign-in.

### 6.4 Foundry OAuth identity passthrough

**What this section proves.** Foundry does not call the MCP servers as itself. Each of five OAuth connections makes Foundry run the authorization-code flow as `abw-agent-client`, store the user's resulting token, and present it to one MCP API as a bearer token. The agent definition attaches a connection to each tool by name (`src/agent/abw_agents.py:119-139#project_connection_id`).

#### 6.4.1 The project connections

**Configured.** `scripts/foundry-connections.ps1` creates one custom OAuth connection per MCP server, because Entra v2 tokens are single-resource, so each connection can carry exactly one resource (`scripts/foundry-connections.ps1:1-12#single-resource`).

| connection | target Foundry calls | auth type | scopes requested | notes |
|---|---|---|---|---|
| `mcp-research-oauth` | APIM gateway `/research/mcp` | oauth2 | `api://<client-id>/Tools.Read offline_access` | `<client-id>` is the research API app's application ID |
| `mcp-wall-oauth` | APIM gateway `/wall/mcp` | oauth2 | `api://<client-id>/Tools.Read offline_access` | `<client-id>` is the wall API app's application ID |
| `mcp-actions-oauth` | APIM gateway `/actions/mcp` | oauth2 | `Tools.Read` and `Tools.Execute` of the actions API, plus `offline_access` | the only connection with two scopes |
| `mcp-vendor-oauth` | APIM gateway `/vendor/mcp` | oauth2 | `Tools.Read` of the vendorgw API plus `offline_access` | the gateway then swaps in the vendor key |
| `mcp-private-oauth` | The private server's own Container Apps address `/mcp`, reached from the network-injected agent subnet (`DESIGN.md:151-151#subnet`) | oauth2 | `Tools.Read` of the private API plus `offline_access` | bypasses APIM (kill switch and allow-list do not apply); the target is `apps.json`, not the gateway (`scripts/foundry-connections.ps1:64-64#mcp-private-oauth`) |
| `mcp-legacy-key` | APIM gateway `/legacy/mcp` | `custom-keys` | none | the custom key `Ocp-Apim-Subscription-Key` (azd option `--custom-key`); no user identity |

Source: `scripts/foundry-connections.ps1:59-66#mcp-actions-oauth`. Fields shared by the five OAuth connections:

- **Client ID:** the `abw-agent-client` app ID, read from `entra.json` (`$ent.clients.agent.appId`), the state file that `identity/Setup-Entra.ps1` writes (`scripts/foundry-connections.ps1:39-39#entra.json`, `scripts/foundry-connections.ps1:88-89#appId`). Both clients have tenant-wide consent on all five MCP APIs (`identity/Setup-Entra.ps1:180-185#Ensure-Grant`).
- **Authorization URL:** `https://login.microsoftonline.com/<tenant-id>/oauth2/v2.0/authorize`. **Token URL and refresh URL:** both `https://login.microsoftonline.com/<tenant-id>/oauth2/v2.0/token` (`scripts/foundry-connections.ps1:50-51#authUrl`, `scripts/foundry-connections.ps1:85-89#tokenUrl`).
- **Scope string:** each scope is `api://<client-id>/<scope>`, joined with a space, plus `offline_access`. The comment explains why the array is forced: without it PowerShell concatenated a single scope with `offline_access` and Entra answered AADSTS650053 (`scripts/foundry-connections.ps1:54-57#Get-Scope`).
- **Where the secret is kept.** `identity/Setup-Entra.ps1` mints it as an 80-day password credential named `foundry-connection` and saves it to `.secrets\agent-client.json`; it keeps the saved one only while the same app still holds that key with more than 10 days left, and mints a new one otherwise (`identity/Setup-Entra.ps1:158-169#addPassword`). `foundry-connections.ps1` reads that file and passes the secret to `azd ai connection create` with `--client-secret` (together with `--auth-type oauth2`, `--client-id`, `--authorization-url`, `--token-url`, `--refresh-url` and `--scopes`), so Foundry stores it in the connection (`scripts/foundry-connections.ps1:47-48#agentSecret`, `scripts/foundry-connections.ps1:85-89#agentSecret`). A re-minted secret does not reach an existing connection by itself, because the script skips a connection that exists unless `-Force` or `-Only` names it (`scripts/foundry-connections.ps1:80-82#Force`). The script scrubs the secret from any error text it throws, but it is on the azd command line for the duration of each call (Findings).
- **Redirect URLs.** Foundry returns one redirect URL per connection after creation. The script collects them and runs `Setup-Entra.ps1 -Phase 2 -AgentClientRedirectUris` to register them on `abw-agent-client`, because the code flow fails unless the redirect URI is known to Entra; `-SkipEntraRedirects` skips this step (`scripts/foundry-connections.ps1:119-123#AgentClientRedirectUris`).
- **The legacy key.** For `mcp-legacy-key` the script reads the APIM subscription key with ARM `listSecrets` and stores it as a custom key header (`scripts/foundry-connections.ps1:91-95#legacyKey`).

Platform behaviour [L8]: the custom OAuth connection fields are Client ID (required), Client secret (optional), Authorization URL, Refresh URL, Token URL and Scopes, and Foundry returns a redirect URL that must be added to the OAuth app. `offline_access` is highly recommended. "Your session has expired. Please reauthenticate with the provided url." means an invalid refresh token or refresh URL.

**Why one connection per server.** A v2 access token has exactly one `aud`, so a single connection cannot cover five APIs. It also keeps consent and revocation per tool. **Trade-off / limitation.** Five connections mean five consents per persona and five tokens that Foundry must refresh.

#### 6.4.2 The consent flow

**Implemented (client side) and Platform behaviour (Foundry side).**

1. The first agent call by a persona for a tool whose connection has no stored token returns, in the response output, an item of type `oauth_consent_request` with a `consent_link` and the tool's `server_label`. The code's own message is that Foundry surfaces one consent at a time: when a label that was shown earlier is missing from a later pass, `ask.py` prints "not pending in this pass (Foundry surfaces one consent at a time)" (`src/agent/ask.py:203-209#oauth_consent_request`).
2. For each consent item whose label has not been shown yet, or was shown more than `--reopen` seconds ago (default 240), `ask.py` prints the link, or opens it with `webbrowser.open` when `--open-consent` is set (`src/agent/ask.py:210-219#consent_link`). It stops with exit code 3 when `--no-wait` is set, when there is no terminal and no `--open-consent`, or when the `--consent-timeout` deadline (default 600 seconds) has passed. Otherwise it sleeps `--poll` seconds (default 10) with `--open-consent`, or waits for Enter (`src/agent/ask.py:223-229#sys.stdin.isatty`, `src/agent/ask.py:154-158#consent-timeout`).
3. The same user opens the link. Foundry starts the authorization-code flow against the connection's authorization URL with `abw-agent-client`. The scopes already have tenant-wide consent for all users (`identity/Setup-Entra.ps1:180-185#Ensure-Grant`), so there is no per-user consent screen for the API scopes. What the Entra page shows beyond sign-in is platform behaviour not captured in this repo.
4. Entra redirects to the connection's registered redirect URL; Foundry redeems the code at the token URL with the client secret and stores the user's tokens. Platform behaviour [L8]: the Agent Service stores the user's credentials and uses them only when the agent talks to that MCP server, and the consent scope is per tool name per project. `DESIGN.md:155#consent` records one consent per OAuth connection, five in all.
5. The caller then submits another response. `ask.py` creates a fresh response from the prompt rather than continuing from `previous_response_id`; its comment says that continuing would replay the stale, empty tool lists (`src/agent/ask.py:230-232#previous_response_id`). Learn's documented pattern is to continue with `previous_response_id`; ABW deliberately does not.
6. From the next call on, Foundry lists the tools on the MCP server and calls `tools/call` with the stored token.

**Why.** Passthrough keeps the user's identity end to end, so the data plane can still say who asked. **Trade-off / limitation.** The consent surface is Foundry's and is not under the repo's control; a user who has not consented sees no tools for that server until they do.

#### 6.4.3 Where the user token is held, refresh and the stale-token caveat

**Designed and Platform behaviour.**

- **Where it is held.** In the Foundry Agent Service, per user and per connection [L8]. It is not visible to ABW code, and the repo cannot read, rotate or revoke it directly.
- **Refresh.** `offline_access` in the scope makes Entra return a refresh token; Foundry renews through the connection's refresh URL (`scripts/foundry-connections.ps1:85-89#tokenUrl`).
- **The stale-token caveat.** Foundry mints a user's token for a server at the first agent call after the previous one expired and then reuses it for its whole life. In the audit, token sets were each used for 39-51 minutes and a third set until it expired at about 73 and 90 minutes, against Entra lifetimes of 60-90 minutes (`DESIGN.md:223-223#jti`, `docs/RUNBOOK.md:49-49#jti`). A role change reaches the agent path only when the held token is replaced, so the APIM kill switch is the immediate lever (6.10). Path B (operator-as-persona) therefore flips gateway beats but not agent beats (`docs/RUNBOOK.md:47-49#jti`).
- **Consent order.** Apply the persona role baseline before the first agent consent: Foundry stores the token it receives at consent for its whole life, and a token that carries no roles leaves the agent with empty tool lists for 14-20 minutes or more after the roles are fixed, until it is replaced (`DESIGN.md:226-226#Consent`). The OAuth redirect URIs are likewise only known after the connections exist, so the Entra step that registers them runs after the connection script (`DESIGN.md:223-223#redirect`).

#### 6.4.4 Attaching a connection to an MCP tool

**Implemented.** The agent definition does not hold a token or a secret. It holds a pointer: the server URL, the name of a project connection, a tool allow-list and an approval rule.

| field | value for the governed agent | effect | source |
|---|---|---|---|
| `server_label` | The server key (`research`, `wall`, `actions`, `private`, `vendor`) | Names the tool for the model and for consent | `src/agent/abw_agents.py:129-138#server_label` |
| `server_url` | The gateway URL from the generated state, or the private server's ACA address | Where Foundry sends the MCP request | `src/agent/abw_agents.py:95-106#server_urls` |
| `project_connection_id` | `mcp-<server>-oauth` | Selects the stored credential. Platform behaviour [L8]: if the connection and `server_url` endpoints differ, the connection's endpoint is used | `src/agent/abw_agents.py:119-139#project_connection_id` |
| `allowed_tools` | A fixed list per server, for example research: `search_research`, `get_research_note` | Everything else the server exposes is invisible to the model | `src/agent/abw_agents.py:42-48#WALL_DESK_TOOLS` |
| `require_approval` | `never`, except the actions server: `always` for `place_order` only | The run pauses with an `mcp_approval_request` that the caller must answer | `src/agent/abw_agents.py:49-49#APPROVAL_REQUIRED`, `src/agent/abw_agents.py:123-128#MCPToolRequireApproval` |

The caller answers an approval request with an `mcp_approval_response` item and continues from `previous_response_id` (`src/agent/ask.py:233-243#mcp_approval_response`). Platform behaviour [L8]: when `require_approval` is not set the default is `always`.

**Contrast: the legacy agent.** `poc_tools()` attaches the single `legacy` tool to the connection `mcp-legacy-key`, sets no `allowed_tools` and `require_approval` to `never`, so every tool the legacy server exposes is callable under one shared key and no user identity (`src/agent/abw_agents.py:142-152#mcp-legacy-key`). That agent exists to show what the typical proof of concept looks like.

**Why.** The agent definition is safe to log and review because it holds only names: the credential lives in the project connection, not in the agent. **Trade-off / limitation.** The approval gate is enforced by the Foundry runtime, not by the MCP server; a caller that reaches the server directly with a valid token skips it (the server's own checks still apply).

### 6.5 APIM inbound authentication

**What this section proves.** Every call to a governed MCP API is authenticated at the gateway by one policy template, rendered once per server. The gateway has no credential to present to the backend and mints no token of its own: it checks that the caller's own Entra access token is genuine, addressed to this one API, issued by this tenant and still valid, and then forwards that same token. What the gateway decides from the claims afterwards (kill switch, client allow-list, scope, role) is authorization and is specified in section 7.3. This section covers the authentication half: the `validate-jwt` element, the 401 the gateway answers with, the anonymous discovery document, the legacy subscription-key path, and how the Authorization header and the request id travel (`infra/apim/policies/mcp-jwt.policy.xml:17-30#validate-jwt`).

Diagram: docs/diagrams/04-authentication-flow.excalidraw

#### 6.5.1 How one template becomes four APIs

**Configured.** `05-apim-apis.bicep` holds one array of four governed servers (research, wall, actions, vendor). For each it creates an API of type `mcp`, bound to its backend, with `subscriptionRequired: false`: the user's token is the credential, not an APIM subscription. The Bicep loads `mcp-jwt.policy.xml` as text, replaces the placeholders `__SERVER__`, `__PATH__`, `__AUDIENCE__`, `__ROLES_CS__`, `__LIST_OPEN__` and `__VENDOR_SECTION__`, and attaches the result at API scope. `__AUDIENCE__` becomes the application (client) ID of the API's own app registration, so each API accepts tokens minted for it and for no other API (`infra/05-apim-apis.bicep:123-147#mcpApis`, `infra/05-apim-apis.bicep:149-166#mcpPolicies`). The API object also sets empty `oAuth2AuthenticationSettings` and `openidAuthenticationSettings`, so APIM's built-in OAuth settings are not used and this policy is the only authenticator (`infra/05-apim-apis.bicep:141-144#oAuth2AuthenticationSettings`).

The policy reads four APIM named values that are defined once for the whole instance: `abw-tenant-id` and `abw-gateway-url` (fixed at deploy time) and `abw-allowed-azp` and `abw-deny-oids` (edited at runtime by scripts, section 7) (`infra/05-apim.bicep:179-218#abw-tenant-id`).

| API | path | token aud it accepts | what the backend receives | code |
|---|---|---|---|---|
| research | `/research` | the client ID of `abw-mcp-research` | the caller's token, unchanged (6.5.7) | `infra/05-apim-apis.bicep:28-73#research` |
| wall | `/wall` | the client ID of `abw-mcp-wall` | the caller's token, unchanged | `infra/05-apim-apis.bicep:28-73#wall` |
| actions | `/actions` | the client ID of `abw-mcp-actions` | the caller's token, unchanged | `infra/05-apim-apis.bicep:28-73#actions` |
| vendor | `/vendor` | the client ID of `abw-mcp-vendorgw` | no token: the vendor section deletes `Authorization` and sets `x-vendor-key` from a Key Vault backed named value | `infra/05-apim-apis.bicep:75-78#vendorSection` |
| legacy | `/legacy` | none: no `validate-jwt`; a subscription key identifies a subscription, not a person | nothing about the caller | `infra/05-apim-apis.bicep:169-193#legacyApi` |
| private | not behind the gateway | n/a: the server authenticates callers itself (6.6) | n/a | `src/agent/abw_agents.py:95-106#server_urls` |

**Why.** One template means one set of semantics: a reviewer reads the authentication rules once, and the per-server differences are only the placeholder values. The cost is that a role list or an aud change needs a redeploy of the Bicep, because the values are baked into the XML text.

#### 6.5.2 `validate-jwt`, attribute by attribute

**Configured.** The element sits at the top of the inbound section, after `<base />` (`infra/apim/policies/mcp-jwt.policy.xml:16-30#validate-jwt`). Learn lists each attribute with its default [L14]; the table puts the repo's value next to it.

| element or attribute | value in the repo | effect | default on Learn [L14] | code |
|---|---|---|---|---|
| `header-name` | `Authorization` | The token is read from this request header | none: one of `header-name`, `query-parameter-name` or `token-value` is required | `infra/apim/policies/mcp-jwt.policy.xml:17-17#header-name` |
| `require-scheme` | `Bearer` | The header value must start with the `Bearer` scheme (Learn: the scheme is ignored when a custom header name is used; here the header is `Authorization`, so it applies) | none | `infra/apim/policies/mcp-jwt.policy.xml:17-17#require-scheme` |
| `require-expiration-time` | `true` | A token with no `exp` claim is refused | true | `infra/apim/policies/mcp-jwt.policy.xml:17-17#require-expiration-time` |
| `require-signed-tokens` | `true` | An unsigned token is refused | true | `infra/apim/policies/mcp-jwt.policy.xml:17-17#require-signed-tokens` |
| `clock-skew` | `60` | Tolerated clock difference between Entra and the gateway, in seconds | 0 seconds | `infra/apim/policies/mcp-jwt.policy.xml:17-17#clock-skew` |
| `failed-validation-httpcode` | `401` | Status returned for any validation failure | 401 | `infra/apim/policies/mcp-jwt.policy.xml:17-17#failed-validation-httpcode` |
| `failed-validation-error-message` | `Unauthorized` | Body text for a failure; in practice replaced by the `on-error` response (6.5.4) | depends on the failure, for example "JWT not present." | `infra/apim/policies/mcp-jwt.policy.xml:17-17#failed-validation-error-message` |
| `output-token-variable-name` | `jwt` | The validated token is kept as a `Jwt` object in the context variable `jwt`; the next element reads its claims | none | `infra/apim/policies/mcp-jwt.policy.xml:17-17#output-token-variable-name` |
| `openid-config` | `https://login.microsoftonline.com/{{abw-tenant-id}}/v2.0/.well-known/openid-configuration` | Source of the signing keys (the JWKS) for this one tenant's v2.0 endpoint | n/a. Learn: the configuration including the JWKS is pulled every 1 hour and cached; if the token's `kid` is not in the cache, or retrieval fails, APIM pulls at most once per 5 minutes; the intervals can change without notice | `infra/apim/policies/mcp-jwt.policy.xml:18-18#openid-config` |
| `audiences` | one `audience` entry, `__AUDIENCE__`, which Bicep replaces with the API's client ID (a GUID) | The `aud` claim must equal that GUID. A token minted for another MCP API, or one that uses the `api://` form, is refused | Learn: several values may be listed and are tried until one matches | `infra/apim/policies/mcp-jwt.policy.xml:19-21#__AUDIENCE__` |
| `issuers` | one `issuer` entry, `https://login.microsoftonline.com/{{abw-tenant-id}}/v2.0` | The `iss` claim must be exactly this tenant's v2 issuer. A v1 token (issuer `https://sts.windows.net/<tenant-id>/`) fails | same rule as `audiences` | `infra/apim/policies/mcp-jwt.policy.xml:22-24#issuer` |
| `required-claims` | claim `tid` must equal `{{abw-tenant-id}}`, `match="all"` | A further check on the tenant, made on the claim instead of the issuer URL | `match` defaults to `all` | `infra/apim/policies/mcp-jwt.policy.xml:25-29#required-claims` |

**Platform behaviour [L14].** The element only accepts the asymmetric algorithms PS256, RS256, RS512 and ES256 when keys come from an OpenID configuration endpoint; child elements and attributes are applied in the order of the policy statement. The page itself recommends `validate-azure-ad-token` for Entra tokens [L14, L15] (see 6.5.8).

**What it does not check.** `validate-jwt` reads no `azp`, `scp`, `roles`, `oid`, `ver`, `idtyp`, `amr` or `acr` claim. Everything beyond signature, issuer, aud, tenant, expiry and the scheme is done by the expression in the next element (6.5.3) and, independently, by the server (6.6).

**Why two tenant checks.** The issuer URL already embeds the tenant ID, and `tid` is the same ID as a claim. For a token that carries this tenant's issuer the two always agree, so the claim check is defence in depth; the repo does not say why it was added (inference).

#### 6.5.3 What the policy reads from the token after validation

**Implemented (policy expression).** A `set-variable` named `abw-deny` runs only after `validate-jwt` has succeeded, so every claim it reads is already known to be signed by the tenant and addressed to this API. It reads four claims and returns the first failing reason, or an empty string to allow. The decisions are explained in section 7.3; this table records only which claim feeds which test (`infra/apim/policies/mcp-jwt.policy.xml:31-46#abw-deny`).

| claim | how the expression reads it | test | reason string | code |
|---|---|---|---|---|
| `oid` | first value, or empty when absent | member of the comma-separated named value `abw-deny-oids` (the kill switch) | `revoked` | `infra/apim/policies/mcp-jwt.policy.xml:36-37#abw-deny-oids` |
| `azp` | first value, or empty | member of the named value `abw-allowed-azp` (the client allow-list) | `client_not_allowed` | `infra/apim/policies/mcp-jwt.policy.xml:35-38#abw-allowed-azp` |
| `scp` | all values joined with a space, then split on a space | contains `Tools.Read` | `missing_scope` | `infra/apim/policies/mcp-jwt.policy.xml:33-39#missing_scope` |
| `roles` | all values; together with the JSON-RPC `method` read from the request body | at least one of the server's roles, unless the call is a discovery method on a server with open discovery | `missing_role` | `infra/apim/policies/mcp-jwt.policy.xml:34-44#missing_role` |

Two facts matter for authentication. First, the policy adds no identity header for the backend: the only headers it sets are `x-abw-request-id` and `x-abw-gateway`, so the server learns who the caller is only by validating the token itself (`infra/apim/policies/mcp-jwt.policy.xml:82-87#x-abw-gateway`). Second, an app-only token has `roles` but no `scp`. If it is addressed to this API it passes `validate-jwt`, and then fails one of the next tests (`client_not_allowed` when the calling app is not on the list, otherwise `missing_scope`). Nothing in the policy names app-only tokens, so that block is implicit; the server blocks the same token explicitly as `app_only` (6.6).

#### 6.5.4 The 401: what a failed validation returns

**Configured.** Every failure of `validate-jwt` (no header, wrong scheme, bad signature, wrong aud, wrong issuer, wrong tenant, expired) ends in the same response. The policy's `on-error` section runs `<base />` and then, when the response status is 401, returns a fixed response (`infra/apim/policies/mcp-jwt.policy.xml:96-112#on-error`). On Learn, processing jumps to `on-error` as soon as an error occurs, and `on-error` may return a custom response [L27]. The response is:

```
HTTP/1.1 401 Unauthorized
WWW-Authenticate: Bearer error="invalid_token", resource_metadata="<gateway>/.well-known/oauth-protected-resource/<path>/mcp"
Content-Type: application/json

{"error":"unauthorized","server":"<server>","reason":"a valid Entra access token for this MCP server is required"}
```

| part | content | note |
|---|---|---|
| status | 401 | `failed-validation-httpcode` and the `on-error` test agree (`infra/apim/policies/mcp-jwt.policy.xml:99-101#return-response`) |
| `WWW-Authenticate` | scheme `Bearer`, `error="invalid_token"`, and the RFC 9728 parameter `resource_metadata`, which holds the URL of this API's protected-resource document, built from `abw-gateway-url` and the API path | no `realm`, no `error_description`, no `scope` (`infra/apim/policies/mcp-jwt.policy.xml:102-104#resource_metadata`) |
| body | fixed JSON naming the server | identical for every failure, so a caller cannot tell a wrong aud from an expired token (`infra/apim/policies/mcp-jwt.policy.xml:105-108#unauthorized`) |
| absent | any `x-abw-request-id`, in the header or the body | the id is set only for allowed calls (6.5.7), and the 403 carries it in the body only; a 401 leaves no id to quote |

**Platform behaviour [L16].** The MCP authorization specification requires every HTTP MCP server to serve a protected-resource document (RFC 9728) and to reference it from the `WWW-Authenticate` header of its 401 responses, so that a client with no token can discover the authorization server and the scope. This header is how the gateway meets that rule.

**Evidence, and what is not proven.** The repo commits no capture of the 401 itself (no header, no body). The scrubbed proof run records one line for it, `HTTP 401 BLOCKED a valid Entra access token for this MCP server is required`, for a call with no token (`demo/evidence-scrubbed/prove-20261022-172919.json:234-236#BLOCKED`), which shows the status and the policy's message but not the `WWW-Authenticate` value. Three places describe or probe the header. The portal tour tells the presenter that a failed `validate-jwt` returns a 401 with a `WWW-Authenticate` header that points at the discovery document (`docs/TALK-TRACK-PORTAL-TOUR.md:313-323#WWW-Authenticate`). A jump-box probe posts an `initialize` request with no token to the research API and records the HTTP status, whether the DNS answer is a private address, and whether the `WWW-Authenticate` value contains the RFC 9728 parameter (`scripts/jumpbox-console-setup.ps1:495-515#prmHeader`). The jump-box check passes when the answer is private and the status is 401; the header match is informational (`scripts/jumpbox-console.ps1:565-565#noToken`). So the status is checked and the exact bytes are the policy's intent, not an observed result.

**Two 401 shapes (Implemented and Platform behaviour).** The gateway's 401 is deliberately uniform. A 401 raised by the MCP server itself (6.6.4) has a different shape: `realm="abw"`, an `error_description` that carries the reason code, and a different protected-resource URL. That response reaches the caller unchanged, because the policy's `backend` section holds only `<base />` (`infra/apim/policies/mcp-jwt.policy.xml:90-92#backend`) and forwarding does not run `on-error` for a backend status unless `fail-on-error-status-code` is set to true; it defaults to false [L36]. This is an inference from the default forwarding behaviour; the repo does not exercise it.

#### 6.5.5 The protected-resource document (`prm.policy.xml`)

**Configured.** A separate API, `abw-mcp-prm-discovery`, has the path `.well-known/oauth-protected-resource`, `subscriptionRequired: false`, and one GET operation per governed server at `/<key>/mcp` (`infra/05-apim-apis.bicep:216-249#prmApi`). Its policy answers anonymously and statically: the first line of its comment says the document is public by design because clients need it before they have a token. The policy has no `<base />` in its inbound section, so it inherits nothing from outer scopes, including any rate limit (`infra/apim/policies/prm.policy.xml:5-25#return-response`).

| field | value | note |
|---|---|---|
| `resource` | `<gateway>/<path>/mcp`, the MCP endpoint URL on the gateway | not the app's `api://<client-id>` identifier (see the observation below) (`infra/apim/policies/prm.policy.xml:17-17#resource`) |
| `resource_name` | the server's display title | `infra/apim/policies/prm.policy.xml:18-18#resource_name` |
| `authorization_servers` | one entry, the tenant's v2.0 issuer URL | Learn requires the v2.0 issuer here [L16] (`infra/apim/policies/prm.policy.xml:19-19#authorization_servers`) |
| `bearer_methods_supported` | `["header"]` | the token goes in the Authorization header (`infra/apim/policies/prm.policy.xml:20-20#bearer_methods_supported`) |
| `scopes_supported` | `["api://<client-id>/Tools.Read"]` | only `Tools.Read`, even for actions, where `Tools.Execute` also exists (`infra/apim/policies/prm.policy.xml:21-21#scopes_supported`) |

The response is `200` with `Content-Type: application/json` and `Cache-Control: public, max-age=300` (`infra/apim/policies/prm.policy.xml:9-14#max-age`). The MCP server also serves its own document at `/.well-known/oauth-protected-resource`, unauthenticated, built from `PUBLIC_BASE_URL` (`src/mcp/abw_mcp/app.py:101-112#bearer_methods_supported`).

**Observation: resource versus identifier.** Learn says an MCP client sends the RFC 8707 `resource` parameter and Entra matches it exactly to an Application ID URI, and that a mismatch yields error AADSTS9010010 [L16]. The apps' identifier is `api://<client-id>` (`identity/Setup-Entra.ps1:133-133#identifierUris`), while the document names the gateway URL. A generic MCP client that follows the document literally would send the gateway URL and could meet that error. The repo does not exercise this: every ABW client asks for the scope by name (`api://<client-id>/Tools.Read`) and sends no `resource` parameter, and no code in `src`, `scripts` or `demo` fetches the document to drive a sign-in. The only reader of the 401 header is the jump-box probe. Not verified live.

#### 6.5.6 The legacy subscription-key path

**Configured.** `abw-mcp-legacy` is deliberately not behind Entra. The API sets `subscriptionRequired: true`, takes the key in the `Ocp-Apim-Subscription-Key` header or the `subscription-key` query parameter, and has the path `legacy` (`infra/05-apim-apis.bicep:169-193#legacyApi`). The subscription `sub-abw-legacy-poc` is scoped to this one API and has tracing disabled (`infra/05-apim-apis.bicep:204-213#allowTracing`). Learn lists the subscription-key header as one of the two inbound options for an MCP server behind APIM, the other being an Entra token validated by policy [L17].

The policy has `<base />`, a rate limit of 120 calls per 60 seconds keyed by the subscription ID (or the caller's address when no subscription is present), `x-abw-request-id` and `x-abw-gateway: apim-legacy`; it has no `validate-jwt` (`infra/apim/policies/mcp-legacy.policy.xml:6-15#rate-limit-by-key`). The gateway therefore authenticates a subscription, not a person: one key admits every caller, no user claim exists downstream, and the legacy container has no authentication middleware either (`src/mcp/abw_mcp/app.py:241-249#BearerAuthMiddleware`). The key is not in any file the demo ships: callers read it with the ARM `listSecrets` operation at demo time (`demo/mcpclient.py:160-161#listSecrets`, `scripts/foundry-connections.ps1:92-92#listSecrets`), and Foundry keeps a copy in the `mcp-legacy-key` connection (6.4).

**Why.** The path exists to show the "before" picture: a shared key, no identity, a broad server identity behind it (`infra/apim/policies/mcp-legacy.policy.xml:1-4#typical`).

#### 6.5.7 What happens to the Authorization header, and where the request id is born

**The Authorization header (Configured and Designed).** The standard policy never rewrites `Authorization`: its backend and outbound sections hold only `<base />`, and only the vendor section deletes the header (`infra/apim/policies/mcp-jwt.policy.xml:88-95#__VENDOR_SECTION__`, `infra/05-apim-apis.bicep:75-78#vendorSection`). The MCP API object sets no authentication override either. The design relies on the server receiving the user's own token: the server re-validates it and uses it as the OBO assertion (`DESIGN.md:32-32#hop`, `DESIGN.md:105-105#client_assertion`), and the information-barrier and entitlement-drift proofs only work if the user's token reaches the data plane (`DESIGN.md:205-205#barrier`, `DESIGN.md:218-218#drift`). Learn says request headers are forwarded to MCP tool invocations with certain exclusions, and describes forwarding `Authorization` explicitly with a required-header declaration plus an outbound `set-header`, or with the credential manager [L17]; it is silent on a pass-through backend such as this one. So the forwarding is demonstrated by the proofs and the design text, not by the policy text and not by a Learn statement.

**Where `x-abw-request-id` is created.** In the allowed branch only, after the 403 `choose` and the rate limit: `set-header` with `exists-action="override"` and the value `context.RequestId.ToString()` (`infra/apim/policies/mcp-jwt.policy.xml:82-84#x-abw-request-id`). `override` replaces any value a client sent under that name. On Learn, `context.RequestId` is a Guid described as the unique request identifier [L26]. The 403 body carries the same id (`infra/apim/policies/mcp-jwt.policy.xml:76-76#request_id`); the 401 carries none (6.5.4). The legacy policy sets the header the same way (`infra/apim/policies/mcp-legacy.policy.xml:9-11#x-abw-request-id`). On the server, the first present of `x-abw-request-id`, `x-request-id`, `x-ms-request-id` and `traceparent` becomes the request ID, else the server generates `req-` plus epoch milliseconds (`src/mcp/abw_mcp/auth.py:173-188#RequestContextMiddleware`). Where the id goes next is section 10.

#### 6.5.8 Why, and trade-offs

- **`validate-jwt` rather than `validate-azure-ad-token` (observation).** Learn recommends the Entra-specific policy for tokens issued by Entra [L14]; it takes a `tenant-id`, a list of acceptable client application IDs (`client-application-ids`), `backend-application-ids` and `audiences` [L15]. The repo does not say why it uses the generic policy. My reading is that the generic form keeps issuer, aud and tenant visible in one element and leaves the client allow-list in an expression that reads a runtime-editable named value, so a script can change it without a redeploy. That reading is mine, not the repo's.
- **Clock skew of 60 seconds.** The Learn default is 0 seconds. The repo sets 60, the same value as the server's `leeway`, so the two layers agree on the edge of expiry (`infra/apim/policies/mcp-jwt.policy.xml:17-17#clock-skew`, `src/mcp/abw_mcp/auth.py:126-127#leeway`). That agreement is an observation, not a stated aim.
- **Key freshness.** The gateway's key set follows the platform's cache rule (1 hour, and a refresh on an unknown `kid` at most once per 5 minutes) [L14]; the repo tunes nothing. A tenant key rollover is therefore picked up without a deploy [L28].
- **A public front door.** The gateway runs in external VNet mode with public network access enabled, so this policy is what stands between the internet and the backends (`infra/05-apim.bicep:47-62#publicNetworkAccess`). The README lists the gateway among the public surfaces that are documented and exempt (`README.md:146-146#gateway`).
- **List parsing differs between the layers (limitation).** The gateway splits `abw-allowed-azp` and `abw-deny-oids` with `Split(',')`, which does not trim, while the server's list parser trims each item (`infra/apim/policies/mcp-jwt.policy.xml:37-38#Split`, `src/mcp/abw_mcp/config.py:29-32#_parse_csv`). The deployment script joins the allow-list with a comma and no space (`scripts/deploy.ps1:178-180#Get-AllowedAzp`), so the default value is safe; a hand edit with a space after a comma would stop that entry from matching at the gateway only.

### 6.6 MCP server authentication

**What this section proves.** The MCP server does not trust the gateway. It validates the bearer token again with its own code, on every request, and builds the `Caller` that the registry, the audit and the OBO broker use. `verify_token` is the only place in `src` that decodes a JWT (`src/mcp/abw_mcp/auth.py:108-170#verify_token`). Section 7.4.1 records the decision order as a table of refusals; this section follows the code, the configuration and the failure shapes.

#### 6.6.1 What the server is configured with

**Configured.** The Bicep injects the authentication settings as environment variables, and `Settings.from_env` reads them once at start-up (`infra/04-apps.bicep:53-66#commonEnv`, `infra/04-apps.bicep:77-84#serverEnv`, `src/mcp/abw_mcp/config.py:87-158#from_env`). The server refuses to start when a required setting is missing.

| setting | set by | when unset | used for | code |
|---|---|---|---|---|
| `TENANT_ID` | `commonEnv` | required | the authority, the v2 issuer, the key-set URL and the `tid` check | `src/mcp/abw_mcp/config.py:61-71#jwks_url` |
| `MCP_APP_CLIENT_ID` | `serverEnv`, one value per server | required for every server except vendor and legacy | the two accepted `audience` values (the GUID and `api://<client-id>`), and the app identity for OBO (6.7) | `src/mcp/abw_mcp/config.py:73-75#mcp_app_client_id` |
| `MCP_ALLOWED_AZP` | `serverEnv`, from the deploy-time list of the agent client, the test client and the Azure CLI | empty list: the `azp` check is skipped | the client allow-list at the server | `src/mcp/abw_mcp/config.py:140-141#MCP_ALLOWED_AZP` |
| `MCP_REQUIRED_SCOPE` | `commonEnv` | `Tools.Read` | the scope that must be present in `scp` | `src/mcp/abw_mcp/config.py:140-141#MCP_REQUIRED_SCOPE` |
| `UAMI_CLIENT_ID` | `serverEnv`, and the legacy and vendor apps | required | selects the user-assigned identity that `ManagedIdentityCredential` uses: the OBO client assertion (6.7), the audit writes and any direct data access | `src/mcp/abw_mcp/obo.py:52-52#ManagedIdentityCredential` |
| `COSMOS_OBO` | `commonEnv`, from the `cosmosObo` deploy parameter | true | whether Cosmos calls carry the user's token (6.7.6) | `src/mcp/abw_mcp/config.py:154-154#cosmos_obo` |
| `COSMOS_OBO_SCOPE` | no Bicep or script sets it | `https://cosmos.azure.com/user_impersonation` | the Cosmos scope requested during OBO | `src/mcp/abw_mcp/config.py:155-155#cosmos_obo_scope` |
| `PUBLIC_BASE_URL` | `serverEnv`: the gateway path for research, wall and actions, the app's own address for private | derived from the forwarded host, protocol and prefix headers | the base of the protected-resource URL the server writes into its payload and its 401 header | `src/mcp/abw_mcp/app.py:91-98#derive_public_base_url` |
| `VENDOR_API_KEY` | an ACA secret on the vendor app | required for the vendor server | the constant-time vendor-key compare | `src/mcp/abw_mcp/app.py:115-142#compare_digest` |
| `STORAGE_ACCOUNT`, `SEARCH_ENDPOINT`, `SEARCH_INDEX`, `COSMOS_ENDPOINT`, `COSMOS_DATABASE` | `commonEnv` | per server, required where the server touches that store | the data-plane endpoints that the OBO tokens are presented to (6.8) | `src/mcp/abw_mcp/config.py:117-128#SEARCH_ENDPOINT` |
| `MCP_DENIAL_MODE`, `AUDIT_FAIL_CLOSED` | no Bicep or script sets them | `soft`, and false | how tool refusals are returned and what an audit failure does (section 7) | `src/mcp/abw_mcp/config.py:150-157#AUDIT_FAIL_CLOSED` |

#### 6.6.2 `verify_token`, step by step

**Implemented.** The middleware extracts the token and calls `verify_token`; each step below raises an `AuthError` with a reason code, and the first failure stops the request.

1. **Scope of the middleware.** Only the exact path `/mcp` is checked, for every HTTP method. Any other path (`/healthz`, the protected-resource document) passes straight through (`src/mcp/abw_mcp/auth.py:209-212#path`).
2. **Token extraction.** The value after a case-insensitive `bearer ` prefix is taken as the token, without trimming. A header with another scheme yields an empty token (`src/mcp/abw_mcp/auth.py:214-216#startswith`).
3. **Empty token.** An empty token fails as `missing_token` (`src/mcp/abw_mcp/auth.py:111-112#missing_token`).
4. **Header parse.** The unverified JOSE header is read to get the `kid`; a token that cannot be parsed fails as `bad_signature` (`src/mcp/abw_mcp/auth.py:113-116#get_unverified_header`).
5. **Signing key.** The key is fetched from the key-set cache by `kid` (6.6.3) (`src/mcp/abw_mcp/auth.py:119-119#get_key`).
6. **Decode and verify.** `jwt.decode` is called with `algorithms=["RS256"]` (no other algorithm is accepted, so an `alg: none` or a symmetric-key trick is refused), `audience` set to the two accepted values, `issuer` set to the exact v2 issuer, `leeway=60` (seconds), and the required claims `exp`, `nbf`, `iss` and `aud`. The two `audience` values are the app's client ID (the form a v2 token carries, [L3]) and `api://<client-id>` (`src/mcp/abw_mcp/auth.py:120-128#RS256`).
7. **Exception mapping.** An invalid signature maps to `bad_signature`, a wrong aud to `bad_audience`, a wrong issuer to `bad_issuer`, an expired token to `expired`, a token that is not yet valid to `not_yet_valid`. Any other exception from this block maps to `bad_signature` (`src/mcp/abw_mcp/auth.py:129-142#InvalidSignatureError`, `src/mcp/abw_mcp/auth.py:131-132#bad_audience`). That includes a key-set fetch failure, a missing required claim and a malformed payload (6.6.4).
8. **Version.** `ver` must be `2.0`; anything else, including a v1 token, is reported as `bad_issuer` (`src/mcp/abw_mcp/auth.py:144-145#ver`).
9. **Tenant.** `tid` must equal `TENANT_ID`, else `bad_tenant` (`src/mcp/abw_mcp/auth.py:146-147#tid`).
10. **User, not app.** A token whose `idtyp` is `app`, or that has no `oid`, fails as `app_only` (`src/mcp/abw_mcp/auth.py:148-149#idtyp`).
11. **Client.** When `MCP_ALLOWED_AZP` is non-empty, `azp` must be in it, else `bad_azp`. A token with no `azp` fails once the list is set; an unset or empty list skips the whole check (`src/mcp/abw_mcp/auth.py:151-153#mcp_allowed_azp`).
12. **Scope.** `scp` is split on a space; `MCP_REQUIRED_SCOPE` must be present, else `missing_scope` (`src/mcp/abw_mcp/auth.py:155-157#mcp_required_scope`).
13. **The caller.** A frozen `Caller` is built from `oid`, `preferred_username`, `tid`, the sorted unique `roles`, the scopes, `azp`, `aud`, the token's `uti` or `jti`, and the raw token. The token field is excluded from `repr`, so logging the object cannot leak it (`src/mcp/abw_mcp/auth.py:29-41#Caller`, `src/mcp/abw_mcp/auth.py:159-170#roles`).
14. **Publishing the caller.** The middleware stores the caller in a context variable for the duration of the request and resets it afterwards (`src/mcp/abw_mcp/auth.py:244-248#current_caller`). The registry, the audit and the OBO broker read it from there.

**Why each step.** Steps 6 to 7 are what Learn asks of any API that accepts Entra tokens: validate the signature, the issuer, the target API and the time window before trusting any claim [L29]. Steps 8 to 12 are the repo's own hardening on top: version, tenant, user-not-app, client and scope. Because the transport is stateless, a new MCP session is never established, so every JSON-RPC POST carries a token and is re-validated (`src/mcp/abw_mcp/app.py:210-215#stateless`).

#### 6.6.3 The signing-key cache

**Implemented.** `JwksCache` keeps one key set in memory with a time-to-live of 3600 seconds (`src/mcp/abw_mcp/auth.py:60-63#ttl_seconds`). The rules, in order:

1. A token with no `kid` fails as `bad_signature` (`src/mcp/abw_mcp/auth.py:69-72#get_key`).
2. A `kid` that is not in the cached set triggers one forced refresh; if it is still unknown, the token fails as `bad_signature` (`src/mcp/abw_mcp/auth.py:73-79#_refresh`).
3. A refresh downloads the tenant's key-set URL with a 10-second timeout and raises on a non-success status; the cached set is replaced only after a successful download (`src/mcp/abw_mcp/auth.py:86-89#_refresh`, `src/mcp/abw_mcp/auth.py:98-102#raise_for_status`).
4. A matching key is converted from JWK to an RSA public key (`src/mcp/abw_mcp/auth.py:91-96#from_jwk`).

**Platform behaviour [L28, L29].** The key-set URL is the tenant's `discovery/v2.0/keys` document (`src/mcp/abw_mcp/config.py:69-71#jwks_url`). Entra rotates its signing keys periodically, and Learn's guidance for validators is to cache keys by `kid`, to refresh on an unknown `kid`, and to expect keys to roll over without notice.

**Trade-off / limitation.** The cache never serves an expired set when a refresh fails (there is no stale-if-error). After one hour, if the key-set download fails, every request fails with the misleading reason `bad_signature` until the download works again (step 7 of 6.6.2). Learn's guidance is to keep keys for 24 hours and refresh hourly [L28], which would survive a longer outage. The same Entra egress is needed for OBO anyway, so an Entra outage stops the data path either way; the difference is only how the failure is labelled.

#### 6.6.4 Failure shapes on the wire

**Implemented.** One function builds every authentication refusal. `AuthError` carries the reason code, a status of 403 for `missing_scope` and `missing_role`, and 401 for all others, and an `error` value of `insufficient_scope` for 403 and `invalid_token` for 401 (`src/mcp/abw_mcp/auth.py:44-57#AuthError`). The middleware then writes the response (`src/mcp/abw_mcp/auth.py:250-260#_auth_error_response`):

| outcome | HTTP | `error` | `error_description` (reason code) | raised by |
|---|---|---|---|---|
| token not accepted | 401 | `invalid_token` | `missing_token`, `bad_signature`, `bad_audience`, `bad_issuer`, `expired`, `not_yet_valid`, `bad_tenant`, `app_only`, `bad_azp` | `verify_token` |
| scope missing | 403 | `insufficient_scope` | `missing_scope` | `verify_token` |
| role missing at the middleware | 403 | `insufficient_scope` | `missing_role` | only when an `authorization_check` is passed to the middleware; `app.py` never passes one, so the branch cannot fire (`src/mcp/abw_mcp/auth.py:220-223#authorization_check`) |

Every one of these carries a `WWW-Authenticate` header with `realm="abw"`, the `error`, the `error_description` and the protected-resource URL, and a JSON body of `error` and `error_description`. None carries an `x-abw-request-id` header. Each is also written to the audit log as an `auth_failed` event with no identity, because nothing is trusted yet (`src/mcp/abw_mcp/auth.py:224-242#auth_failed`; the event is described in 7.4.1).

**Catch-all (limitation).** `bad_signature` is also what any unlisted exception becomes. That covers a failed key-set download, a token with a missing required claim, a token whose `alg` is not RS256 and a malformed payload. A reader of the audit log should therefore treat `bad_signature` as "the token could not be verified", not as proof of tampering (`src/mcp/abw_mcp/auth.py:141-142#bad_signature`).

**Gateway 401 versus server 401.** The gateway answers with a fixed body and no reason (6.5.4); the server names the reason in `error_description`. Both name a protected-resource URL, but not the same one: the gateway publishes `<gateway>/.well-known/oauth-protected-resource/<path>/mcp`, while the server builds `<PUBLIC_BASE_URL>/.well-known/oauth-protected-resource`, which for research is `<gateway>/research/.well-known/oauth-protected-resource` (`src/mcp/abw_mcp/app.py:241-249#prm_url_builder`, `infra/05-apim-apis.bicep:251-258#prm`). Whether the gateway routes that second path to the container is not shown in the repo. A server-side 401 can reach a caller only when the gateway has accepted the token and the server has then refused it (for example `bad_azp` after the runtime allow-list changed but the deploy-time list did not), or on the private server, which has no gateway.

#### 6.6.5 Paths and servers with a different check

**Implemented.**

- **Unauthenticated routes.** `/healthz` and `/.well-known/oauth-protected-resource` are routed outside the `/mcp` check, so they answer without a token (`src/mcp/abw_mcp/app.py:224-228#healthz`).
- **The vendor server** has no Entra check. A `VendorKeyMiddleware` reads the `x-vendor-key` header, compares it in constant time, and answers `401 invalid_vendor_key` on a mismatch. It also logs whether an Authorization header arrived and whether a vendor key arrived, which is the observable check that the gateway removed the user's token (`src/mcp/abw_mcp/app.py:115-142#saw_authorization_header`).
- **The legacy server** installs no authentication middleware at all (`src/mcp/abw_mcp/app.py:241-249#BearerAuthMiddleware`).
- **DNS-rebinding protection** is switched off in the streamable-HTTP transport settings (`src/mcp/abw_mcp/app.py:210-215#enable_dns_rebinding_protection`). The app sits behind the gateway or inside the VNet; the repo does not state the reasoning.

#### 6.6.6 Why, and trade-offs

- **Why validate again.** The design says the server "never trusts the hop" (`DESIGN.md:32-32#hop`). The private server is reached directly and has no gateway at all (`DESIGN.md:107-107#kill`), and the registry needs a verified `Caller`, not a header it has to believe.
- **Hand-written claim checks.** PyJWT does the signature, aud, issuer and time work; the repo adds `tid`, `ver`, `idtyp`, `azp` and scope in its own code. Learn advises against writing token validation from scratch and recommends a maintained library or middleware [L16]. This is a deliberate trade for fine-grained reason codes, but it is code that must be kept correct (Findings).
- **Two audience forms.** The server accepts the GUID and `api://<client-id>`; the gateway accepts only the GUID. A v2 token always carries the GUID [L3], so the second form never occurs from Entra here and is harmless.
- **Failing open when unset.** An empty `MCP_ALLOWED_AZP` disables the server's client check, whereas the gateway refuses everything when its list is empty (`src/mcp/abw_mcp/auth.py:151-153#bad_azp`). Section 7.4.1 describes the two lists.

### 6.7 On-behalf-of with a federated managed identity

**What this section proves.** A server exchanges the caller's token (T2) for a token for one data store (T4a, T4b or T4c) and holds no secret to do it. The proof of identity in the exchange is a managed-identity token (T3) that Entra accepts because the MCP app registration carries a federated identity credential for exactly one managed identity. Two halves have to agree: the broker inside the server (`src/mcp/abw_mcp/obo.py:39-79#OboBroker`) and the trust that Phase 2 of the identity script creates (`identity/Setup-Entra.ps1:258-276#Invoke-Phase2`). The design states the chain in one line (`DESIGN.md:105-105#client_assertion`).

#### 6.7.1 The exchange, in order

**Implemented.** The steps follow one Blob read by the research server. The Cosmos path is identical from step 3 (`src/mcp/abw_mcp/data.py:177-189#get_credential`). Steps 5 to 7 are Platform behaviour [L5, L6]: they happen inside MSAL and Entra, which this repo does not contain.

1. **T2 is already in hand.** It sits in the frozen `Caller` that the middleware built after `verify_token` accepted it. The server's own aud check has therefore already shown that T2 was issued for this very app (6.6.2, step 6) (`src/mcp/abw_mcp/auth.py:29-41#Caller`).
2. **A tool asks the data layer for a document.** `read_blob_text` defaults to `use_user_token=True`, so it asks `_obo_credential` for a credential for the scope `https://storage.azure.com/user_impersonation` (`src/mcp/abw_mcp/data.py:57-62#read_blob_text`, `src/mcp/abw_mcp/data.py:191-194#_obo_credential`).
3. **The broker calls MSAL.** `get_credential` hands the raw T2 to MSAL as the user assertion, with the one scope in a list (`src/mcp/abw_mcp/obo.py:60-65#user_assertion`).
4. **MSAL asks for the client proof.** The confidential client was built with the MCP app's client ID and a `client_credential` dict whose `client_assertion` is a bound method. The method asks the managed-identity credential for a token for the resource `api://AzureADTokenExchange` and returns the raw string: that is T3 (`src/mcp/abw_mcp/obo.py:53-58#client_assertion`, `src/mcp/abw_mcp/obo.py:77-79#_get_client_assertion`). In Container Apps the credential reads the token from the local identity endpoint [L12], and the managed-identity back end caches tokens per resource [L9].
5. **MSAL posts to the tenant's v2 token endpoint** with the fields in 6.7.3 [L5].
6. **Entra decides**, with three independent checks:
   - T3 is compared with the federated identity credential on the MCP app: issuer, subject and `audiences` must match exactly [L6].
   - T2 must be a token issued to this app; a token issued to a different app cannot be redeemed [L5].
   - The requested delegated scope must already be consented for this app, because the flow has no interaction step [L5]. Phase 1 grants it tenant-wide (6.7.4).
7. **Entra answers** with `access_token`, `expires_in` and `ext_expires_in`, or with an `error` (6.7.7).
8. **`obo.py` shapes the result.** It adds `expires_on` (now plus `expires_in`, or 3600 when the field is absent) and wraps the token in a `StaticTokenCredential`. The token is never decoded or logged in this package (`src/mcp/abw_mcp/obo.py:69-75#expires_on`, `src/mcp/abw_mcp/obo.py:28-37#StaticTokenCredential`).
9. **A fresh SDK client is built** around that credential. Whatever scope the SDK asks for, `get_token` returns the same stored token, so the SDK never calls Entra itself (`src/mcp/abw_mcp/data.py:152-157#BlobServiceClient`, `src/mcp/abw_mcp/obo.py:35-36#get_token`). The SDK's own request pipeline is outside this repo.
10. **The store verifies T4a** (6.8).

**Why a managed identity and a federated credential.** The phase heading in the identity script calls the design "secretless OBO" (`identity/Setup-Entra.ps1:264-264#secretless`). The alternative is a client secret or certificate on each MCP app, which would be a long-lived credential in each container's configuration. Here the only long-lived artefact is the trust record in Entra; the proof is a short-lived token that the platform mints on demand for one identity (6.7.8).

#### 6.7.2 `obo.py`, element by element

**Implemented.** The module is 79 lines; this table covers all of it.

| element | what it does | code |
|---|---|---|
| imports | `msal` for the exchange, the managed-identity credential for the client proof, and the SDK's token types, so that a downstream client can be handed a ready token | `src/mcp/abw_mcp/obo.py:10-12#ManagedIdentityCredential` |
| `OboError` | A one-field exception: the Entra `error` string or a local code such as `missing_caller` | `src/mcp/abw_mcp/obo.py:20-25#OboError` |
| `StaticTokenCredential` | A slotted data class holding the token and its expiry; `get_token` ignores the scopes it is given and returns the stored token | `src/mcp/abw_mcp/obo.py:28-37#StaticTokenCredential` |
| constructor | Builds, once per process: an in-memory `SerializableTokenCache`, a `ManagedIdentityCredential` bound to the UAMI client ID, and a `ConfidentialClientApplication` for the MCP app with the tenant authority, that cache and the callable client assertion | `src/mcp/abw_mcp/obo.py:42-58#ConfidentialClientApplication` |
| `get_credential` | Acquire, then wrap the result in a static credential | `src/mcp/abw_mcp/obo.py:60-62#get_credential` |
| `acquire_token_on_behalf_of` | Calls MSAL with `user_assertion` set to the caller's raw token and the scope list. If the result has no `access_token`, raises `OboError` with the `error` string (or `unknown_error`). Otherwise returns the token, `expires_in`, `ext_expires_in` and a computed `expires_on` | `src/mcp/abw_mcp/obo.py:64-75#acquire_token_on_behalf_of` |
| `_get_client_assertion` | Gets a UAMI token for `api://AzureADTokenExchange/.default` and returns the string; takes any arguments; has no exception handling | `src/mcp/abw_mcp/obo.py:77-79#_get_client_assertion` |

**What leaves the module.** On success only the token and three numbers. The token is never decoded, so the module does not know the downstream aud or `exp` and relies on the `expires_in` field instead; `get_credential` does not read `ext_expires_in`. On failure only the `error` string survives: the description, any claims challenge and the correlation ID in MSAL's error result are discarded (`src/mcp/abw_mcp/obo.py:66-68#OboError`).

**One scope per call, no claims challenge.** The scope list always has one element, and `claims_challenge` is never passed to MSAL (`src/mcp/abw_mcp/obo.py:61-61#acquire_token_on_behalf_of`, `src/mcp/abw_mcp/obo.py:65-65#user_assertion`). A Conditional Access challenge during the exchange would therefore surface only as an error code (6.7.7).

**The callable assertion (not on Learn).** The MSAL Python reference documents a dict `{"client_assertion": "<a JWT>"}` for `client_credential` [L30]; it does not document a callable as the value. The repo passes a bound method. The live proofs that decide on the user's token (P03 and P16) pass through it, so the MSAL version in the deployed image evidently accepts it (`DESIGN.md:205-205#Information`, `DESIGN.md:218-218#Entitlement`). When MSAL calls the method, and whether MSAL caches the assertion it returns, are not shown in this repo, and an exception inside the method is not caught anywhere in the package (6.7.7). The project file pins only minimum versions, so a rebuild may take a newer MSAL (`src/mcp/pyproject.toml:10-26#msal`).

#### 6.7.3 The request, field by field

**Platform behaviour [L5, L6].** MSAL builds this request; the repo never sees it. The fields are the ones Learn lists for an OBO request that authenticates with a federated client assertion instead of a secret.

| field | value | where the value comes from |
|---|---|---|
| endpoint | `POST https://login.microsoftonline.com/<tenant-id>/oauth2/v2.0/token` | the authority built from `TENANT_ID` (`src/mcp/abw_mcp/config.py:61-63#authority`) |
| `client_id` | the MCP app's application (client) ID | `MCP_APP_CLIENT_ID` (`src/mcp/abw_mcp/config.py:73-75#mcp_app_client_id`) |
| `grant_type` | `urn:ietf:params:oauth:grant-type:jwt-bearer` | fixed by the protocol [L5] |
| `assertion` | T2, the caller's access token | `caller.token` (`src/mcp/abw_mcp/obo.py:65-65#user_assertion`) |
| `requested_token_use` | `on_behalf_of` | fixed by the protocol [L5] |
| `scope` | one delegated scope, for example `https://storage.azure.com/user_impersonation` | 6.7.4 |
| `client_assertion_type` | `urn:ietf:params:oauth:client-assertion-type:jwt-bearer` | sent in place of a client secret when a client assertion is used [L5] |
| `client_assertion` | T3, the UAMI token | `src/mcp/abw_mcp/obo.py:77-79#_get_client_assertion` |
| `client_secret` | not sent | the MCP apps have none (6.7.8) |

**What Entra compares.** T3 is accepted only if the federated identity credential on the app named by `client_id` matches it: T3's issuer against the credential's issuer (the tenant's v2 issuer URL), T3's subject against the credential's subject (the managed identity's principal ID, which Learn says is case-sensitive and must match exactly), and T3's aud against the credential's `audiences` (`api://AzureADTokenExchange`) [L6]. Each of the four apps has a credential for its own UAMI only, so the research server's managed-identity token cannot be used to act as the wall app, although both run the same image (`identity/Setup-Entra.ps1:266-275#principalId`).

**What comes back.** The version, issuer and aud form of the returned token are decided by the target resource, not by the MCP app: the setting that makes the MCP apps issue v2 tokens governs tokens issued for the MCP apps (T2), not tokens issued for Storage, Cosmos DB or Search (6.2.3) [L3]. That is why the server never inspects T4a, T4b or T4c.

#### 6.7.4 The scope per downstream resource

**Implemented.** The scope is a string literal in the data layer, except for Cosmos DB, which reads a setting. Each scope names the resource (which becomes the token's aud) and the delegated permission `user_impersonation`.

| store | scope string | set at | servers that use it | what Learn shows |
|---|---|---|---|---|
| Blob Storage | `https://storage.azure.com/user_impersonation` | `src/mcp/abw_mcp/data.py:59-59#user_impersonation` | research, wall | Storage exposes one delegation scope, `user_impersonation`, on the resource `https://storage.azure.com/` [L21, L31] |
| AI Search | `https://search.azure.com/user_impersonation` | `src/mcp/abw_mcp/data.py:84-84#user_impersonation` | research, wall | Learn shows the resource `https://search.azure.com/.default` [L34]; the identity script looks for a scope called `user_impersonation` on the Search service principal (`identity/Setup-Entra.ps1:96-97#user_impersonation`) |
| Cosmos DB | `COSMOS_OBO_SCOPE`, default `https://cosmos.azure.com/user_impersonation` | `src/mcp/abw_mcp/config.py:155-155#cosmos_obo_scope`, `src/mcp/abw_mcp/data.py:180-180#cosmos_obo_scope` | actions, private (every call site passes the same setting) | The Cosmos SDK sample on Learn uses `https://cosmos.azure.com/.default` [L25]; I did not find a Learn page that states whether the `user_impersonation` form is accepted. The live proof P04 places a clean order, which with the default switch writes with T4b (`DESIGN.md:206-206#Trading`) |

**Consent comes first.** The flow has no interaction step, so the MCP app must already hold consent for each downstream scope [L5]. Phase 1 does this per app. It lists the downstream resource in the app's `requiredResourceAccess` (type `Scope`) and creates a tenant-wide delegated grant (`consentType` `AllPrincipals`) for `user_impersonation` on the downstream first-party service principal; an existing grant whose scope differs is patched (`identity/Setup-Entra.ps1:79-88#AllPrincipals`, `identity/Setup-Entra.ps1:126-136#requiredResourceAccess`). The `$Apis` table fixes who gets which leg: research and wall get Storage and Search, actions and private get Cosmos DB, and the vendor gateway app gets none (`identity/Setup-Entra.ps1:29-46#$OboResources`). If a downstream service principal, or its `user_impersonation` scope, is missing from the tenant, the script warns and skips that leg instead of failing (`identity/Setup-Entra.ps1:90-100#Get-OboTargets`). The exchange for that store would then fail at run time (inference), which is why the error path in 6.7.7 matters.

#### 6.7.5 Caching, replicas and blocking

**Implemented.**

- **One in-memory cache per process.** The broker is created once per process and shares one `SerializableTokenCache` with its confidential client. The package never writes that cache out: the `serialize` calls in the repo belong to the user-side caches of the console, the demo client and the agent helper (`src/mcp/abw_mcp/obo.py:51-51#SerializableTokenCache`, `console/personas.py:162-162#serialize`, `demo/mcpclient.py:106-106#serialize`, `src/agent/ask.py:70-70#serialize`).
- **Per replica.** Every replica has its own process and so its own cache; nothing is shared. The apps run one to two replicas by default, in single-revision mode (`infra/modules/mcp-app.bicep:19-20#maxReplicas`, `infra/modules/mcp-app.bicep:38-38#activeRevisionsMode`).
- **What MSAL does with the cache.** The MSAL Python reference says that `acquire_token_for_client` looks in the cache first and that the token cache is in memory by default [L24, L30]; it does not say whether `acquire_token_on_behalf_of` is cache-first. The .NET documentation says that an OBO cache is keyed by the user assertion [L23]. Whether the Python library reuses an OBO token for the same user and scope is therefore not established by Learn, and the repo does not test it. The audit row records only that the OBO path was used, not whether the token came from the cache (`src/mcp/abw_mcp/audit.py:178-216#build_event`).
- **The managed-identity token.** The managed-identity back end caches tokens for about 24 hours per resource, and a token cannot be forced to refresh early [L9]. T3 is only the proof for the exchange, so its life does not bound the life of T4a.
- **A new SDK client for every call.** The Blob, Search and Cosmos clients are built inside each data call around a static credential that holds one token, so no SDK-level token cache exists that could go stale (`src/mcp/abw_mcp/data.py:63-63#_build_blob_service`, `src/mcp/abw_mcp/data.py:159-168#SearchClient`, `src/mcp/abw_mcp/data.py:183-189#CosmosClient`). The repo does not say why; the effect is that every call is bound to the current user's token and no client object can carry one user's token into another user's request. That reading is mine.
- **The credential is requested on the event loop.** The data methods are `async`, and the SDK calls inside them run in worker threads, but the credential is obtained by a plain synchronous call outside `asyncio.to_thread`. A call that needs a real exchange therefore blocks the server's event loop for the Entra round trip, plus a local identity-endpoint call when the managed-identity token is not cached. This is an observation from the code, not a measurement (`src/mcp/abw_mcp/data.py:57-65#read_blob_text`, `src/mcp/abw_mcp/data.py:180-180#get_credential`).

**Trade-off / limitation.** In-memory, per-replica caching means that a second replica repeats the exchange for the same user, and the blocking call shows up under load rather than in a functional test.

#### 6.7.6 The `cosmosObo` switch

**Configured.** One deploy parameter decides whether the actions and private servers call Cosmos DB with the user's token (T4b) or with their own managed identity. The wiring is: the deploy script reads `cosmosObo` from the deployment config and defaults it to true; `04-apps.bicep` declares the parameter (default true) and writes it into every server's environment variables as `COSMOS_OBO`; `Settings.from_env` parses it (default true) (`scripts/deploy.ps1:344-344#cosmosObo`, `infra/04-apps.bicep:30-30#cosmosObo`, `infra/04-apps.bicep:65-65#COSMOS_OBO`, `src/mcp/abw_mcp/config.py:154-154#cosmos_obo`).

| switch | credential for Cosmos DB calls | audit `obo` flag | code |
|---|---|---|---|
| on (default) | `OboBroker.get_credential` with the Cosmos scope, which is T4b, the user's token. It needs the caller and a broker, else the call raises `OboError` with `missing_caller` | true | `src/mcp/abw_mcp/data.py:177-180#missing_caller` |
| off | the server's own managed-identity credential | false | `src/mcp/abw_mcp/data.py:181-182#managed_identity_credential` |

**What the switch does not change.** The actions server reads the restricted list with its own identity whatever the switch says (`caller=None`, `use_user_token=False`). The platform template gives the actions managed identity a read role on that one container, and the people role assignments cover `orders` and `positions` only (`src/mcp/abw_mcp/servers/actions.py:30-37#use_user_token`, `infra/03-platform.bicep:604-615#cosmosActionsRestricted`). The legacy server never uses the user's token (`src/mcp/abw_mcp/servers/legacy.py:52-52#use_user_token`). The reads and writes of `orders` and `positions` follow the switch (`src/mcp/abw_mcp/servers/actions.py:91-98#use_user_token`, `src/mcp/abw_mcp/servers/actions.py:114-125#user_scope`, `src/mcp/abw_mcp/servers/private.py:19-45#cosmos_obo`).

**Intent.** The only statement of intent is one line in the server README: trading checks the restricted list with the compliance identity and then writes the order as the user, unless the switch is turned off explicitly (`src/mcp/README.md:128-128#COSMOS_OBO`). The repo gives no rationale for turning it off.

**Inference, not exercised.** The actions managed identity holds one Cosmos role, Cosmos DB Built-in Data Reader on the `restricted` collection, and the private managed identity holds none (`infra/03-platform.bicep:604-615#cosmosActionsRestricted`). With the switch off, those servers would present those identities to `orders` and `positions` and would probably be refused. No test or proof in the repo runs with the switch off, and I did not run one. Turning it off is therefore not a safe fallback; it selects a different security model that the role assignments do not support.

#### 6.7.7 Errors

**Implemented.** An OBO failure becomes a refusal, never a fallback to the server's own identity. The registry catches `OboError` around the tool handler and turns it into a tool error (`src/mcp/abw_mcp/registry.py:177-193#OboError`).

| failure | raised as | what the caller gets | audit row |
|---|---|---|---|
| a Cosmos call that asks for the user's token has no caller or no broker | `OboError` with `missing_caller` (`src/mcp/abw_mcp/data.py:177-179#missing_caller`) | FORBIDDEN, reason `obo_failed:missing_caller` | `tool_denied` |
| a Blob or Search call has no broker | `OboError` with `not_configured` (`src/mcp/abw_mcp/data.py:191-194#not_configured`) | FORBIDDEN, reason `obo_failed:not_configured` | `tool_denied` |
| Entra refuses the exchange (consent missing, T3 rejected, T2 not issued to this app, a challenge) | `OboError` carrying the `error` string from Entra, for example `interaction_required` for a challenge [L5] (`src/mcp/abw_mcp/obo.py:66-68#OboError`) | FORBIDDEN, reason `obo_failed:<error>` | `tool_denied` |

The first two rows are defensive paths: the research, wall, actions and private servers always have a broker and a caller on these calls, and the legacy and vendor servers never ask for the user's token (`src/mcp/abw_mcp/app.py:73-88#build_runtime`).

**Reading the audit.** `ToolError` defaults `obo` to true, and the OBO branch does not override it, so the audit row of an OBO denial says `obo: true` although no token was obtained. A denial that the registry raises before any handler runs (unknown tool, missing role or scope) takes the flag from the server type instead, true for every server except legacy and vendor, so it does not mean that a token was exchanged there either; an invalid-argument denial sets it false (`src/mcp/abw_mcp/registry.py:54-75#obo`, `src/mcp/abw_mcp/registry.py:222-236#obo`, `src/mcp/abw_mcp/registry.py:170-172#obo`). Read the flag together with the reason, never alone. In the default soft mode the refusal is a normal tool result with `decision` set to DENIED and the request ID, not an MCP error; strict mode sets `isError` (`src/mcp/abw_mcp/registry.py:263-270#isError`).

**What is not mapped.** The registry catches only `OboError` and `ToolError` around the handler. Failures that fall outside that net: an exception raised by the managed-identity credential or by MSAL instead of an error result, any Search error, and any Cosmos error other than a 404 on a read. None of them becomes a tool denial, and the registry writes no audit row for them. What the MCP framework returns for an unhandled exception is not shown in this repo (`src/mcp/abw_mcp/data.py:73-97#search_documents`, `src/mcp/abw_mcp/data.py:109-116#Exception`).

**Test.** `test_obo_failure_does_not_fallback` uses a fake broker that fails with `invalid_grant` and checks that the result is FORBIDDEN with the reason `obo_failed:invalid_grant`, and that the audit row carries the same reason (`src/mcp/tests/test_servers.py:140-156#test_obo_failure_does_not_fallback`). The code `invalid_grant` is the test's own choice; Learn's example for this flow is `interaction_required` [L5].

**The claims-challenge gap (limitation).** When Entra answers an OBO request with a claims challenge, Learn says the middle tier must hand the challenge back so that the client acquires a new token, and that the client must not retry with a cached one [L5]. This broker keeps only the error string and never passes `claims_challenge`, so it cannot relay a challenge: the user would see FORBIDDEN, not a prompt (`src/mcp/abw_mcp/obo.py:64-68#acquire_token_on_behalf_of`). No Conditional Access policy that blocks anything is configured in this repo (6.3.5), so the gap is latent rather than active.

#### 6.7.8 The Entra side, and why there is no secret

**Implemented.** Phase 1 of the identity script creates the apps and the consent. Phase 2 creates the federated credentials and can only run after the platform deployment, because the managed identities' principal IDs exist only then (`identity/Setup-Entra.ps1:258-276#Invoke-Phase2`).

| item | value | where |
|---|---|---|
| one API app per server | single-tenant, v2 access tokens, an `api://<client-id>` identifier URI | `identity/Setup-Entra.ps1:129-133#requestedAccessTokenVersion` |
| downstream consent | `requiredResourceAccess` plus a tenant-wide delegated grant per store | 6.7.4 |
| credential name | `uami-<key>` for the keys research, wall, actions and private | `identity/Setup-Entra.ps1:266-270#uami-` |
| issuer | `https://login.microsoftonline.com/<tenant-id>/v2.0` | `identity/Setup-Entra.ps1:264-265#issuer` |
| subject | the UAMI's principal (object) ID, read from the platform stage's output file | `identity/Setup-Entra.ps1:267-267#principalId` |
| `audiences` | `api://AzureADTokenExchange` | `identity/Setup-Entra.ps1:274-274#federatedIdentityCredentials` |
| description | `UAMI id-abw-mcp-<key>` | the same line |
| idempotence | same subject: skip. Different subject: delete, then create | `identity/Setup-Entra.ps1:271-273#existing` |
| not covered | the vendor and legacy apps, which do no OBO | `identity/Setup-Entra.ps1:266-266#research` |

**Platform behaviour [L6].** The credential's issuer must be exactly the tenant's v2 issuer URL (a leading or trailing space blocks the exchange). The subject is the case-sensitive principal ID of the managed identity, and the exchange is rejected unless it matches exactly. The `audiences` list must hold `api://AzureADTokenExchange` in the global cloud. Only user-assigned managed identities are supported. An app can hold up to 20 federated credentials, wildcards are not supported, and the credential name (3 to 120 characters) cannot be changed. This estate uses one credential per app.

**Why there is no secret on the MCP apps.** Phase 1 mints exactly one client secret, and it goes to the `abw-agent-client` app with an 80-day life; no API app is given one (`identity/Setup-Entra.ps1:165-169#addPassword`). The only secrets in the apps' configuration are the App Insights connection string and, on the vendor app, the vendor key; neither is an Entra credential (`infra/04-apps.bicep:53-66#commonEnv`, `infra/04-apps.bicep:77-84#serverEnv`). Rotation is therefore not a task for the MCP apps: the moving part is the managed identity's token, which the platform renews.

**Trade-off / limitation.**

- A federated credential binds one UAMI to one app. Rebuilding the platform stage creates new UAMIs with new principal IDs, so Phase 2 must run again; it handles this by deleting a credential whose subject differs and creating a new one (`identity/Setup-Entra.ps1:271-273#existing`). Until it has run, every exchange fails with an Entra error and the servers deny the calls (6.7.7).
- Trust is as narrow as the managed identity. Only the container app that the UAMI is assigned to can obtain a token as that UAMI (`infra/modules/mcp-app.bicep:28-33#userAssignedIdentities`), and T3 alone mints nothing: the exchange also needs a valid T2 issued to the MCP app [L5].
- The callable assertion is not documented for MSAL Python and the MSAL version is not pinned (6.7.2).

### 6.8 Data-plane authentication

**What this section proves.** The data stores authenticate and authorize the token they are given; they do not take the MCP server's word for who the user is. All three stores have key-based access switched off and public network access disabled, so an Entra token is the only way in, and the roles held by the user inside the token are the only thing that opens a door (`infra/03-platform.bicep:617-661#cosmosTradersOrders`, `src/mcp/abw_mcp/data.py:42-71#DataPlaneClients`). Which role may call which tool is layer 2 and is covered in section 7; this section covers how the stores verify the token, which identity each server presents, and what the caller sees when a store says no.

#### 6.8.1 What each store verifies

**Configured.** None of the three stores accepts a shared key, account key or API key, and none is reachable from the public internet, so the only credential they take is an Entra token (`infra/03-platform.bicep:130-143#allowSharedKeyAccess`, `infra/03-platform.bicep:225-231#disableLocalAuth`, `infra/03-platform.bicep:312-316#disableLocalAuth`). The network paths themselves are section 3.

| store | keys and SAS | resource the OBO token is for | how the store authorizes | evidence |
|---|---|---|---|---|
| Blob Storage | Shared Key access is off. The repo contains no code that creates a SAS (a search of `src`, `scripts`, `infra`, `identity` and `demo` found none) | `https://storage.azure.com` (T4a) | Entra authentication first, then Azure RBAC data roles such as Storage Blob Data Reader, assigned here at container scope [L21, L31, L33] | `infra/03-platform.bicep:130-143#allowSharedKeyAccess` |
| Cosmos DB | Local (key) authentication is off, so Entra ID is required [L19] | `https://cosmos.azure.com` (T4b) | The service's own data-plane roles, Cosmos DB Built-in Data Reader and Data Contributor, assigned here per collection; they are separate from Azure RBAC [L18, L19] | `infra/03-platform.bicep:225-231#disableLocalAuth` |
| AI Search | API-key authentication is off, so data requests that pass a key are refused [L22] | `https://search.azure.com` (T4c) | Azure RBAC data roles such as Search Index Data Reader [L35]; this repo assigns one, at service scope | `infra/03-platform.bicep:312-316#disableLocalAuth` |

**The role assignments that serve these tokens.** People get roles through Entra security groups; the servers' managed identities get only the few roles the table shows. Azure RBAC accepts security groups as principals [L38]. Cosmos DB role names are the built-in definitions that the template references.

| principal | role | scope | what it enables | code |
|---|---|---|---|---|
| research group | Storage Blob Data Reader | the `research-public` container | public research notes, read as the user | `infra/03-platform.bicep:618-626#raResearchBlob` |
| Falcon group | Storage Blob Data Reader | the `wall-falcon` container | Falcon deal documents, read as the user. A template comment says Orion has no assignee, so a Falcon user who asks for an Orion document is refused by Storage itself | `infra/03-platform.bicep:628-638#raFalconBlob` |
| research group | Search Index Data Reader | the Search service | searching the index, as the user | `infra/03-platform.bicep:640-648#raSearchResearch` |
| traders group | Cosmos DB Built-in Data Contributor | the `orders` collection | placing and listing orders as the user | `infra/03-platform.bicep:650-661#cosmosTradersOrders` |
| compliance group | Cosmos DB Built-in Data Reader | the `orders` collection | reading orders | `infra/03-platform.bicep:663-674#cosmosComplianceOrders` |
| traders and compliance groups | Cosmos DB Built-in Data Reader | the `positions` collection | positions and credit limits | `infra/03-platform.bicep:676-700#cosmosCompliancePositions` |
| actions server's UAMI | Cosmos DB Built-in Data Reader | the `restricted` collection | the restricted list, read as the service | `infra/03-platform.bicep:604-615#cosmosActionsRestricted` |
| every UAMI except the vendor's | Storage Blob Data Contributor | the `worm-audit` container | appending audit records | `infra/03-platform.bicep:548-556#raAuditAppend` |
| every UAMI | AcrPull | the container registry | pulling the server image | `infra/03-platform.bicep:537-545#raAcrPull` |
| vendor server's UAMI | Key Vault Secrets User | the Key Vault | reading the vendor key | `infra/03-platform.bicep:559-567#raVendorKv` |
| legacy server's UAMI | Storage Blob Data Reader, Search Index Data Reader, Cosmos DB Built-in Data Contributor | the whole account or service | broad on purpose: the keyed contrast server | `infra/03-platform.bicep:570-601#cosmosLegacyContrib` |

**No fallback.** The research, wall and private managed identities hold no role on any store of user data (their only data role is the audit append), and the actions identity can read only the restricted list. If the OBO exchange fails, nothing else would let those servers read the data, which is why a failed exchange is a refusal (6.7.7). The legacy identity is the deliberate exception.

#### 6.8.2 How `data.py` presents the token

**Implemented.**

- **Which credential.** The wrapper creates one managed-identity credential for the server's UAMI client ID when it is constructed. Each call then uses either a token from the broker (T4a, T4b or T4c, 6.7) or that managed-identity credential when the call is made with `use_user_token=False` (`src/mcp/abw_mcp/data.py:53-62#managed_identity_credential`).
- **A new client per call, holding one static token.** The Blob, Search and Cosmos clients are built inside each call (6.7.5). The static credential returns the stored token for whatever scope the SDK asks about, so the SDK never negotiates a token of its own. A token for the wrong resource would be caught only by the store, which is where that check belongs [L29]; nothing in the repo inspects the aud of T4a, T4b or T4c. The Search client is built with no Audience setting, although the SDK reference lists one for Entra authentication [L32]; the static credential ignores the scope that setting would imply, so the scope strings in 6.7.4 are the only place where the resource is chosen (`src/mcp/abw_mcp/data.py:152-168#_build_blob_service`, `src/mcp/abw_mcp/data.py:159-168#SearchClient`).
- **The request ID is stamped.** The ID that the gateway minted (6.5.7) and the middleware stored in a context variable is passed to Blob as the client request ID and to Search as the request ID, but only when it matches a safe pattern (letters, digits and a few punctuation characters, at most 64 characters). Storage rows can then be joined to the audit trail by that ID. Whether the Search log records it is not shown, because the evidence query matches Search and Cosmos DB rows to the MCP call by time (`observability/kql/AbwFullChainCore.kql:186-190#dataCalls`; 6.11.5). Cosmos DB calls carry no such ID (`src/mcp/abw_mcp/data.py:21-28#downstream_request_id`, `src/mcp/abw_mcp/data.py:200-217#client_request_id`).
- **Audit writes use the server's own identity.** Every server appends its audit events with its own managed identity, never with the user's token (`src/mcp/abw_mcp/audit.py:124-143#ManagedIdentityCredential`).

| server | Blob | Search | Cosmos DB | code |
|---|---|---|---|---|
| research | T4a, container `research-public` | T4c | none | `src/mcp/abw_mcp/servers/research.py:22-29#search_documents`, `src/mcp/abw_mcp/servers/research.py:47-55#read_blob_text` |
| wall | T4a, container `wall-<project>` | T4c | none | `src/mcp/abw_mcp/servers/wall.py:62-70#search_documents`, `src/mcp/abw_mcp/servers/wall.py:88-96#read_blob_text` |
| actions | none | none | `orders`: T4b when the switch is on; `restricted`: the server's identity, always | `src/mcp/abw_mcp/servers/actions.py:30-37#use_user_token`, `src/mcp/abw_mcp/servers/actions.py:91-98#use_user_token` |
| private | none | none | `positions` and credit limits: T4b when the switch is on | `src/mcp/abw_mcp/servers/private.py:19-28#cosmos_query_items`, `src/mcp/abw_mcp/servers/private.py:37-45#cosmos_read_item` |
| legacy | the server's own identity | the server's own identity | the server's own identity | `src/mcp/abw_mcp/servers/legacy.py:46-53#use_user_token` |
| vendor | none | none | none (synthetic data) | `src/mcp/abw_mcp/servers/vendor.py:30-59#obo=False` |

The vendor server still builds the audit sink, but its identity has no audit-append role (`infra/03-platform.bicep:548-556#raAuditAppend`), so its blob append would be refused by RBAC. That is an inference; the append runs on a worker thread whose failure is caught and printed, so the server would carry on without an audit blob (`src/mcp/abw_mcp/audit.py:94-103#Exception`).

#### 6.8.3 What the data plane evaluates

**Implemented, with one inference.**

- **The user, not the app.** T4a, T4b and T4c are delegated tokens for the user [L5], so a store applies the role assignments held by that person, directly or through a group. For user data the repo assigns roles to Entra security groups, not to the MCP apps (`infra/03-platform.bicep:617-626#raResearchBlob`); the apps' own roles are the audit append, the `restricted` list and the legacy server's broad roles (6.8.1, 6.9.1). The identity script creates the groups and places each persona in some of them: for example the Falcon persona is in the research and Falcon groups (`identity/Setup-Entra.ps1:48-60#sg-abw-research`). A person in the Falcon group is also in the research group, so can use Search and `research-public` too.
- **Two entitlement systems side by side.** App roles are assigned directly to users, because group-based app-role assignment needs Entra P1 (`identity/Setup-Entra.ps1:6-8#P1`). They travel in T2's `roles` and are decided by the gateway and the server (6.6). Groups drive the data plane and are decided by the store. The first can say yes while the second says no.
- **No group claim.** The identity script sets no group-membership claim on any API app, and a search of `identity`, `scripts`, `infra`, `src` and `demo` finds none (`identity/Setup-Entra.ps1:121-143#oauth2PermissionScopes`). The stores must therefore resolve group membership themselves when they receive a token. That reading is an inference from the missing claim plus the live proof below; this repo does not show how each store resolves membership.
- **Cosmos DB and groups.** The Cosmos DB RBAC pages that I read describe the principal only as an existing identity and do not state that a group is accepted [L19]. The repo's evidence is the design statement of layer 3 and the live proof P04, in which a clean order is written under a trader's token (`DESIGN.md:33-33#evaluated`, `DESIGN.md:206-206#Trading`).
- **Live proof of drift (P16).** The proof reads a Falcon document, removes the user from the Falcon group, polls the same tool until the data plane answers `storage_rbac_denied`, and checks that the app-role claim in the user's token is unchanged, so the gateway and the server would still have said yes. It restores the membership in a `finally` block (`demo/prove.py:962-985#p16`). The design records 5 to 44 seconds from group removal to the denial (`DESIGN.md:218-218#Entitlement`).
- **Search is coarse.** One role at service scope serves the whole research group (`infra/03-platform.bicep:640-648#raSearchResearch`). Search RBAC alone therefore cannot separate wall documents from public ones; the separation for Search lives in the tool's role check and query filter (section 7). I did not read the index definition and make no claim about it.

#### 6.8.4 What the caller sees when a store says no

**Implemented.** The wrapper maps a few downstream errors into `DataAccessError` and leaves the rest alone.

| condition | where it is raised | what the tool returns | audit event |
|---|---|---|---|
| the exchange fails | `OboError` (6.7.7) | FORBIDDEN, reason `obo_failed:<code>` | `tool_denied` |
| Storage answers 403 | `DataAccessError` with reason `storage_rbac_denied` (`src/mcp/abw_mcp/data.py:68-70#storage_rbac_denied`) | FORBIDDEN, "Storage access denied." | the wall server records `wall_violation_attempt` (`src/mcp/abw_mcp/servers/wall.py:94-96#wall_violation_attempt`); the research server records `tool_denied` (`src/mcp/abw_mcp/servers/research.py:54-55#DataAccessError`) |
| the blob does not exist | `DataAccessError` with reason `blob_not_found` (`src/mcp/abw_mcp/data.py:66-67#blob_not_found`) | NOT_FOUND | `tool_denied` |
| another Blob HTTP error | re-raised (`src/mcp/abw_mcp/data.py:71-71#raise`) | not mapped | none from the registry |
| any Search error | not mapped (`src/mcp/abw_mcp/data.py:73-97#search_documents`) | not mapped | none |
| a Cosmos DB read answers 404 | the read returns nothing (`src/mcp/abw_mcp/data.py:109-116#Exception`) | the tool decides; the credit-limit tool returns NOT_FOUND with reason `counterparty_not_found` (`src/mcp/abw_mcp/servers/private.py:46-47#counterparty_not_found`) | `tool_denied` |
| any other Cosmos DB error, a 403 included | re-raised, not mapped | not mapped | none |

The rows marked "not mapped" never reach the registry's denial path, so the registry writes no audit row for them, and this repo does not show what the MCP framework returns to the caller for an unhandled exception (6.7.7). I searched `demo/prove.py` and `src/mcp/tests` for a test or proof that provokes a Cosmos DB refusal and found none.

#### 6.8.5 Propagation, and the SAS footnote

**Propagation.** Learn says that Azure role-assignment changes can take up to 10 minutes to take effect and that a new token or a fresh sign-in forces it [L20, L33]. The measured time from group removal to the denial was 5 to 44 seconds (`DESIGN.md:218-218#Entitlement`). The two are not the same quantity: Learn's figure is for role-assignment changes, and the pages I read give no figure for group-membership changes. The measurement comes from one tenant and is not a guarantee. The README pairs it with the gateway kill switch, because the access token itself lives 60 to 90 minutes (`README.md:141-141#kill`, 6.10).

**The SAS footnote.** The README discloses that four SAS-signed storage requests in a seven-day log coincide with Defender for Storage onboarding: Azure itself called the service-properties operations from an Azure-internal address, with no caller identity and no blob read or written (`README.md:145-145#footnote`). Platform behaviour [L37]: once Shared Key access is disallowed, a Shared Key request fails with 403, a user-delegation SAS is still allowed, service and account SAS are refused, and the storage log does not distinguish the SAS types. A SAS-signed log row therefore does not by itself prove that a key was used. The "no key, no SAS of ours" claim rests on that reasoning, on the disabled-key settings above and on the absence of any SAS-creating code in the repo.

**Why.** If the data plane trusted the server's identity, every user would read what the server can read, and the wall would be only as strong as the code above it. Evaluating the user's token at each store makes the stores the last line of defence, independent of that code (`DESIGN.md:33-33#evaluated`).

**Trade-off / limitation.**

- Roles are granted to people, not to the MCP apps. A role therefore applies to any token for that person at that store, not only to the OBO token. The repo leans on the stores having no public network access to keep a person's own token from being used elsewhere (`infra/03-platform.bicep:225-231#publicNetworkAccess`). That follows from how RBAC works and is not exercised here.
- Cosmos DB roles are scoped to a collection. Per-user isolation inside `orders` is the tool's choice of partition key, not a role (`src/mcp/abw_mcp/servers/actions.py:113-127#partition_key`).
- A per-store refusal that is not mapped (Search, most Cosmos DB errors) is an unclassified failure for the caller and absent from the audit trail.

Learn sources added in 6.5-6.8 (all verified; [L14]-[L38]):

- [L14] APIM validate-jwt policy: https://learn.microsoft.com/azure/api-management/validate-jwt-policy
- [L15] APIM validate-azure-ad-token policy: https://learn.microsoft.com/azure/api-management/validate-azure-ad-token-policy
- [L16] Secure an MCP server with Microsoft Entra ID: https://learn.microsoft.com/entra/agent-id/secure-mcp-server-with-entra-id
- [L17] Secure access to MCP servers in API Management: https://learn.microsoft.com/azure/api-management/secure-mcp-servers
- [L18] Azure Cosmos DB data plane security reference: https://learn.microsoft.com/azure/cosmos-db/reference-data-plane-security
- [L19] Cosmos DB for NoSQL with role-based access control and Microsoft Entra ID, including turning key-based authentication off: https://learn.microsoft.com/azure/cosmos-db/how-to-connect-role-based-access-control
- [L20] Troubleshoot Azure RBAC, Azure role assignments (changes can take up to 10 minutes): https://learn.microsoft.com/azure/role-based-access-control/troubleshooting#azure-role-assignments
- [L21] Azure Storage REST API, authorize with Microsoft Entra ID and OAuth access tokens: https://learn.microsoft.com/rest/api/storageservices/authorize-with-azure-active-directory#use-oauth-access-tokens-for-authentication
- [L22] Azure AI Search, disable API key authentication: https://learn.microsoft.com/azure/search/search-security-enable-roles#disable-api-key-authentication
- [L23] MSAL.NET on-behalf-of flow (the OBO cache is keyed by the user assertion): https://learn.microsoft.com/entra/msal/dotnet/acquiring-tokens/web-apps-apis/on-behalf-of-flow
- [L24] MSAL Python client applications, caching: https://learn.microsoft.com/entra/msal/python/getting-started/client-applications#caching
- [L25] CosmosClient reference (@azure/cosmos), sample with the Cosmos DB scope: https://learn.microsoft.com/javascript/api/@azure/cosmos/cosmosclient?view=azure-node-latest
- [L26] APIM policy expressions, the context variable: https://learn.microsoft.com/azure/api-management/api-management-policy-expressions#context-variable
- [L27] APIM error handling in policies: https://learn.microsoft.com/azure/api-management/api-management-error-handling-policies
- [L28] Signing key rollover in the Microsoft identity platform: https://learn.microsoft.com/entra/identity-platform/signing-key-rollover
- [L29] Access tokens, validate tokens: https://learn.microsoft.com/entra/identity-platform/access-tokens#validate-tokens
- [L30] MSAL Python ConfidentialClientApplication reference: https://learn.microsoft.com/python/api/msal/msal.application.confidentialclientapplication?view=msal-py-latest
- [L31] Authorize access to blobs using Microsoft Entra ID: https://learn.microsoft.com/azure/storage/blobs/authorize-access-azure-active-directory
- [L32] SearchClient reference (azure-search-documents): https://learn.microsoft.com/python/api/azure-search-documents/azure.search.documents.searchclient?view=azure-python
- [L33] Assign an Azure role for access to blob data: https://learn.microsoft.com/azure/storage/blobs/assign-azure-role-data-access
- [L34] Azure AI Search query-time sensitivity labels (shows the Search token resource): https://learn.microsoft.com/azure/search/search-query-sensitivity-labels
- [L35] Azure AI Search role-based access control: https://learn.microsoft.com/azure/search/search-security-rbac
- [L36] APIM forward-request policy: https://learn.microsoft.com/azure/api-management/forward-request-policy
- [L37] Prevent Shared Key authorization for a storage account: https://learn.microsoft.com/azure/storage/common/shared-key-authorization-prevent
- [L38] Understand Azure role assignments (principals include security groups): https://learn.microsoft.com/azure/role-based-access-control/role-assignments

### 6.9 Service-to-service and platform identities

**What this section proves.** Beside the user's tokens the estate runs machine identities: Foundry's own, APIM's, six Container Apps identities, a seed identity and a jump box. This section states what each may do, shows that none of them stands on the user's token path, and then walks the one place where a user token meets a service the repo does not own: the APIM agent front door in front of the Foundry Responses endpoint (`infra/08-agent-frontdoor.bicep:49-62#abw-agent-frontdoor`). The credentials themselves were inventoried in 6.1; this section adds roles, scope and evidence and does not repeat them.

#### 6.9.1 What each platform identity may do

**Configured (Bicep and scripts).** Role names only; every role is an Azure built-in. The third column says whether the identity appears on the path of a governed `tools/call` (6.11).

| identity | roles and scope | on the user's token path | code |
|---|---|---|---|
| Foundry account, system-assigned | None granted by ABW. Key authentication is switched off. The Foundry template can give this identity a Key Vault role, but only when `enableKeyVault` is true, and the deploy script sets it to false | No | `infra/foundry/modules-network-secured/ai-account-identity.bicep:29-32#SystemAssigned`, `infra/foundry/modules-network-secured/ai-account-identity.bicep:52-52#disableLocalAuth`, `infra/foundry/main.bicep:326-327#enableKeyVault`, `scripts/deploy.ps1:265-267#enableKeyVault` |
| Foundry project, system-assigned | The roles in the next table, all on the stores that Foundry's own template creates for agent state. It holds no registry pull role, because `enableContainerRegistry` is false. Its three connections to those stores use Entra authentication (`authType: 'AAD'`); the Application Insights connection uses an API key | No. The MCP connections carry the user's token (6.4) | `infra/foundry/modules-network-secured/ai-project-identity.bicep:42-42#SystemAssigned`, `infra/foundry/modules-network-secured/ai-project-identity.bicep:49-89#authType`, `infra/foundry/modules-network-secured/application-insights.bicep:63-63#ApiKey`, `scripts/deploy.ps1:265-267#enableContainerRegistry` |
| Per-agent Entra identities (blueprint plus agent identity) | None by default. On Learn a new agent identity starts with no resource permissions and Foundry does not assign roles [L47]. The repo only records the identities (read-only) and adds no role to them | No. ABW uses OAuth identity passthrough, so the user's token goes to the tool. Disabling the agent's service principal did not stop an agent run (one observation) | `scripts/extras-agent-identity.ps1:10-12#blueprint`, `scripts/extras-agent-identity.ps1:130-130#shared`, `scripts/extras-agent-identity.ps1:343-348#identityLeverTest` |
| APIM, system-assigned | Key Vault Secrets User on the one Key Vault, to resolve the Key Vault-backed named value that holds the vendor key. No policy under `infra/apim/policies` contains `authentication-managed-identity`, so APIM never authenticates to a backend as itself | No. On the research, wall and actions legs it forwards the caller's token unchanged; on the vendor leg it removes it and sets the vendor key (C6) | `infra/05-apim.bicep:51-53#SystemAssigned`, `infra/05-apim.bicep:225-233#raApimKv`, `infra/05-apim-apis.bicep:81-91#secretIdentifier`, `infra/05-apim-apis.bicep:75-78#vendorSection` |
| API Center, system-assigned | API Management Service Reader at the APIM scope, so the catalog can read the gateway's API definitions | No (a catalog only) | `infra/05-apim.bicep:236-246#apic`, `infra/05-apim.bicep:267-275#raApicApim` |
| Agent 365 first-party service principal | One Azure role at the APIM scope, granted by a script that calls it the role-based-access half only. The tenant-level consent is a human step in the Microsoft 365 admin center and the role stays inert until a tenant admin enables the gateway setting. Recorded status: configured, not yet observed | No | `scripts/extras-agent-identity.ps1:13-16#Agent`, `scripts/extras-agent-identity.ps1:187-187#CONFIGURED-NOT-YET-OBSERVED`, `scripts/extras-agent-identity.ps1:202-205#humanStep` |
| Six Container Apps identities, one per MCP app | All six: AcrPull on the registry [L45]. All but the vendor: Storage Blob Data Contributor on the immutable audit container, for the append. Vendor: Key Vault Secrets User. Actions: Cosmos DB Built-in Data Reader on the `restricted` collection only. Legacy: Storage Blob Data Reader on the whole storage account, Search Index Data Reader, and Cosmos DB Built-in Data Contributor over the whole account ("broad on purpose", the "before" picture). Research, wall and private: nothing beyond the registry pull and the audit append | Only as the federated subject in the OBO exchange (6.7). The data they touch as themselves is the audit append, the `restricted` list and, for legacy, everything | `infra/03-platform.bicep:74-78#uamis`, `infra/03-platform.bicep:537-545#raAcrPull`, `infra/03-platform.bicep:548-556#raAuditAppend`, `infra/03-platform.bicep:559-567#raVendorKv`, `infra/03-platform.bicep:569-601#raLegacyBlob`, `infra/03-platform.bicep:603-615#cosmosActionsRestricted` |
| Seed identity | AcrPull; Storage Blob Data Contributor on the storage account; Search Service Contributor and Search Index Data Contributor on the search service; Cosmos DB Built-in Data Contributor over the whole account. The only identity that can write the synthetic blob and search corpus (the legacy server's identity can also write Cosmos DB, above) | No. A manually triggered job runs it inside the VNet and teardown removes it | `infra/04b-seed-job.bicep:3-8#intentionally`, `infra/04b-seed-job.bicep:51-99#raAcr`, `infra/04b-seed-job.bicep:101-110#seedJob` |
| Jump box | No managed identity (the VM resource has no identity block) and no public IP in the template. A local administrator whose password the deploy script generates and keeps outside the repo. A person signs in on it with a device code (6.3.2), so the tokens on the machine are the person's | No. It is a browser and console host inside the VNet | `infra/07-jumpbox.bicep:153-208#adminPassword`, `infra/07-jumpbox.bicep:14-17#Secrets`, `scripts/jumpbox.ps1:24-26#keyless` |
| Operator (a person) | Foundry User at the Foundry account scope; Key Vault Administrator on the Key Vault; AcrPush on the registry; Search Service Contributor on the search service. The template comment calls this control plane only; what it means is that the operator has no blob, index or document access (the Key Vault and registry roles are themselves data-plane roles on those two resources) | The operator's own `az` token is what the console runner presents to the front door (6.9.2) | `infra/02-foundry-rbac.bicep:26-34#roleFoundryUser`, `infra/03-platform.bicep:733-764#raOpKv` |
| Entra groups | `sg-abw-demo-all`: Foundry Agent Consumer at the Foundry project scope [L46]. Research group: Storage Blob Data Reader on `research-public` and Search Index Data Reader. Falcon group: Storage Blob Data Reader on `wall-falcon`. Traders and compliance groups: Cosmos DB roles on `orders` and `positions`. Infosec group: Reader, Log Analytics Reader and Monitoring Reader | Yes, as the person's entitlements: the data plane evaluates the user's token against these assignments (6.8) | `infra/02-foundry-rbac.bicep:36-44#raConsumersProject`, `infra/03-platform.bicep:617-648#raResearchBlob`, `infra/03-platform.bicep:702-731#raInfosecReader` |
| Deploy-time identities | The operator's Azure CLI sign-in (C7 in 6.2). The repo holds no deploy service principal and no stored deploy credential. How azd authenticates is not visible in this repo | No | `scripts/common.ps1:63-69#Get-GraphToken` |

**The Foundry project identity's roles on the Foundry-owned stores.** These are the standard roles of Foundry's network-secured agent template (the account module carries an "ABW patch" marker, the rest is the template). The stores they point at hold agent state and are separate from ABW's own Storage, Cosmos DB and AI Search.

| role | scope | code |
|---|---|---|
| Storage Blob Data Contributor | the Foundry-owned storage account | `infra/foundry/modules-network-secured/azure-storage-account-role-assignment.bicep:16-23#storageBlobDataContributor` |
| Cosmos DB Operator | the Foundry-owned Cosmos DB account (control plane) | `infra/foundry/modules-network-secured/cosmosdb-account-role-assignment.bicep:19-26#cosmosDBOperatorRoleAssignment` |
| Search Index Data Contributor and Search Service Contributor | the Foundry-owned search service | `infra/foundry/modules-network-secured/ai-search-role-assignments.bicep:20-28#searchIndexDataContributorAssignment`, `infra/foundry/modules-network-secured/ai-search-role-assignments.bicep:35-43#searchServiceContributorRoleAssignment` |
| Storage Blob Data Owner, with an ABAC condition | the project's containers | `infra/foundry/modules-network-secured/blob-storage-container-role-assignments.bicep:26-35#storageBlobDataOwnerAssignment` |
| A built-in Cosmos DB data-plane role (the template comment calls it the built-in data contributor) | the whole Foundry-owned Cosmos DB account | `infra/foundry/modules-network-secured/cosmos-container-role-assignments.bicep:24-32#sqlRoleAssignments` |
| Log Analytics Reader and Privileged Monitoring Data Reader | the Foundry-owned Application Insights | `infra/foundry/modules-network-secured/application-insights-role-assignment.bicep:25-33#appInsightsRoleAssignments` |

**Platform behaviour.** Three Learn facts bear on this table. A system-assigned identity is tied to the APIM service and is deleted with it, which is why a Key Vault with its firewall on can only be reached by APIM through that identity plus the trusted-services bypass [L43][L44]; the repo's Key Vault has default action Deny with the Azure-services bypass (`infra/03-platform.bicep:91-98#bypass`), which fits. The Container Apps image pull works because AcrPull is granted to the user-assigned identity named in the app's `registries` block, and the registry has to accept Azure Resource Manager audience tokens [L45]; each app declares that identity (`infra/modules/mcp-app.bicep:45-50#registries`). Finally, Learn's minimum role list for a Foundry project includes "Foundry User" for the project's managed identity on the Foundry resource [L46]; ABW's Bicep assigns Foundry User only to the operator, so whether Foundry grants the project identity that role implicitly is not shown in this repo.

**Why.** On the governed path no platform identity reads user data. The research, wall and private identities hold no role on any store of user data (their only data role is the audit append), so a stolen or buggy server credential cannot widen what a user may see: the data plane sees the person (6.8). The exceptions are visible and deliberate: the audit append, the `restricted` list that the actions server reads as the compliance system of record (`infra/03-platform.bicep:603-615#cosmosActionsRestricted`), the legacy server, and the seed job.

**Trade-off / limitation.** The legacy identity is over-privileged on purpose. The seed identity holds write roles and an account-wide Cosmos DB role until teardown. The Foundry project identity holds broad data roles on its own stores, which is the template's pattern and not ABW's choice. The vendor identity holds a Key Vault role, yet the vendor app receives the key as a literal container-app secret (Findings).

#### 6.9.2 The agent front door token path

**Configured and Implemented.** `infra/08-agent-frontdoor.bicep` publishes an API named `abw-agent-frontdoor` at the path `agents`. Its `serviceUrl` is the Foundry project endpoint, `subscriptionRequired` is false, and three operations (GET, POST, DELETE) each use the template `/*`, so every path under `/agents` is forwarded (`infra/08-agent-frontdoor.bicep:49-62#abw-agent-frontdoor`, `infra/08-agent-frontdoor.bicep:64-74#urlTemplate`). The policy file is loaded as text and attached to the API (`infra/08-agent-frontdoor.bicep:76-87#loadTextContent`). The base URL a client uses is the gateway URL plus `/agents/openai/v1` (`infra/08-agent-frontdoor.bicep:89-90#openAiBaseUrl`).

Diagram: docs/diagrams/11-agent-front-door.excalidraw

The diagram uses the same labels as this section: T1 is the user's Foundry token, T2 is the token Foundry sends to a tool (T2b here) and T4 is the data token (T4a here; T4b and T4c for Cosmos DB and Search). The table in 6.11.1 lists the labels side by side.

1. **The caller obtains T1.** The console runner builds its credential with `ask.build_credential(None)`, which returns the operator's own Azure CLI sign-in (`src/agent/ask.py:109-118#build_credential`, `console/agent_run.py:83-87#get_openai_client`). With a persona, `src/agent/ask.py` uses `PersonaCredential` instead: the Azure CLI public client with a per-persona refresh-token cache (6.3.2, `src/agent/ask.py:43-71#PersonaCredential`). The project SDK asks the credential for the Foundry data-plane scope, `https://ai.azure.com/.default` [L13], so T1 carries `aud` = `https://ai.azure.com` [L10]; the Act 7 probes use the same audience (`console/act7.py:38-39#AI_AUDIENCE`). The runner picks the path with `--via`: `apim` uses the front-door base URL saved by the deploy and `direct` uses the project endpoint. The console passes `apim` once the front door is deployed, and `direct` when the presenter has switched it off or when the agent is the legacy proof-of-concept agent; run by hand, the default is `direct` unless `ABW_AGENT_VIA` is set (`console/jobs.py:105-107#agent_via`, `console/jobs.py:719-721#legacy`, `console/agent_run.py:77-78#ABW_AGENT_VIA`). The Act 7 "agent path" step stores the choice (`console/act7.py:161-171#run_agentpath`).
2. **Arrival.** No subscription key is needed or read, so the bearer token is the only credential at this gateway (`infra/08-agent-frontdoor.bicep:56-56#subscriptionRequired`). The Act 7 console prints that fact from the live API object (`console/act7.py:176-178#subscriptionRequired`).
3. **`validate-jwt`.** The same element as the MCP gateway's (6.5.2) with the differences in the table below. A failure jumps to `on-error` and returns the 401 in the failure table (`infra/apim/policies/agent-frontdoor.policy.xml:18-32#validate-jwt`).
4. **Three variables.** `abw-oid` is the first `oid` value, or the string `unknown` when the claim is absent; `abw-upn` is the first of `upn`, `unique_name`, `preferred_username`; `abw-agent` is `agent_reference.name` read from the request body with `preserveContent: true` (so the body still reaches Foundry), or `n/a` (`infra/apim/policies/agent-frontdoor.policy.xml:33-50#abw-oid`).
5. **The kill switch.** `abw-deny` is `revoked` when the named value `abw-deny-oids`, split on commas, contains the `oid`. It is the same named value the MCP gateway reads (`infra/apim/policies/agent-frontdoor.policy.xml:51-55#abw-deny`, `infra/apim/policies/agent-frontdoor.policy.xml:2-9#kill`). `Split(',')` does not trim, so the value must be written without spaces; `scripts/kill-switch.ps1` writes it that way (6.10.2). The decision metric `abw-gateway-decisions` and a trace are emitted for allow and deny, and a denied call returns 403 `forbidden` (`infra/apim/policies/agent-frontdoor.policy.xml:56-70#abw-gateway-decisions`, `infra/apim/policies/agent-frontdoor.policy.xml:71-94#forbidden`). The switch runs before the rate limit and the budget, so a revoked user spends neither.
6. **Per-user rate limit.** `rate-limit-by-key` with `calls="{{abw-agent-rpm}}"` (60 by default) and `renewal-period="60"`, keyed by the `oid` (`infra/apim/policies/agent-frontdoor.policy.xml:95-95#rate-limit-by-key`). On Learn the policy returns 429 when the limit is exceeded, is not completely accurate, uses a sliding window of at most 300 seconds and counts per gateway [L42]. DESIGN.md says a lock-out lasts about two minutes (`DESIGN.md:174-174#lock-out`).
7. **Per-user token budget.** `llm-token-limit` keyed by the `oid`, with `token-quota="{{abw-agent-token-quota}}"` (250,000 by default), `token-quota-period="Hourly"` and `estimate-prompt-tokens="false"` (`infra/apim/policies/agent-frontdoor.policy.xml:96-96#llm-token-limit`, `infra/08-agent-frontdoor.bicep:17-21#tokenQuotaPerHour`). With estimation off the policy counts the `usage` that the backend returns, so the count is known only after the response and one call can overshoot; concurrent calls can briefly exceed the limit; the counter is per gateway; over the rate limit the caller gets 429 and over the quota 403 [L41]. The two response headers `x-abw-tokens-remaining` and `x-abw-tokens-consumed` carry the numbers back, and the console runner tallies them (`console/agent_run.py:90-105#tally`).
8. **Attribution.** `llm-emit-token-metric` in the namespace `abw-agent` records tokens with the dimensions `oid`, `upn` and `agent`, and the request id header is set from `context.RequestId` (`infra/apim/policies/agent-frontdoor.policy.xml:97-101#llm-emit-token-metric`, `infra/apim/policies/agent-frontdoor.policy.xml:102-104#x-abw-request-id`).
9. **Forward unchanged.** The backend section is `forward-request` with a 240-second timeout. No `set-header` touches `Authorization` and no `authentication-*` element appears in the policy, so T1 reaches Foundry as the caller sent it. The policy's own words: the user's token is forwarded UNCHANGED, and the gateway "never swaps the caller for a service identity" (`infra/apim/policies/agent-frontdoor.policy.xml:106-108#forward-request`, `infra/apim/policies/agent-frontdoor.policy.xml:10-12#UNCHANGED`).
10. **Foundry authorizes the person.** Learn: the agent endpoint authorization scheme defaults to Azure RBAC (alias `Entra`), the token must be for `https://ai.azure.com`, the caller needs the data action `Microsoft.CognitiveServices/accounts/AIServices/endpoints/interact/action`, and API keys are not supported [L10]. Learn lists Foundry Agent Consumer (least privilege) and Foundry User as the roles that allow interacting with agent endpoints [L46]. ABW gives the consumers group Foundry Agent Consumer at project scope and the operator Foundry User at account scope (`infra/02-foundry-rbac.bicep:36-44#raConsumersProject`, `infra/02-foundry-rbac.bicep:26-34#roleFoundryUser`). What Foundry returns to a caller with no such role is not captured in the repo.
11. **The tool leg uses T2b, not T1.** When the agent calls a tool, Foundry attaches the connection named in the tool definition, `mcp-<server>-oauth` (6.4, `src/agent/abw_agents.py:119-141#project_connection_id`), and sends the user's own token for that connection, T2b, as the bearer to the MCP API. T1 could not be replayed there: its `aud` is the Foundry data plane, while each MCP `validate-jwt` accepts only that API's own client ID (6.5.2). The two tokens never cross.
12. **Return path.** The outbound section re-sets `x-abw-request-id` and `x-abw-gateway: apim-agent-front-door` on every answer that passes through the policy (`infra/apim/policies/agent-frontdoor.policy.xml:109-117#x-abw-gateway`). The runner stores the request ids it sees (`console/agent_run.py:90-105#tally`).

**Platform behaviour [L14] and what differs.** The front door's `validate-jwt` is the MCP gateway's element with three changes:

| element | front door | MCP gateway (6.5.2) | code |
|---|---|---|---|
| `audiences` | `https://ai.azure.com`, the Foundry data plane | the API's own client ID (a GUID), one per API | `infra/apim/policies/agent-frontdoor.policy.xml:20-22#audience` |
| `issuers` | two: the v1 issuer `https://sts.windows.net/{{abw-tenant-id}}/` and the v2 issuer | the v2 issuer only | `infra/apim/policies/agent-frontdoor.policy.xml:23-26#issuer` |
| `required-claims` | `tid` equals the tenant ID, `match="all"` | the same | `infra/apim/policies/agent-frontdoor.policy.xml:27-31#required-claims` |
| all other attributes | `header-name`, `require-scheme`, `require-expiration-time`, `require-signed-tokens`, `clock-skew="60"`, 401 and `output-token-variable-name="jwt"` are identical | as listed in 6.5.2 | `infra/apim/policies/agent-frontdoor.policy.xml:18-18#clock-skew` |
| what happens after validation | only the kill switch, then rate and budget | tests `oid`, `azp`, `scp` and `roles` | `infra/apim/policies/agent-frontdoor.policy.xml:51-55#abw-deny` |

The repo does not say why both issuer forms are listed. The `ver` claim in a token states its version [L3] and the issuer form follows the version, so listing both keeps the gateway working whichever version the Foundry resource issues (inference).

**What the caller sees (Implemented).** Each row is a branch of the policy; the first two come from `validate-jwt` and the kill switch, the last two from `on-error`.

| answer | when | body `code` | headers | recorded as | code |
|---|---|---|---|---|---|
| 401 | `validate-jwt` fails: no token, bad signature, expired, wrong audience (an Azure Resource Manager token, say), wrong issuer or tenant | `unauthorized` | `x-abw-request-id` and `x-abw-gateway`; no `WWW-Authenticate` | No decision metric or trace, because both sit after `validate-jwt`; the gateway log outcome `unauthenticated` carries no reason | `infra/apim/policies/agent-frontdoor.policy.xml:121-141#unauthorized`, `docs/PROOF-PLAYBOOK.md:993-993#unauthenticated` |
| 403 | the `oid` is on `abw-deny-oids` | `forbidden`, with `reason` = `revoked` | the same two ids | decision metric `deny` and a trace | `infra/apim/policies/agent-frontdoor.policy.xml:71-94#forbidden` |
| 429 | more than the allowed calls per 60 seconds for this `oid` | `rate_limited`, with `retry_after_seconds` | `Retry-After` and the two ids | deny metric and trace written by `on-error` | `infra/apim/policies/agent-frontdoor.policy.xml:142-187#token_quota_exceeded` |
| 403 | the hourly token budget is used up | `token_quota_exceeded`, with `retry_after_seconds` | `Retry-After` and the two ids | the same | `infra/apim/policies/agent-frontdoor.policy.xml:142-187#token_quota_exceeded` |
| Foundry's own 4xx or 5xx | the caller holds no Foundry role, or the request is malformed | Foundry's body | Foundry's headers plus the two ids set by the outbound section (inferred) | not captured in the repo | `infra/apim/policies/agent-frontdoor.policy.xml:109-117#x-abw-gateway`, `console/act7.py:200-208#valid` |

The 401 is a different shape from the MCP gateway's: no `WWW-Authenticate` header, a body of the form `error.code`, `error.message` and `error.request_id`, and a request id that does exist (the MCP 401 carries none, 6.5.4). The message names the required audience, `https://ai.azure.com`.

#### 6.9.3 Front door versus calling Foundry directly

**Implemented, with an honest edge.** The front door controls only the callers who use it. Foundry's public network access is on in the deployed estate (`scripts/deploy.ps1:265-267#foundryPublicNetworkAccess`) and key authentication is off (`infra/foundry/modules-network-secured/ai-account-identity.bicep:52-52#disableLocalAuth`). So a bare call to the project endpoint is refused by Foundry itself, but a valid Foundry-audience token for a user who holds a Foundry role is answered directly, with no kill switch, no rate limit and no token budget. The Act 7 console shows exactly that: probe 1 (no token) and probe 2 (an Azure Resource Manager token) are refused at the gateway with a 401 `unauthorized`; probe 3 (a Foundry-audience token) is forwarded and Foundry answers 400 or 404; probe 4 calls Foundry without APIM and records Foundry's own answers (`console/act7.py:182-198#unauthorized`, `console/act7.py:210-215#bypassing`). The console states the caveat in its own words (`console/act7.py:48-49#HONEST_PUBLIC`, `console/catalog.py:958-961#Honest`), and the README calls the front door "a gateway, not a wall around the model" (`README.md:149-149#front`). The direct path is selectable in the console, and its own text says it has no per-user token budget, no token metering and no kill switch at the agent's entrance (`console/act7.py:161-171#run_agentpath`).

The production remedy named in the repo is a private endpoint on the Foundry account, which would make the front door the only way in (`DESIGN.md:174-174#public`). The private MCP server is also outside this gateway: it validates the same Entra token inside the VNet itself and does not read the kill switch (`console/catalog.py:958-961#Not`).

**Why.** Forwarding the token unchanged keeps two properties that matter more than the gateway's own checks: Foundry still authorizes the person with Azure RBAC, and OAuth identity passthrough still reaches every MCP server as that person (`infra/apim/policies/agent-frontdoor.policy.xml:10-12#UNCHANGED`, `DESIGN.md:174-174#unchanged`). The proof playbook states the invariant as a question and an answer: the gateway does not swap in a service identity (`docs/PROOF-PLAYBOOK.md:1017-1017#service`).

**Trade-off / limitation.**

- **No client allow-list at the front door.** The `azp` allow-list `abw-allowed-azp` is read only by the MCP policy, so any client application in the tenant that can obtain a Foundry-audience token for a user passes this gateway; Foundry then decides per person.
- **No `scp`, `roles` or app-only test.** An app-only token for `https://ai.azure.com` from the same tenant also passes `validate-jwt` here, and is counted under the service principal's `oid`. Whether Foundry accepts it depends on that principal's role assignments.
- **The budget is counted after the response** and per gateway [L41][L42].
- **The two limits are plain named values** that anyone with APIM write access can change at runtime (`infra/08-agent-frontdoor.bicep:27-47#abw-agent-token-quota`); the Act 7 beat lowers them for a moment to show the 429 and puts them back (`console/catalog.py:958-961#Beat`).
- **Act 7 is newer than the proofs.** It was added after the final proof run and is not among the 18 proofs (`DESIGN.md:246-246#Act`).

**Not in this repo.** How the Foundry project identity itself would call an MCP server (the connections use the user's token); the shape of Foundry's refusal for a caller without a role; how azd authenticates.

### 6.10 Lifetimes, refresh, revocation and replay

**What this section proves.** ABW does not revoke tokens. An access token is good until its `exp`, Foundry keeps one for its whole life, and the repo builds no continuous access evaluation for its custom APIs (the README says they cannot get it, which this document did not verify), so the repo adds revocation points that do not depend on the token: a deny list at the two gateways and Azure RBAC at the data plane. The README states the pairing in one sentence (`README.md:141-141#CAE`), and the kill-switch script's header says what each lever stops and how long it takes (`scripts/kill-switch.ps1:7-14#revokeSignInSessions`). This section tabulates every lifetime in play, walks the kill switch, shows what `jti` is and is not used for, explains why continuous access evaluation is not relied on, and lists what cannot be revoked quickly.

#### 6.10.1 Lifetimes at a glance

**Platform behaviour and Implemented.** Platform defaults come from Learn; the other rows are read from code or measured by the proofs. A measured number is one run unless the row says otherwise.

| artefact | lifetime or refresh cycle | basis | evidence |
|---|---|---|---|
| ID token (C1) | 1 hour | Platform default [L1][L4] | Kept in the client library's cache; no ABW service accepts it (6.2) |
| Access token for an MCP API (T2) | A random value between 60 and 90 minutes, 75 on average | Platform default [L1]. The repo sets no lifetime policy: the app manifests set the token version and nothing about lifetime | `identity/Setup-Entra.ps1:129-133#requestedAccessTokenVersion`, `README.md:141-141#CAE` |
| Access token for a CAE-capable client | Up to 28 hours | Platform [L40]. It does not apply to ABW: the MCP APIs issue no claims challenge and the repo's MSAL clients pass no `client_capabilities`, whose default is none [L30] (6.10.4) | `src/mcp/abw_mcp/obo.py:53-58#ConfidentialClientApplication`, `console/personas.py:126-129#PublicClientApplication` |
| Refresh token (C2) | 90 days of inactivity; replaced on use; dead at once when revoked | Platform [L1][L2]; revocation [L39] | `console/personas.py:108-110#_cache_path`, `docs/RUNBOOK.md:127-127#replay` |
| Device code (C4) | 15 minutes to finish the sign-in | Platform default [L7] | `console/personas.py:253-253#initiate_device_flow` |
| UAMI federated assertion (T3) | The managed-identity back end caches its token for about 24 hours; the code asks for one each time MSAL needs a client assertion | Platform [L9] | `src/mcp/abw_mcp/obo.py:77-79#_get_client_assertion` |
| OBO tokens (T4a, T4b, T4c) | The access-token lifetime of the downstream resource [L5]; the code records `expires_on` as now plus `expires_in` and keeps them in a per-process MSAL cache that no code flushes | Implemented | `src/mcp/abw_mcp/obo.py:51-51#SerializableTokenCache`, `src/mcp/abw_mcp/obo.py:69-75#expires_on` |
| Foundry-held passthrough token (T2b) | Held for its whole life: two measured token sets were each used for 39-51 minutes, and a third set for about 73 minutes (wall and private tokens) and about 90 minutes (actions token) | Measured by the project from the MCP audit `jti`; consistent with Entra's 60-90 minutes | `DESIGN.md:223-223#jti`, `docs/RUNBOOK.md:49-49#jti` |
| A token minted before the person had a role | Foundry keeps it, so the agent's tool lists stay empty until it expires: about 14 to 20 minutes after the roles were fixed in the observed case | Observed | `DESIGN.md:226-226#Consent` |
| MCP server signing-key cache | 3600 seconds, plus a forced refresh when a token names an unknown `kid` | Implemented | `src/mcp/abw_mcp/auth.py:60-63#ttl_seconds` |
| APIM signing-key cache | Pulled every hour, and at most once in 5 minutes when a token names an unknown `kid` | Platform [L14] | `infra/apim/policies/mcp-jwt.policy.xml:17-18#openid-config` |
| App-role claim in a new token | Up to about 30 seconds after an assignment change; one removal lagged longer | Observed | `DESIGN.md:226-226#propagation` |
| Azure RBAC role assignment | Up to 10 minutes on Learn [L20]. Group-membership removal reached the Storage denial in 5 to 44 seconds across runs (27 in the committed scoreboard, 44 in the runbook's final run), polled every 15 seconds | Platform versus measured | `DESIGN.md:218-218#Entitlement`, `demo/evidence-scrubbed/SCOREBOARD.md:45-45#seconds`, `demo/prove.py:973-977#drifted` |
| Plain APIM named values (`abw-deny-oids`, `abw-allowed-azp`) | "About a minute" in the script text; 43 seconds for the kill switch and 46 for the allow-list in the committed scoreboard; the runbook quotes 45 to 90 seconds, with 66 and 59 for its final run. Learn gives no figure | Measured | `scripts/kill-switch.ps1:107-107#minute`, `demo/evidence-scrubbed/SCOREBOARD.md:41-44#seconds`, `docs/RUNBOOK.md:335-336#harness` |
| Key Vault-backed named value (`abw-vendor-key`) | A changed secret reaches APIM within 4 hours | Platform [L43] | `infra/05-apim-apis.bicep:81-91#secretIdentifier` |
| `abw-agent-client` secret (C3) | 80 days; the script mints a new one when the saved one is missing, no longer on the app or has fewer than 10 days left | Implemented | `identity/Setup-Entra.ps1:158-169#addPassword` |
| APIM subscription key (C5) | No expiry and no rotation job | Implemented | `infra/05-apim-apis.bicep:204-213#sub-abw-legacy-poc` |
| Vendor key (C6) | No expiry; rotated by hand | Implemented | `scripts/deploy.ps1:182-186#Get-VendorKey` |
| MCP gateway rate window | 120 calls per 60 seconds per user | Configured | `infra/apim/policies/mcp-jwt.policy.xml:81-81#rate-limit-by-key` |
| Front-door rate window | Calls per 60 seconds per user (60 by default); a lock-out lasts about two minutes | Configured and observed [L42] | `infra/apim/policies/agent-frontdoor.policy.xml:95-95#rate-limit-by-key`, `DESIGN.md:174-174#lock-out` |
| Front-door token budget | 250,000 tokens per user per hour by default, counted in a fixed window that follows the calendar hour | Configured [L41] | `infra/apim/policies/agent-frontdoor.policy.xml:96-96#llm-token-limit`, `docs/PROOF-PLAYBOOK.md:1647-1647#calendar` |
| `revokeSignInSessions` | Refresh tokens stop working after "a small delay of a few minutes" | Platform [L39] | `scripts/kill-switch.ps1:109-116#revokeSignInSessions` |
| Conditional Access and group changes at CAE resource providers | Up to a day, reduced to two hours by an optimisation. Not a mechanism ABW's custom APIs use | Platform [L40] | `README.md:141-141#CAE` |

**Why.** ABW takes the Entra defaults and does not tune them. The design leans on three clocks that differ by orders of magnitude: a token lives 60 to 90 minutes, the gateway deny list takes effect in about a minute, and a role-assignment change reaches the data plane in seconds to minutes. The shortest clock is the lever the repo actually pulls.

**Trade-off / limitation.** Nothing in the repo shortens a token's life: there is no token-lifetime policy and no sign-in frequency setting, and the one Conditional Access policy ABW creates carries conditions and a grant control but no session control (`scripts/extras-agent-identity.ps1:243-248#grantControls`). The exposure window on any path that does not pass the kill switch is therefore the token's remaining life, up to 90 minutes (6.10.5). Every propagation figure for plain named values is a measurement, because Learn gives none.

#### 6.10.2 The kill switch

**Implemented.** The kill switch is one APIM named value, `abw-deny-oids`: a comma-separated list of user object ids that Bicep creates as `none` and marks not secret (`infra/05-apim.bicep:209-218#abw-deny-oids`). Both gateway policies read it as their first claim test, before the client allow-list, the scope, the roles, the rate limit and the token budget: the MCP policy inside `abw-deny` (`infra/apim/policies/mcp-jwt.policy.xml:37-37#abw-deny-oids`) and the front door inside its own, shorter `abw-deny` (`infra/apim/policies/agent-frontdoor.policy.xml:51-55#abw-deny-oids`, 6.9.2). Each splits the value on commas and tests whether the list contains the token's `oid` claim exactly, so an entry has to be a lower-case object id with no spaces around it. The script writes it that way.

**The first minute, step by step.**

1. The operator runs `scripts/kill-switch.ps1 -User <who>`. `<who>` may be a persona alias, a UPN, an object id or `operator` (`scripts/kill-switch.ps1:16-17#operator`).
2. `Resolve-Oid` turns it into a lower-case object id: a GUID is lower-cased, `operator` maps to the configured operator object id, a persona alias is looked up in the generated `entra.json`, and a UPN is resolved through Microsoft Graph with the operator's deploy-time token (C7) (`scripts/kill-switch.ps1:45-55#Resolve-Oid`).
3. `Get-DenyList` reads the current value with `az apim nv show`. `none` means empty, and every element is trimmed and lower-cased (`scripts/kill-switch.ps1:63-68#Get-DenyList`).
4. If the id is not already listed, the script appends it and writes the list back with `az apim nv update`: `none` for an empty list, a comma join with no spaces otherwise (`scripts/kill-switch.ps1:70-74#Set-DenyList`, `scripts/kill-switch.ps1:106-107#Set-DenyList`).
5. APIM applies the new value. The script says "within about a minute" and the console allows 90 seconds, nine tries ten seconds apart (`console/jobs.py:1243-1258#tries`). The committed scoreboard records 43 seconds from the command to the first refusal (`demo/evidence-scrubbed/SCOREBOARD.md:41-41#seconds`). Learn gives no figure for a plain named value.
6. The next call that carries a token for that `oid` still passes `validate-jwt`, because the token is valid. Then `abw-deny` evaluates to `revoked`, the decision metric and a trace are emitted, and the policy returns 403 `forbidden` with `reason` `revoked`, the server name and the request id (`infra/apim/policies/mcp-jwt.policy.xml:64-80#forbidden`). The front door returns its own 403 (6.9.2).
7. The gateway log carries the `revoked` rows (`docs/PROOF-PLAYBOOK.md:438-440#revoked`) and Sentinel rule ABW-005 raises the incident (`scripts/kill-switch.ps1:118-118#ABW-005`; the rule is in section 11.3).
8. Optionally, `-RevokeSessions` also calls Graph `POST /users/<oid>/revokeSignInSessions`. The operator is skipped unless `-Force` is added, because the call would sign the Azure CLI out (`scripts/kill-switch.ps1:109-116#revokeSignInSessions`, `scripts/kill-switch.ps1:110-111#Force`).
9. `-Restore` removes only that id and `-Reset` writes `none` (`scripts/kill-switch.ps1:90-104#Restore`).

**What each lever stops (Implemented, with measured times).**

| lever | what it stops | what it does not stop | how fast | code |
|---|---|---|---|---|
| Deny-list entry (the default) | Every call by that user at the four governed MCP APIs and the agent front door, whatever roles the token carries | A call that never reaches APIM: the private MCP server, the legacy key path, a direct call to the Foundry endpoint | About a minute; 43 seconds measured | `scripts/kill-switch.ps1:7-9#abw-deny-oids`, `console/jobs.py:1304-1350#run_kill` |
| `-RevokeSessions` | New access tokens minted from the user's refresh tokens: an app that redeems an invalidated refresh token gets an error and has to send the user through sign-in again [L39] | An access token already issued, which clients replay from their cache until `exp` [L40]; the token Foundry already holds. A refresh token held by Foundry is one of "all refresh tokens", so its next renewal is expected to fail (inference, not exercised) | "A small delay of a few minutes" [L39] | `scripts/kill-switch.ps1:109-116#revokeSignInSessions` |
| Client allow-list (`scripts/client-allowlist.ps1 -Block`) | A validly signed token whose `azp` is not on `abw-allowed-azp`, for every user of that app | The agent path: Foundry calls with its own client, which stays on the list, "verified live". A token from an app that is on the list | 46 seconds measured | `scripts/client-allowlist.ps1:7-9#client_not_allowed`, `docs/RUNBOOK.md:219-219#fail` |
| Group removal | The user's data-plane access, shown for Storage, while the token is unchanged | The gateway and server checks, which still see the same role claim | 5 to 44 seconds measured | `demo/prove.py:962-987#storage_rbac_denied` |
| Disable the Entra account | Sign-in altogether | Not scripted on purpose: "an identity decision, not a gateway one" | Manual | `scripts/kill-switch.ps1:14-14#manual` |
| Disable the agent's own identity | At most new agent-identity token issuance, by the script's own conclusion | The agent run that uses the user's token: it still completed (one run) | Not measured | `scripts/extras-agent-identity.ps1:343-348#identityLeverTest` |

**Reach.** The switch sits in the two gateways, so it covers the four governed MCP APIs and the agent front door. It does not cover three paths. The private MCP server is not behind APIM and validates the token itself, so "a revoked user keeps access here until their token expires" (`console/catalog.py:987-996#Honest`, `docs/PROOF-PLAYBOOK.md:444-444#kill`); the design text labels this "read from the code, not exercised live" (`DESIGN.md:107-107#exercised`). The legacy API has no user to revoke because it runs on a shared key. A direct call to the Foundry endpoint with a valid token never meets the front door (6.9.3).

**The agent under the switch.** In the console scene a revoked user's agent run fails closed. Behind the front door the user is refused before the agent or the model is invoked; on the direct path the agent's tool calls carry the same user and are refused at the MCP gateway (`console/jobs.py:1321-1326#apim`). In Path B the operator is also the agent's user, so the runbook says never to run an agent beat while the switch is on, and to prove the allow-list and the kill switch one after the other because the policy tests the deny list first (`docs/RUNBOOK.md:219-219#fail`).

**Audit of the switch itself.** Flipping it is an ARM write by the admin account. The Azure activity log records a `namedValues/write` operation whose resource id ends in `abw-deny-oids` (`docs/PROOF-PLAYBOOK.md:432-436#namedValues/write`).

**Why.** The named value is the one revocation that does not depend on the token: it needs no code deploy and no lookup against Entra, and the policy uses only the `oid` that `validate-jwt` already holds. The design text pairs it with group removal, which is durable and reaches the data plane in under a minute (`DESIGN.md:236-236#deny-list`).

**Trade-off / limitation.**

- The script reads the list at line 87 and writes it at line 106, so two operators acting at the same moment can overwrite each other's entry (`scripts/kill-switch.ps1:87-87#Get-DenyList`, `scripts/kill-switch.ps1:106-106#Set-DenyList`).
- One list serves every MCP server and the front door. There is no per-server or per-tool revocation.
- Re-deploying the APIM Bicep states `none` again (`infra/05-apim.bicep:215-215#none`), so a redeploy is expected to clear a runtime edit. This is an inference from the template; the repo does not exercise it. Teardown and re-deploy are in section 4.10.
- The runbook describes an HTTP 401 right after the script as "old token vs new gateway state", with the remedy of waiting about 50 seconds and requesting a new token (`docs/RUNBOOK.md:288-288#abw-kill`). Neither policy returns 401 for a deny-list hit, which gives 403, so the repo does not explain the mechanism.
- The console explains an agent that still answered after a revoke as "the revoke had not reached every gateway replica yet" (`console/jobs.py:1331-1331#replica`). Its 90-second polling window is the only guard.

#### 6.10.3 `jti` in the audit trail

**Implemented.** The audit field named `jti` is a correlation key, not a security control. `verify_token` fills `Caller.jti` from the `uti` claim first and falls back to `jti` (`src/mcp/abw_mcp/auth.py:168-168#uti`). Learn describes `uti` as the "token identifier claim, equivalent to `jti` in the JWT specification", unique per token [L3]. The audit row copies it as `jti` (`src/mcp/abw_mcp/audit.py:208-208#jti`), and the actions server also stores it in each order record next to the `azp` and the request id (`src/mcp/abw_mcp/servers/actions.py:87-87#jti`). Entra records the same value as `UniqueTokenIdentifier` in its sign-in logs, and `AbwFullChain` joins the two (`DESIGN.md:170-170#UniqueTokenIdentifier`; section 10.3). The demo helper `abw-tokens` uses the field the other way round: it groups the MCP audit by token id to show how long one token kept serving calls, which is how the Foundry token-hold figures in 6.4.3 were observed (`demo/stage.ps1:62-62#token-hold`, `demo/stage.ps1:219-224#TokenId`).

**What it is not used for.** There is no replay defence anywhere in the chain: no `jti` cache, no nonce, no proof-of-possession binding and no revocation lookup in `verify_token` (`src/mcp/abw_mcp/auth.py:108-170#verify_token`). A bearer token is accepted from any caller that presents it, until `exp`. The raw token is kept in `Caller.token` with `repr=False`, so printing the object does not leak it, and the audit row has no token field at all (`src/mcp/abw_mcp/auth.py:30-41#repr`, `src/mcp/abw_mcp/audit.py:196-216#args_sha256`).

**Why a one-time-use rule would not work here.** Foundry presents the same token for its whole life, 39 to 51 minutes or more of tool calls in the measured sets (`DESIGN.md:223-223#jti`). A server that rejected a repeated `jti` would refuse Foundry's own second call. So the design correlates on the id and does not reject on it.

**Trade-off / limitation.** The field is named `jti` but holds `uti` whenever the token has one, so anyone who reads the audit by that name should know which claim it is. Entra's own log uses the `uti` name.

#### 6.10.4 Why continuous access evaluation is not relied on

**Platform behaviour [L40][L48].** With continuous access evaluation (CAE) a resource provider can reject an access token that has not expired: the API returns 401 with a `WWW-Authenticate` header that carries a claims challenge (`error="insufficient_claims"` plus a `claims` parameter), and the client then asks Entra for a new token with those claims. Both sides have to opt in. Learn says "both your app and the resource API it's accessing must be CAE-enabled", the client declares support with the `cp1` client capability, and only then does it receive CAE tokens, whose lifetime can rise to 28 hours [L48][L40]. A client that mishandles the challenge "might repeatedly retry an API call using a token that is technically valid but is revoked due to CAE" [L48]. Critical-event evaluation is implemented by services such as Exchange Online, SharePoint Online and Teams, and Learn warns of up to 15 minutes of latency even there [L40].

**What ABW has (Implemented, and not in this repo).** None of the CAE pieces exist on either side:

- The server checks the signature, `exp`, `nbf`, `iss`, `aud`, `tid`, `azp` and `scp`. It has no revocation lookup and its 401 carries `invalid_token` and a `resource_metadata` pointer, not a claims challenge (`src/mcp/abw_mcp/auth.py:250-260#resource_metadata`).
- The gateway 401 is the same shape (`infra/apim/policies/mcp-jwt.policy.xml:102-104#resource_metadata`).
- The clients never declare `cp1`. The OBO confidential client and the console's public client are built without `client_capabilities` (`src/mcp/abw_mcp/obo.py:52-58#ConfidentialClientApplication`, `console/personas.py:126-129#PublicClientApplication`), and no code, script or template in the repo sets `client_capabilities`, `xms_cc` or `enable_cae`.
- The repo says so in plain words: custom APIs get no CAE, so group removal is paired with the gateway kill switch (`README.md:141-141#CAE`, `DESIGN.md:236-236#CAE`). This document did not verify that sentence: the Learn pages read here say that both the client and the resource API must be CAE-enabled and do not say whether a custom API can enable it [L40][L48], so what is shown is that none of the pieces is built, not that none could be.

The kill-switch script's header says `-RevokeSessions` is "near immediate for CAE-capable clients" (`scripts/kill-switch.ps1:13-13#CAE-capable`). That holds for the first-party services Learn lists. It does not describe the ABW servers.

**Why.** CAE needs work on both ends: the server would have to emit the challenge and the clients would have to handle it. ABW instead puts the revocation decision in two places it controls, the gateway deny list and Azure RBAC at the data plane (6.10.2, 6.8).

**Trade-off / limitation.** An already-issued token stays usable on any path outside the gateway until it expires, and neither `revokeSignInSessions` nor an account change shortens that on a non-CAE API [L39][L40].

#### 6.10.5 What cannot be revoked immediately

**Implemented, with the honest edges.** Every row follows from one fact: ABW validates self-contained bearer tokens and keeps no server-side session. Where a path sits behind the gateways, the deny list is the immediate lever. These are the things it cannot reach.

| item | why it survives | what shortens or ends it | evidence |
|---|---|---|---|
| An access token already issued (T1, T2a, T2b) | The servers validate signature and `exp` only. Clients replay a cached token until it expires [L40] | Expiry, 60 to 90 minutes. At the gateways, a deny-list entry makes it useless in about a minute | `src/mcp/abw_mcp/auth.py:108-170#verify_token` |
| The token Foundry holds (T2b) | Held per user and per connection for its whole life. The repo cannot read, rotate or revoke it (6.4.3) | A deny-list entry blocks its use at APIM. `-RevokeSessions` stops its renewal, not the token in hand [L39] | `DESIGN.md:223-223#jti` |
| The private MCP path | Not behind APIM. The server validates the token itself and does not read the deny list | Expiry. The repo's remedy is an internal APIM in front of it, or having the server read the same list. Group removal still bites at the data plane | `console/catalog.py:987-996#Honest`, `DESIGN.md:107-107#exercised` |
| A direct call to the Foundry endpoint | Foundry stays reachable with a valid Foundry-audience token. The front door is a gateway, not a wall (6.9.3) | A private endpoint on the Foundry account, named as the production remedy and not built | `DESIGN.md:174-174#public`, `console/catalog.py:958-961#Honest` |
| OBO tokens in a replica's memory (T4a to T4c) | Held in MSAL's per-process cache, which no code flushes; whether MSAL reuses a cached OBO token is not established (6.7.5) | Their own expiry or a replica restart. On the governed path no call reaches them once the user is on the deny list | `src/mcp/abw_mcp/obo.py:51-51#SerializableTokenCache` |
| Persona refresh tokens (C2) | Plain JSON files and the Azure CLI cache. "Anyone who can read one can replay it until it expires or is revoked" | `-RevokeSessions` [L39], 90 days of inactivity [L1][L2], or deleting the file | `console/personas.py:108-123#_cache_path`, `docs/RUNBOOK.md:127-127#replay` |
| A role claim inside an issued token | The `roles` claim is fixed when the token is issued. A held token keeps the old claim until it is replaced | Token replacement. Azure RBAC at the data plane reacts on its own, in 5 to 44 seconds measured | `DESIGN.md:226-226#propagation`, `demo/prove.py:962-987#storage_rbac_denied` |
| Disabling the agent's own identity | It did not stop an agent run that uses the user's token (one run) | The deny list | `scripts/extras-agent-identity.ps1:343-348#identityLeverTest` |
| The APIM subscription key (C5) | No expiry, shared, and not tied to a user, so there is no user to put on a deny list | Rotate the key by hand in APIM | `infra/05-apim-apis.bicep:204-213#sub-abw-legacy-poc`, `docs/PROOF-PLAYBOOK.md:444-444#kill` |
| The vendor key (C6) | Held in a Key Vault-backed named value and as an ACA secret; no expiry. Key Vault-backed named values refresh within 4 hours [L43] | Rotate by hand in both places | `infra/05-apim-apis.bicep:81-91#secretIdentifier`, `infra/04-apps.bicep:176-187#vendor-api-key` |
| The `abw-agent-client` secret (C3) | The same secret is copied into each Foundry connection. An existing connection is skipped unless `-Force` is given, so a re-minted secret does not reach it | Re-run the connection script with `-Force`. Secrets last 80 days | `scripts/foundry-connections.ps1:80-82#Force`, `identity/Setup-Entra.ps1:158-169#addPassword` |

**Why.** The design accepts the exposure as bounded: the worst case on a path outside the gateways is the token's remaining life, at most 90 minutes, and the keys are shared secrets rotated by hand.

**Trade-off / limitation.** The shared keys (C5, C6, C3) have no automatic expiry that a user action can trigger. Rotating them is an operator task with no script in the repo for the subscription key or the vendor key.

### 6.11 One governed tools/call, token by token

**What this section proves.** One governed `tools/call` crosses five trust boundaries: the front door, Foundry, the MCP gateway, the MCP server and the data plane. At every hop one token bound to the signed-in person enters and one leaves. The caller's own token is checked at the front door, Foundry replays the same person's token to the MCP gateway, and the MCP server trades that token for a data-plane token for the same person. No hop on this path swaps in a service identity, and the audit record has no field that could hold a token (`DESIGN.md:100-112#OBO`, `src/mcp/abw_mcp/audit.py:178-216#build_event`).

#### 6.11.1 Reading the diagrams against the tags of 6.2

Diagrams 01, 03, 04, 05, 06, 07, 11 and 13 label the four working tokens T1 to T4. This section uses the same four labels and adds a letter only where a family has more than one member: T2a is the user's token for an MCP API when a client presents it directly, T2b is the same kind of token when Foundry holds it and replays it to the tool, and T4a, T4b and T4c are the data tokens for Storage, Cosmos DB and Search. C1 to C7 are the other credentials of 6.2.1. They appear only in this document; diagram 07 draws some of them (the client secret, the subscription key, the vendor key and the operator's tokens) as cards without a label.

| tag in this section | the token | label in the diagrams | drawn in diagram 11 | validated by | code |
|---|---|---|---|---|---|
| T1 | the caller's token for the Foundry data plane, `aud` = `https://ai.azure.com` | T1 | yes | the front door, then Foundry | `console/act7.py:38-39#AI_AUDIENCE` |
| T2b on the agent path, T2a when a caller calls the MCP API directly | the user's token for the wall MCP API: `aud` = that API's client ID, scope `Tools.Read`, app role `Wall.Falcon` or `Wall.Orion` | T2 | yes | the MCP gateway, then the MCP server | `src/mcp/abw_mcp/auth.py:108-170#verify_token` |
| T3 | the managed identity's assertion, `aud` = `api://AzureADTokenExchange` | T3 | no | Entra, against the federated credential | `src/mcp/abw_mcp/obo.py:77-79#_get_client_assertion` |
| T4a | the on-behalf-of token for Storage: `aud` = `https://storage.azure.com`, delegated scope `user_impersonation` | T4 | yes | Storage, through Azure RBAC | `src/mcp/abw_mcp/data.py:57-62#read_blob_text` |

#### 6.11.2 Before the call: what must already be true

**Implemented and Configured.** A governed call starts from four facts that earlier steps created. None of them is made at call time.

1. **A sign-in exists.** The person has signed in (device code in the console, 6.3.2) and the client holds a refresh token (C2) from which it mints T1, or T2a for a direct call, when it needs one (`console/personas.py:253-253#initiate_device_flow`).
2. **Consent was given.** Until the person has consented to a connection, the agent run returns a consent link instead of tool results. The console runner prints the link, waits, and then starts a fresh response. After consent Foundry holds a per-user token, T2b, for each connection (6.4, `src/agent/ask.py:224-232#open_consent`).
3. **An app role is assigned in Entra.** The role (`Wall.Falcon` for the demo persona) is assigned directly to the user on the wall API's enterprise application, so it appears in the `roles` claim of T2b (`identity/Setup-Entra.ps1:237-251#appRoleAssignments`, `identity/Setup-Entra.ps1:53-54#Wall.Falcon`).
4. **A data-plane role exists for the person's group.** The group `sg-abw-wall-falcon` holds Storage Blob Data Reader on the container `wall-falcon`, and nobody holds it on `wall-orion`, so Storage itself is the second layer of the information barrier (`identity/Setup-Entra.ps1:53-54#sg-abw-wall-falcon`, `infra/03-platform.bicep:628-638#raFalconBlob`).

**Why.** Authorization is checked twice by two mechanisms. The app role is a claim that the gateway and the server read from the token. The group membership is evaluated by Storage when the on-behalf-of token arrives. A person needs both, and an administrator can change either one without touching code (6.8).

#### 6.11.3 The walk-through

**Implemented.** The example is the wall tool `get_deal_document` with `doc_id` = `FALCON-001`, called by a person who holds `Wall.Falcon` and sits in the Falcon group. Each step names the token that enters, the token that leaves, who validates it, and where the code is. Steps 1 and 2 summarize 6.9.2 and steps 4 to 8 summarize 6.5 to 6.8.

1. **The caller presents T1 to the front door.**
   - Token in: T1 (`aud` = `https://ai.azure.com`) as `Authorization: Bearer` on the request that names the agent. Token out: the same T1, unchanged.
   - Validator: the front-door `validate-jwt`, then the kill-switch test on `oid`, the rate limit (60 per 60 seconds by default) and the hourly token budget (250,000 by default). A denial here ends the call before Foundry sees it (6.9.2, steps 3 to 8).
   - Code: `infra/apim/policies/agent-frontdoor.policy.xml:18-32#validate-jwt`, `infra/apim/policies/agent-frontdoor.policy.xml:95-96#rate-limit-by-key`.
2. **APIM hands T1 to Foundry unchanged, and Foundry authorizes the person.**
   - Token in and out: T1. The policy has no `authentication-*` element and no step that rewrites `Authorization`.
   - Validator: Foundry checks Azure RBAC on the project endpoint for the person [L10][L46]. ABW assigns Foundry Agent Consumer to the consumers group.
   - Code: `infra/apim/policies/agent-frontdoor.policy.xml:106-108#forward-request`, `infra/02-foundry-rbac.bicep:36-44#raConsumersProject`.
3. **Foundry's MCP client calls the wall MCP API with T2b.**
   - Token in: T2b, the per-user token that Foundry minted at consent, or at the first agent call after the previous one expired, and keeps for the connection `mcp-wall-oauth` until it expires (6.4; `DESIGN.md:223#Foundry`). Token out: the same T2b as `Authorization: Bearer` on each MCP request to the gateway URL of the wall API. T1 is not sent: its audience is the Foundry data plane, which the MCP gateway does not accept.
   - Every MCP method is its own HTTP request. The policy treats `initialize`, `ping`, `tools/list` and any method that starts with `notifications/` as discovery, which skips only the role check and only on the three servers that filter their own tool list; every other method, including `tools/call` and a body it cannot parse, needs an app role. The server runs its transport stateless with JSON responses, so no request depends on an earlier one and every request is validated again. `tools/list` returns only the tools whose requirement the caller meets, so a person without a wall role sees no wall tools at all.
   - Validator: none yet. Foundry only holds the token and forwards it.
   - Code: `src/agent/abw_agents.py:119-141#project_connection_id`, `infra/apim/policies/mcp-jwt.policy.xml:40-44#discovery`, `src/mcp/abw_mcp/app.py:210-215#stateless`, `src/mcp/abw_mcp/registry.py:132-156#list_tools`.
4. **The MCP gateway validates T2b and decides.**
   - Token in: T2b. Token out: the same T2b, plus two request headers that the policy sets: `x-abw-request-id` (a new value, set with `override`) and `x-abw-gateway`.
   - Validator: `validate-jwt` (signature against the keys behind the v2 openid-config URL, the v2 issuer, `aud` = this API's client ID, `tid`, `exp`, 60 seconds of skew). Then `abw-deny` in order: `revoked`, `client_not_allowed`, `missing_scope`, `missing_role`. Then 120 calls per 60 seconds per `oid` (6.5.2, 6.5.3).
   - Evidence written: the decision metric `abw-gateway-decisions` and a trace carrying `server`, `oid`, `reason` and `request_id`.
   - Code: `infra/apim/policies/mcp-jwt.policy.xml:17-30#validate-jwt`, `infra/apim/policies/mcp-jwt.policy.xml:31-46#abw-deny`, `infra/apim/policies/mcp-jwt.policy.xml:81-81#rate-limit-by-key`, `infra/apim/policies/mcp-jwt.policy.xml:82-87#x-abw-request-id`.
5. **The MCP server validates T2b again, on its own.**
   - Token in: T2b, as the caller sent it, because the gateway does not rewrite `Authorization` on this API. Token out: a `Caller` object (`oid`, `upn`, `tid`, `roles`, `scopes`, `azp`, `aud`, `jti`) held in a context variable for this request. The raw token stays in a field that is excluded from `repr`, for step 7.
   - Validator: `verify_token` (key set cached for 3600 seconds, signature, `iss`, `aud`, `exp` and `nbf` with 60 seconds of leeway, `ver` equal to `2.0`, `tid`, not app-only, the `azp` allow-list when it is set, and the scope) (6.6). On refusal the answer is 401, or 403 for `missing_scope`, with `WWW-Authenticate`, and an `auth_failed` audit event. A missing role is never refused here, because the app passes no authorization check to the middleware (`src/mcp/abw_mcp/app.py:244-249#BearerAuthMiddleware`); the tool layer answers it as a `DENIED` result with HTTP 200 (6.6.4).
   - The request id: the middleware takes the first of `x-abw-request-id`, `x-request-id`, `x-ms-request-id` and `traceparent`. Behind APIM that is the gateway's id from step 4.
   - Code: `src/mcp/abw_mcp/auth.py:108-170#verify_token`, `src/mcp/abw_mcp/auth.py:173-188#RequestContextMiddleware`, `src/mcp/abw_mcp/auth.py:191-248#BearerAuthMiddleware`, `src/mcp/abw_mcp/app.py:250-253#add_middleware`.
6. **The registry applies the tool's own rules.**
   - Token in: none new, only the `Caller`. Token out: none, only a decision.
   - Validator: the tool's requirement (`require_any_role("Wall.Falcon", "Wall.Orion")`), the argument model (`doc_id` must match `FALCON-nnn` or `ORION-nnn`, no extra fields), and the handler's project rule: the project taken from `doc_id` must be among the projects implied by the caller's roles, else `project_not_in_token_roles` with the audit event `wall_violation_attempt`. A refusal becomes a normal tool result with `decision` = `DENIED`, not an MCP error, unless `MCP_DENIAL_MODE` is `strict`, because Foundry aborts the run when a tool returns `isError`.
   - Code: `src/mcp/abw_mcp/servers/wall.py:122-137#require_any_role`, `src/mcp/abw_mcp/registry.py:158-175#call_tool`, `src/mcp/abw_mcp/servers/wall.py:39-47#_require_project`, `src/mcp/abw_mcp/registry.py:263-270#isError`.

7. **On-behalf-of: T2b and T3 become T4a.**
   - Token in: T2b as the user assertion (`caller.token`) and T3 as the client assertion. Token out: T4a, an access token for `https://storage.azure.com` with the delegated scope `user_impersonation`, whose subject is the same person as T2b's.
   - T3 comes from the server's own user-assigned managed identity: `ManagedIdentityCredential(client_id=settings.uami_client_id)` is asked for `api://AzureADTokenExchange/.default`, and MSAL calls that function each time it builds a token request. The request fields are in 6.7.3.
   - Validator: Entra. It validates T2b (signature, and that its `aud` is the app named as `client_id`), validates T3 against the federated credential on the MCP app (issuer, subject = the managed identity's principal ID, audience), and checks that the app already holds consent for the downstream scope [L5][L6] (6.7.8). No secret is involved.
   - Cache: MSAL keeps T4a in memory per process. Whether a second call within the life of T4a is answered from that cache is not established (6.7.5).
   - Failure: `OboError` carrying Entra's error string becomes the soft denial `obo_failed:<code>` with the audit event `tool_denied`. There is no fallback to the server's own identity (6.7.7).
   - Code: `src/mcp/abw_mcp/data.py:57-62#read_blob_text`, `src/mcp/abw_mcp/obo.py:64-75#acquire_token_on_behalf_of`, `src/mcp/abw_mcp/obo.py:77-79#_get_client_assertion`, `src/mcp/abw_mcp/registry.py:177-191#OboError`, `identity/Setup-Entra.ps1:258-276#Invoke-Phase2`.
8. **Storage evaluates T4a against the person.**
   - Token in: T4a as `Authorization: Bearer` on the Blob GET for `FALCON-001.md` in the container `wall-falcon`, with `x-ms-client-request-id` set to the gateway's request id when the id matches a safe pattern. Token out: the blob bytes (200), or 403, or 404.
   - Validator: Storage verifies the Entra token and evaluates Azure RBAC for the token's principal, the person, through the group's Storage Blob Data Reader assignment on the container [L31][L33]. No identity of the MCP server is presented to Storage on this call.
   - Evidence written: a row in the Blob diagnostic log. The join function reads its requester (UPN or object ID), the requesting application ID and `ClientRequestId`, which Learn documents as the value of the `x-ms-client-request-id` header [L49][L50]. That the SDK keyword `client_request_id` becomes that header is the repo's design and is not itself cited from Learn.
   - Code: `src/mcp/abw_mcp/data.py:200-204#client_request_id`, `src/mcp/abw_mcp/data.py:21-28#downstream_request_id`, `observability/kql/AbwFullChainCore.kql:175-185#RequesterObjectId`, `infra/03-platform.bicep:464-476#diagBlob`.
   - For Search the same id is passed as `request_id`, which the Azure SDK's request-id policy writes to the same header by default [L51].
9. **If Storage answers 403.**
   - No new token. `read_blob_text` raises `DataAccessError` with the reason `storage_rbac_denied`. The handler turns it into a `ToolError` whose audit event is `wall_violation_attempt`. The caller gets a normal result with `decision` = `DENIED`, `error` = `FORBIDDEN`, `reason` = `storage_rbac_denied` and the `request_id`. A 404 gives `blob_not_found`, an `ERROR` result with the audit event `tool_denied`.
   - Validator: Storage (step 8). This is the layer that still refuses when the role claim in T2b says yes but the group membership says no, for example a person who holds both app roles but sits in only one project's group.
   - Code: `src/mcp/abw_mcp/data.py:66-71#storage_rbac_denied`, `src/mcp/abw_mcp/servers/wall.py:92-96#wall_violation_attempt`, `demo/prove.py:962-987#storage_rbac_denied`.
10. **The audit record is appended under the server's own identity.**
    - Token in: none from the user. The server's managed identity obtains its own Storage token and appends one JSON line to the audit append blob for that server and day. Token out: none.
    - What the record holds: `user_oid`, `user_upn`, `tid`, `roles`, `scp`, `azp`, `aud`, `jti` (the token's `uti` when it has one), `args_sha256`, `trace_id` and `request_id`. There is no field for any token and the arguments are stored as a hash.
    - Validator: Storage, against the managed identity's Storage Blob Data Contributor assignment on the audit container. This is a labelled exception (6.11.6). The append does not block the call unless `AUDIT_FAIL_CLOSED` is set: the background worker swallows a failure and prints `append_audit_failed`.
    - Code: `src/mcp/abw_mcp/audit.py:105-118#_append_line`, `src/mcp/abw_mcp/audit.py:124-143#ManagedIdentityCredential`, `src/mcp/abw_mcp/audit.py:178-216#build_event`, `src/mcp/abw_mcp/audit.py:94-103#append_audit_failed`, `infra/03-platform.bicep:548-556#raAuditAppend`.
11. **The return path.**
    - Token in: none. The tool result is JSON text with the same payload as `structuredContent`, and an allowed result gets `request_id` added. The MCP gateway's outbound section is `<base />` only, so the answer passes through unchanged. Foundry hands the result to the model. The model's answer returns through the front door, whose outbound section re-sets `x-abw-request-id` (the front door's own id, not the tool leg's) and `x-abw-gateway`, and the `llm-token-limit` element adds `x-abw-tokens-remaining` and `x-abw-tokens-consumed` [L41].
    - No token is returned to the caller or to the model. The only identifier that travels back is the request id.
    - Code: `src/mcp/abw_mcp/registry.py:195-200#setdefault`, `infra/apim/policies/mcp-jwt.policy.xml:93-95#outbound`, `infra/apim/policies/agent-frontdoor.policy.xml:109-117#x-abw-gateway`, `infra/apim/policies/agent-frontdoor.policy.xml:96-96#x-abw-tokens-remaining`.

Diagram: docs/diagrams/03-request-data-flow.excalidraw

#### 6.11.4 What the caller sees at each wall

**Implemented.** Every refusal on the path has a fixed shape and a fixed record. The first group is HTTP-level, where the caller gets a 4xx; the second group is tool-level, where the HTTP status is 200 and the refusal is in the result.

| wall | trigger | the caller sees | recorded as | code |
|---|---|---|---|---|
| front door | no token, bad signature, expired, wrong audience or tenant | 401 `unauthorized`, no `WWW-Authenticate` | the gateway log only: no decision metric and no reason | `infra/apim/policies/agent-frontdoor.policy.xml:121-141#unauthorized` |
| front door | the `oid` is on the deny list | 403 `forbidden`, reason `revoked` | decision metric `deny` and a trace | `infra/apim/policies/agent-frontdoor.policy.xml:71-94#forbidden` |
| front door | over the rate limit or the budget | 429 `rate_limited`, or 403 `token_quota_exceeded`, each with `retry_after_seconds` | deny metric and trace written by `on-error` | `infra/apim/policies/agent-frontdoor.policy.xml:142-187#token_quota_exceeded` |
| Foundry | the caller holds no Foundry role | Foundry's own error, not captured in the repo | not captured in the repo | `infra/02-foundry-rbac.bicep:36-44#raConsumersProject` |
| MCP gateway | no token, or `validate-jwt` fails | 401 JSON `unauthorized`, with `WWW-Authenticate` carrying `invalid_token` and `resource_metadata`; no request id | the gateway log; no decision metric | `infra/apim/policies/mcp-jwt.policy.xml:96-112#resource_metadata` |
| MCP gateway | `abw-deny` is set | 403 JSON `forbidden` with `reason`, `server` and `request_id` | decision metric `deny` and a trace | `infra/apim/policies/mcp-jwt.policy.xml:64-80#forbidden` |
| MCP gateway | more than 120 calls in 60 seconds for this `oid` | 429 from the policy's own answer [L42] | the gateway log carries the status; no ABW element adds a reason | `infra/apim/policies/mcp-jwt.policy.xml:81-81#rate-limit-by-key` |
| MCP server | `verify_token` fails | 401, or 403 for `missing_scope` only, with `WWW-Authenticate` carrying `error`, `error_description` (the reason code) and `resource_metadata`; a missing role is not refused here (the next row) | audit event `auth_failed`, decision `deny`, caller fields empty | `src/mcp/abw_mcp/auth.py:191-248#BearerAuthMiddleware`, `src/mcp/abw_mcp/auth.py:250-260#_auth_error_response`, `src/mcp/abw_mcp/app.py:244-249#BearerAuthMiddleware` |
| MCP tool | the role requirement fails, or the arguments do not match the model | 200 with a `DENIED` result (`FORBIDDEN`, reason `missing_role` or `missing_scope`), or an `ERROR` result `INVALID_ARGUMENT` | audit event `tool_denied`, decision `deny` | `src/mcp/abw_mcp/registry.py:158-175#call_tool` |
| MCP tool | the project is not among the caller's roles | 200 with `DENIED`, reason `project_not_in_token_roles` | audit event `wall_violation_attempt` | `src/mcp/abw_mcp/servers/wall.py:39-47#_require_project` |
| on-behalf-of | Entra refuses the exchange | 200 with `DENIED`, reason `obo_failed:<code>`, message "Unable to acquire downstream user token." | audit event `tool_denied` | `src/mcp/abw_mcp/registry.py:177-191#OboError` |
| data plane | Storage answers 403 | 200 with `DENIED`, reason `storage_rbac_denied` | audit event `wall_violation_attempt`, plus the Blob diagnostic row | `src/mcp/abw_mcp/data.py:66-71#storage_rbac_denied` |

A `DENIED` result carries a note that tells the model to report the block and the reason code and not to retry or look for a workaround (`src/mcp/abw_mcp/registry.py:285-289#workaround`). Which wall refused is therefore readable from the reason code alone: `revoked`, `client_not_allowed`, `missing_scope` and `missing_role` come from the gateway or the server, `project_not_in_token_roles` from the tool, `obo_failed:<code>` from Entra, and `storage_rbac_denied` from Storage.

#### 6.11.5 Joining the evidence: which ids travel with the call

**Implemented.** Four identifiers connect the records of one call. They are minted in different places and do not all travel the whole way.

| id | minted by | it appears in | code |
|---|---|---|---|
| token id (`uti`, else `jti`) | Entra, inside T2b | the MCP audit field `jti`, and Entra's non-interactive sign-in log as `UniqueTokenIdentifier` | `src/mcp/abw_mcp/auth.py:168-168#uti`, `src/mcp/abw_mcp/audit.py:208-208#jti`, `DESIGN.md:170-170#UniqueTokenIdentifier` |
| MCP-leg request id (a GUID) | the MCP gateway, from `context.RequestId`, set with `override` | the gateway trace, the 403 body, the header the server reads, the audit field `request_id`, the tool result, and the Storage client request id | `infra/apim/policies/mcp-jwt.policy.xml:57-63#request_id`, `infra/apim/policies/mcp-jwt.policy.xml:82-84#override`, `src/mcp/abw_mcp/registry.py:198-200#CorrelationId` |
| front-door request id | the front door, from `context.RequestId` | the response headers of the agent call | `infra/apim/policies/agent-frontdoor.policy.xml:109-113#x-abw-request-id` |
| W3C trace id | OpenTelemetry in the server, and APIM's own telemetry | the audit field `trace_id`, and the operation id of the APIM request telemetry | `src/mcp/abw_mcp/audit.py:214-214#trace_id`, `observability/kql/AbwFullChainCore.kql:10-18#gwTrace` |

**Two APIM requests, not one.** The agent call through the front door and the tool calls to the MCP gateway are separate HTTP requests with separate `context.RequestId` values: Foundry, not APIM, issues the tool leg, to the MCP gateway URL. The MCP policy overrides any inbound `x-abw-request-id`, so the front-door id cannot reach the MCP audit even if something forwarded it (`infra/apim/policies/mcp-jwt.policy.xml:82-84#override`). The repo stitches the legs together with the W3C trace id and with the `request_id` that every tool result echoes, which Foundry records on its `execute_tool` span (`observability/kql/AbwFullChainCore.kql:19-25#toolRid`). That Foundry propagates `traceparent` to the tool leg is shown only by the design of that join, not by a capture in the repo. `DESIGN.md` describes the request id as minted by APIM and carried by every record of the call (`DESIGN.md:112-112#x-abw-request-id`).

**Search and Cosmos DB rows join by time.** Only the Blob row carries the client request id. The join function states that Search and Cosmos DB logs carry no caller id and matches them to the MCP call by the time window in which the server worked (`observability/kql/AbwFullChainCore.kql:186-190#dataCalls`). Section 10.2 and 10.3 describe the join in full.

#### 6.11.6 The invariant and its labelled exceptions

**Implemented.** On the governed path no hop replaces the person's identity with a service identity. The proof playbook states the invariant as a question with a fixed answer: the gateway does not swap in a service identity (`docs/PROOF-PLAYBOOK.md:1017-1017#service`). The table lists every place where another identity acts, so that the invariant is not overstated.

| where | which identity acts | what it can reach | code |
|---|---|---|---|
| T3 in step 7 | the server's managed identity | nothing by itself: it proves the app to Entra for the exchange, and the data access is by T4a | `src/mcp/abw_mcp/obo.py:77-79#_get_client_assertion` |
| the audit append, step 10 | the server's managed identity | the audit container, with the role Storage Blob Data Contributor | `src/mcp/abw_mcp/audit.py:124-143#ManagedIdentityCredential`, `infra/03-platform.bicep:548-556#raAuditAppend` |
| the restricted-list read in the actions server | the actions server's managed identity | one Cosmos DB container, read only | `src/mcp/abw_mcp/servers/actions.py:30-37#use_user_token`, `infra/03-platform.bicep:604-615#cosmosActionsRestricted` |
| Cosmos DB calls with `cosmosObo` off | the server's managed identity | whatever its role assignments allow, which is not enough for `orders` and `positions` (6.7.6) | `scripts/deploy.ps1:344-344#cosmosObo`, `src/mcp/abw_mcp/data.py:181-182#managed_identity_credential` |
| the vendor path | the gateway: it validates the person's token, deletes `Authorization` and sets the vendor key (C6) | the third-party backend, which sees the key and never the person's token | `infra/05-apim-apis.bicep:75-78#vendorSection` |
| the legacy path | the legacy managed identity, over-privileged on purpose | blobs and search indexes are read, and Cosmos DB is read and written, across the account | `src/mcp/abw_mcp/servers/legacy.py:75-75#use_user_token`, `infra/03-platform.bicep:569-601#raLegacyBlob` |

**Paths that skip a wall (not identity swaps).** A direct call to Foundry skips the front door, and the private MCP server is reached without the gateway, so neither reads the kill switch. Both are covered in 6.9.3 and 6.10.5. The legacy server has no auth middleware at all and relies on the subscription key at APIM (`src/mcp/abw_mcp/app.py:241-249#VendorKeyMiddleware`).

**Why.** The person's identity, not a shared one, is what makes the data plane's own log and the entitlement proofs meaningful: when Storage says no, it is the person's group that it checked. That is the property the exceptions above are measured against.

**Trade-off / limitation.** The design gives up two things for it. Every governed call pays an extra Entra round trip for the exchange unless MSAL's cache answers (6.7.5), and a held token stays valid for its life, so revocation depends on the gateways and on the data plane's RBAC rather than on the token (6.10).

**Learn sources added in 6.9-6.11 (all verified; [L39]-[L51]):**

- [L39] Microsoft Graph, user: revokeSignInSessions: https://learn.microsoft.com/graph/api/user-revokesigninsessions?view=graph-rest-1.0
- [L40] Continuous access evaluation: https://learn.microsoft.com/entra/identity/conditional-access/concept-continuous-access-evaluation
- [L41] API Management llm-token-limit policy: https://learn.microsoft.com/azure/api-management/llm-token-limit-policy
- [L42] API Management rate-limit-by-key policy: https://learn.microsoft.com/azure/api-management/rate-limit-by-key-policy
- [L43] API Management named values: https://learn.microsoft.com/azure/api-management/api-management-howto-properties
- [L44] API Management managed identities: https://learn.microsoft.com/azure/api-management/api-management-howto-use-managed-service-identity
- [L45] Container Apps image pull with managed identity: https://learn.microsoft.com/azure/container-apps/managed-identity-image-pull
- [L46] Role-based access control for Microsoft Foundry: https://learn.microsoft.com/azure/foundry/concepts/rbac-foundry
- [L47] Agent identity concepts in Foundry: https://learn.microsoft.com/azure/foundry/agents/concepts/agent-identity
- [L48] How to use CAE-enabled APIs in your applications: https://learn.microsoft.com/entra/identity-platform/app-resilience-continuous-access-evaluation
- [L49] Get Blob, request headers (x-ms-client-request-id): https://learn.microsoft.com/rest/api/storageservices/get-blob#request
- [L50] Blob Storage monitoring data reference, Azure Monitor Logs tables (clientRequestId): https://learn.microsoft.com/azure/storage/blobs/monitor-blob-storage-reference#azure-monitor-logs-tables
- [L51] azure-core RequestIdPolicy: https://learn.microsoft.com/python/api/azure-core/azure.core.pipeline.policies.requestidpolicy?view=azure-python

**Key takeaways**

- **One person's token at every hop, and no service identity in the data path.** Foundry presents the user's token (T2b); each MCP server trades it for a downstream token with the on-behalf-of exchange, so Storage, Cosmos DB and AI Search decide about the person (6.7, 6.11; `src/mcp/abw_mcp/obo.py:64-75#acquire_token_on_behalf_of`, `DESIGN.md:100-112#OBO`).
- **Two independent authorization layers.** The `roles` claim decides which tool and project a call may attempt; data-plane RBAC decides what the person's groups may read. Either can refuse, and the proofs show both refusals (6.8, 6.11.4; `src/mcp/abw_mcp/servers/wall.py:39-47#_require_project`, `infra/03-platform.bicep:628-638#raFalconBlob`, `demo/prove.py:962-987#storage_rbac_denied`).
- **No secret on the MCP apps.** An app proves itself to Entra with its managed identity's token, used as a federated client assertion. The secrets that do exist are the `abw-agent-client` secret (C3), the APIM subscription key (C5) and the vendor key (C6) (6.1, 6.7.7; `src/mcp/abw_mcp/obo.py:77-79#_get_client_assertion`, `identity/Setup-Entra.ps1:258-276#Invoke-Phase2`).
- **The gateway validates, and the server validates again.** APIM checks signature, audience, issuer, tenant, scope, role and client; the server repeats a hand-written set of checks, so a server reached without the gateway still refuses an unauthenticated call, except on the legacy path (6.5, 6.6; `infra/apim/policies/mcp-jwt.policy.xml:17-30#validate-jwt`, `src/mcp/abw_mcp/auth.py:108-165#verify_token`).
- **The agent front door is a control point, not a wall.** It validates the caller's token, rate-limits and budgets per person, and forwards the same token; Foundry still authorizes the person, and the Foundry endpoint stays reachable without the front door (6.9.2, 6.9.3; `infra/apim/policies/agent-frontdoor.policy.xml:18-32#validate-jwt`, `infra/apim/policies/agent-frontdoor.policy.xml:106-108#forward-request`).
- **The kill switch is a gateway rule, not a token recall.** A deny-list entry stops the next call through the MCP gateway and the front door within about a minute; it does not touch a token already issued, the private server, the legacy path or a direct call to Foundry (6.10.2; `infra/apim/policies/mcp-jwt.policy.xml:31-46#abw-deny`).
- **Token lifetime bounds the exposure.** There is no continuous access evaluation, no replay cache and no proof of possession, so a stolen bearer token is good until `exp` (6.10.3, 6.10.4; `src/mcp/abw_mcp/auth.py:108-165#verify_token`).
- **The audit record carries claims, not the token.** It holds the caller's object id, user name, roles, scopes, client, audience and token id, a hash of the arguments rather than the arguments, and the correlation ids: enough to prove who asked, not enough to replay anything (6.11.5; `src/mcp/abw_mcp/audit.py:178-216#build_event`).
- **The ids join through the trace id and the echoed `request_id`, not through one id.** The front-door call and the tool calls are separate APIM requests (6.11.5; `observability/kql/AbwFullChainCore.kql:10-25#gwTrace`).
- **What Foundry does with the token it holds is known from observation, not from documentation.** Token sets were reused for 39 to 51 minutes in the audit, and the repo can neither read nor revoke that copy (6.4.3; `DESIGN.md:223-223#jti`).


### 6.12 Findings

The 61 findings raised while writing section 6 (documentation mismatches, defects and undocumented decisions) are collected in [Appendix B.4](appendix-b-findings-register.md#b4-raised-while-writing-section-6). Where the text above says "Findings" or quotes a finding number, it means that list.

---

[Index](../ARCHITECTURE-AND-DESIGN.md) | Previous: [5. Identity objects and entitlement model](05-identity-objects.md) | Next: [7. Authorization: the four walls and policy-as-code](07-authorization.md)
