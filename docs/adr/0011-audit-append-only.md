# ADR-0011: Audyt: log append-only z łańcuchem skrótów i Object Lock

Status: Zaakceptowany · 2026-11-09

## Kontekst
Klienci pracują w reżimie ISO 13485 – potrzebna identyfikowalność, kto i dlaczego zmienił BOM.

## Decyzja
Tabela `audit_events` tylko do dopisywania (uprawnienia + trigger blokujący UPDATE/DELETE), pole `prev_hash`/`hash`; codzienny eksport do S3 z Object Lock (compliance). Pochodzenie każdej pozycji BOM (reguła + wersja / model + prompt + cytaty).

## Konsekwencje
Dowodliwa integralność logu; dane do kontroli klienta. Koszt: przechowywanie.

## Rozważane alternatywy
Tylko CloudTrail (nie widzi operacji domenowych).
