# ADR-0003: ECS Fargate + SQS; Lambda tylko do kleju; bez Kubernetes

Status: Zaakceptowany · 2026-11-09

## Kontekst
Potrzebne: API, długie zadania agentów (minuty), przetwarzanie plików, opcjonalnie GPU dla modeli open-weight.

## Decyzja
ECS Fargate dla API, workerów, gateway i Langfuse; SQS (+DLQ) jako bufor pracy, autoskalowanie po głębokości kolejki. Lambda tylko do reakcji na zdarzenia (np. upload do S3). GPU (vLLM) – ECS z capacity providerem EC2 GPU, włączane flagą. Kubernetes (EKS) – nie teraz; wrócić, gdy będzie >15 serwisów lub potrzeba własnych operatorów.

## Konsekwencje
Mało operacji, płacimy za użycie. Lambda odpada dla agentów (limit 15 min, zimne starty z ciężkimi zależnościami). Fargate nie obsługuje GPU – stąd osobny capacity provider.

## Rozważane alternatywy
EKS (wysoki narzut operacyjny); Lambda + Step Functions dla całego przepływu (limity czasu i rozmiaru ładunku, trudniejsze lokalne testy).
