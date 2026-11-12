# ADR-0013: IaC: AWS CDK in TypeScript + cdk-nag

Status: Accepted · 2026-11-09

## Context
Infrastructure as code, testable, with compliance checks.

## Decision
AWS CDK (TypeScript), stacks: network, data, identity, compute, observability, edge, security-baseline. `cdk-nag` in CI, snapshot and assertion tests (`aws-cdk-lib/assertions`).

## Consequences
Full typing, a high level of abstraction, unit tests of the infrastructure.

## Alternatives considered
Terraform (a good choice, but an additional language, HCL, and state to maintain).
