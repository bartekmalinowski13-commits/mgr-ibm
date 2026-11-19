# ADR-0019: Egress allowlist at the network layer (AWS)

Status: Proposed · 2026-11-19 (ops review I9; pending the owner's decision - see `docs/DECISIONS_LOG.md`).
Nothing in `infra/` changes with this ADR; it is the proposal the owner accepts, changes or rejects.

## Context
CLAUDE.md rule 2 and ARCHITECTURE.md (network) call for "no endpoints outside the allowlist".
Today the EU guarantee is enforced only at the application layer:
- The LLM gateway serves only enabled, verified EU catalogue entries, and `eu_guard` fails the build otherwise.
- Bedrock is limited by `aws:RequestedRegion` and the SCP.

The network allows more than that:
- The API security group (`ApiSg`, `compute-stack.ts`) has the CDK default `allowAllOutbound`.
- The agent-worker and kb-indexer security groups use `allowAllOutbound: !isolated`.
- The gateway security group has the default too.
- The app subnets reach the internet through NAT without domain filtering (`network-stack.ts`).

Every task in the app subnets can therefore reach any internet host. The API and the agent
worker handle untrusted file content (rule 5), so a prompt-injection or parser bug that makes
an outbound request is limited only by the code.

DECISIONS_LOG (2026-11-10, "NAT without domain filtering") accepted this for LLM provider
egress until acceptance. It does not cover the API and the workers.

## Decision (proposed)
1. **Route 53 Resolver DNS Firewall** on the VPC:
   - A rule group that ALLOWs only these domains and BLOCKs (NXDOMAIN) everything else:
     - the gateway's provider hosts, rendered from the catalogue by the same code as the gateway config, for example `api.mistral.ai`;
     - the IdP (Cognito, or the issuer and JWKS hosts of the configured OIDC provider);
     - `*.amazonaws.com` in `eu-central-1` for services that are not behind VPC endpoints.
   - Fail-open is off.
   - The rule group is per environment, so dev can carry extra entries (logged).
   - It is cheap: about $0.60 per million queries plus one rule group. Network Firewall is ten times the cost and needs a firewall subnet.
2. **Security groups tighten to what each task needs:**
   - `ApiSg`: 443 to the VPC endpoints' security group, 4000 to the gateway security group, 443 to the internet only for the IdP (JWKS, userinfo), and 5432 to the database.
   - Agent-worker and kb-indexer: 4000 to the gateway, 443 to the VPC endpoints and S3, and 5432. No general internet access.
   - Gateway: 443 out (provider APIs; DNS Firewall decides which hosts).
3. **Tests:**
   - CDK assertions that no application security group keeps `0.0.0.0/0` egress except the gateway's 443 rule and the API's 443 rule;
   - a synth test that the DNS Firewall domain list equals the catalogue's provider hosts.
4. Rollout:
   - Deploy in dev with the firewall rule action set to ALERT for a week and read the query logs.
   - Then switch to BLOCK, then move to staging and prod.
   - The pipeline deploys this. Nothing is applied from a session (CLAUDE.md rule 6).

## Consequences
- The EU allowlist is enforced by the network as well as by the code.
- A compromised task can no longer exfiltrate to an arbitrary host. DNS Firewall does not stop
  connections to raw IP addresses, so the security groups (point 2) carry that part.
- Every new external dependency (IdP, provider) needs an entry, which is also the review point.

Costs:
- one more stack resource per environment;
- the IdP hosts must be known at synth time (context variable);
- a forgotten entry shows up as an outage, which is why the rollout starts in ALERT mode.

## Alternatives considered
- AWS Network Firewall with a domain allowlist on TLS SNI: stronger, because it also covers IP connections, but about $300 per month per AZ.
- An HTTP egress proxy (Squid) in front of NAT: one more service to run and patch.
- Accept the gap in writing: possible for the pilot phase, but it contradicts rule 2 for customer data.
