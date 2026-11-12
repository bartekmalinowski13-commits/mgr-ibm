# ADR-0014: Frontend: React + Vite + shadcn/ui

Status: Accepted · 2026-11-09

## Context
The UX is to be non-generic (frontend-design skill), based on patterns from Mobbin (Homerun) and ready-made components.

## Decision
SPA: React, Vite, TypeScript, TanStack Router + Query, Tailwind CSS, **shadcn/ui** as the base (components copied into `packages/ts/ui`, full control of style), TanStack Table for the BOM, charts via shadcn charts (Recharts), i18n (PL/EN), forms with React Hook Form + Zod. One component library – we do not mix MUI/Chakra/Mantine/Ant/HeroUI (consistency, bundle size); patterns can be drawn from them.

## Consequences
Our own design system without fighting the theme of an off-the-shelf library. Static hosting (S3+CloudFront).

## Alternatives considered
Next.js (SSR unnecessary in an application behind a login); MUI/Ant (a heavily imposed look).
