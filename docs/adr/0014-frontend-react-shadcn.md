# ADR-0014: Frontend: React + Vite + shadcn/ui

Status: Zaakceptowany · 2026-11-09

## Kontekst
UX ma być nie-generyczny (skill frontend-design), oparty na wzorcach z Mobbin (Homerun) i gotowych komponentach.

## Decyzja
SPA: React, Vite, TypeScript, TanStack Router + Query, Tailwind CSS, **shadcn/ui** jako baza (komponenty kopiowane do `packages/ts/ui`, pełna kontrola stylu), TanStack Table dla BOM, wykresy przez shadcn charts (Recharts), i18n (PL/EN), formularze React Hook Form + Zod. Jedna biblioteka komponentów – nie mieszamy MUI/Chakra/Mantine/Ant/HeroUI (spójność, rozmiar paczki); z nich można czerpać wzorce.

## Konsekwencje
Własny design system bez walki z motywem gotowej biblioteki. Hosting statyczny (S3+CloudFront).

## Rozważane alternatywy
Next.js (SSR niepotrzebny w aplikacji za logowaniem); MUI/Ant (mocno narzucony wygląd).
