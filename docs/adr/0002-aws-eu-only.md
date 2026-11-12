# ADR-0002: AWS, EU regions only, multiple accounts

Status: Accepted · 2026-11-09

## Context
Customers are EU medtech companies; processing of data in the EU is required.

## Decision
AWS, primary region `eu-central-1` (Frankfurt), backups in `eu-west-1`. AWS Organizations with accounts: management, security, log-archive, shared-services, dev, staging, prod. An SCP denies actions in non-EU regions (exceptions for global services: IAM, CloudFront, Route 53, Organizations).

## Consequences
Strong environment isolation and clear proof of data residency for customers. Cost: more accounts to manage (Control Tower / IaC).

## Alternatives considered
A single account with tags (weak isolation, hard to audit); another cloud provider (no advantage, Bedrock gives access to Claude in the EU).
