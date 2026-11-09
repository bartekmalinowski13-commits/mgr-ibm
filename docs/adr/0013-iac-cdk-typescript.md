# ADR-0013: IaC: AWS CDK w TypeScript + cdk-nag

Status: Zaakceptowany · 2026-11-09

## Kontekst
Infrastruktura jako kod, testowalna, z kontrolą zgodności.

## Decyzja
AWS CDK (TypeScript), stacki: network, data, identity, compute, observability, edge, security-baseline. `cdk-nag` w CI, testy snapshot i asercji (`aws-cdk-lib/assertions`).

## Konsekwencje
Pełna typizacja, wysoki poziom abstrakcji, testy jednostkowe infrastruktury.

## Rozważane alternatywy
Terraform (dobry wybór, ale dodatkowy język HCL i stan do utrzymania).
