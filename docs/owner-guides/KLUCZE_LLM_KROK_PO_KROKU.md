# Klucze do modeli LLM (przetwarzanie w UE) - instrukcja krok po kroku

> Wyjątek od zasady "dokumentacja po angielsku": ten plik jest po polsku, bo to instrukcja dla właściciela projektu (zob. `docs/DECISIONS_LOG.md`).
> Stan na **2026-11-12**. Konsole dostawców zmieniają się często. Gdzie nie dało się czegoś potwierdzić w oficjalnej dokumentacji, stoi **do sprawdzenia**. Ceny to **szacunki** do planowania, nie oferta.

Po co to wszystko: platforma (`mgr-ibm-bomagent` na Fly.io) rozmawia z modelami przez własną bramkę `mgr-ibm-llm-gateway`. Bramka potrzebuje kluczy do dostawców. Wszystko ma być przetwarzane w UE (CLAUDE.md zasada 2, ADR-0006, SECURITY.md). Szczegóły techniczne: `docs/platform/runbooks/llm-gateway-pilot.md` (na gałęzi `feat/llm-gateway-pilot`, po jej scaleniu na `main`).

## Spis treści

0. Kolejność: co robić najpierw
1. Czego NIE robić
2. Mistral (UE) - najszybciej
3. Claude przez AWS Bedrock (UE)
4. OpenAI przez Azure (UE Data Zone)
5. Qwen i inne modele open-weight (Bedrock w UE lub lokalnie w Ollama)
6. Jak wpisać klucze do bramki (`fly secrets`)
7. Tabela końcowa: co mam / czego brakuje

---

## 0. Kolejność: co robić najpierw, żeby mieć działające modele najszybciej

1. **Mistral** (rozdział 2). Około 20 minut, jedna karta płatnicza, jeden klucz. Daje działający model w UE najszybciej.
2. **AWS Bedrock** (rozdział 3). Około 1-2 godziny (konto AWS, MFA, uprawnienia). Daje Claude (Opus/Sonnet/Haiku) i Qwen/gpt-oss w jednym miejscu.
3. **Ollama na Macu** (rozdział 5B) - w każdej chwili, za darmo, tylko do nauki i testów lokalnych. Nie działa z pilotem na Fly.
4. **Azure OpenAI** (rozdział 4) na końcu. Najwięcej klikania i najwięcej niewiadomych (dostępność modeli w regionach).

Na start wystarczy **Mistral + Bedrock**. Reszta jest opcjonalna.

**Dwie rzeczy, które musisz wiedzieć od razu:**

- **Mistral**: domyślny adres `api.mistral.ai` jest "globalny". Mistral sam pisze, że nie zobowiązuje się do konkretnej lokalizacji przetwarzania. Do gwarancji UE służy osobny adres `api.eu.mistral.ai` (cena +10%). Źródło: <https://docs.mistral.ai/inference/regional-inference>. Katalog modeli w repozytorium używa dziś domyślnego adresu. **Zgłoś to Claude Code** przed włączeniem Mistrala w produkcji (potrzebna zmiana: adres UE w konfiguracji bramki). Do tego czasu traktuj Mistrala jako "do sprawdzenia" pod względem zasady "tylko UE".
- **Anthropic bezpośrednio** nie jest używany (rozdział 3.0).

---

## 1. Czego NIE robić

- **Nigdy nie wklejaj kluczy do czatu** (ani do Claude, ani do ChatGPT, ani do maila, ani na Slacka). Klucz w czacie = uznaj go za wyciekły i go usuń.
- **Nigdy nie commituj kluczy** do repozytorium, do `.env`, do `fly.toml`, do żadnego pliku w Gicie. Klucze trafiają tylko do `fly secrets set`.
- **Zawsze ustaw limit wydatków** u każdego dostawcy, **zanim** utworzysz klucz.
- **Nie używaj konta głównego AWS (root)** do niczego poza założeniem konta. Klucz dostępu robisz dla osobnego użytkownika IAM.
- **Nie wybieraj "Global"** przy wdrożeniach Azure ani prefiksów `us.` / `global.` przy Bedrock. To wysyła dane poza UE.
- **Nie używaj Alibaba/DashScope** (API Qwena od Alibaby) ani `api.openai.com` ani `api.anthropic.com`. Platforma ich blokuje.
- Klucza nie zapisujesz w notatkach ani zrzutach ekranu. Gdy klucz jest pokazany "tylko raz", skopiuj go prosto do terminala (rozdział 6).
- Nie ufaj mailom "z AWS/Azure/Mistral" z prośbą o klucz. Nikt z dostawców nigdy nie prosi o klucz.

---

## 2. Mistral (La Plateforme / Studio, UE)

Przybliżony koszt do eksperymentu: **ok. 20-60 EUR** (patrz szacunek w rozdziale 3.6: Mistral Large kosztuje wg strony <https://mistral.ai/pricing> ok. 0,5 USD za 1 mln tokenów wejścia i 1,5 USD za 1 mln wyjścia, +10% za endpoint UE). Ustaw limit **50 EUR / miesiąc**.

### 2.1 Konto i płatność

1. Wejdź na <https://console.mistral.ai> i załóż konto (**Sign up**), potwierdź e-mail.
2. Utwórz organizację (nazwa dowolna, np. `mgr-ibm`). Instrukcja Mistrala: "Create your organization" w <https://docs.mistral.ai/getting-started/quickstarts/admin/create-organization> (nie czytałem jej szczegółowo, **do sprawdzenia** nazwy pól).
3. Wejdź w **Admin Panel > Subscriptions > Billing**. Źródło: <https://docs.mistral.ai/admin/user-management-finops/billing>.
4. W sekcji **Payment methods** dodaj kartę. Wypełnij **Billing information**.
5. Klucze API są **nieaktywne**, dopóki nie ma karty. W sekcji **Credits** kliknij **Add credits** i dokup np. 20 EUR. Przełącznika "pay-as-you-go" nie znalazłem w dokumentacji: jeśli konsola go pokazuje, włącz go (**do sprawdzenia**).
6. **Auto Recharge** zostaw wyłączone (nie chcesz automatycznego doładowywania).

### 2.2 Limit wydatków (zrób to przed kluczem)

1. W **Admin Panel > Subscriptions > Billing** znajdź **Monthly spending limit (API and Vibe)** i ustaw np. **50** (limit całej organizacji).
2. Dodatkowo limit workspace: **Admin Panel > Subscriptions > Billing**, pod nazwą workspace kliknij **Set limit** (miesięczna kwota w USD). Druga strona dokumentacji podaje inną ścieżkę: **Administration > Workspaces > (workspace) > Settings > Monthly spending limit**. Użyj tej, którą widzisz w konsoli (**do sprawdzenia**, która jest aktualna).
3. Po przekroczeniu limitu API zwraca błąd 429 do następnego miesiąca. To jest twarda bariera (w odróżnieniu od AWS i Azure).

Źródła: <https://docs.mistral.ai/admin/workspaces/usage-limits>, <https://docs.mistral.ai/admin/quickstarts/manage-workspaces>.

### 2.3 Workspace i klucz API

1. **Admin Panel > Manage > Workspaces > Create workspace**, nazwa np. `bomagent-pilot`, **Create**. (Zalecenie Mistrala: osobny workspace na development i produkcję.)
2. Przejdź do **Studio > API keys**, wybierz workspace z listy rozwijanej.
3. Kliknij **Create new key**, nadaj nazwę (np. `gateway-pilot`).
4. **Skopiuj klucz od razu**, jest pokazany tylko raz. To jest Twój `MISTRAL_API_KEY`.

### 2.4 Które modele

Katalog w repozytorium używa wpisu `mistral-large-eu` z identyfikatorem `mistral/mistral-large-latest`. Aktualne modele wg <https://docs.mistral.ai/models/overview>: **Mistral Large 4** (open-weight), **Mistral Small 4**, **Ministral 3** (14B/8B/3B). Dokładne identyfikatory API sprawdź poleceniem (po wpięciu klucza do zmiennej w terminalu, nie w czacie):

```bash
curl https://api.eu.mistral.ai/v1/models -H "Authorization: Bearer $MISTRAL_API_KEY"
```

Dostępność modeli na endpoincie UE bywa węższa niż globalnie (<https://docs.mistral.ai/inference/regional-inference>): lista z tego polecenia jest wiążąca. Endpoint UE nie obsługuje m.in. Agents, Batch i Files API (tylko zwykłe wywołania i function calling), co platformie wystarcza.

### 2.5 Co skopiować

- `MISTRAL_API_KEY` = klucz z kroku 2.3.
- Adres UE `https://api.eu.mistral.ai/v1`: czy bramka przyjmie go przez zmienną środowiskową, czy trzeba zmienić konfigurację katalogu, **do sprawdzenia** (zgłoś to Claude Code, patrz rozdział 0).

### 2.6 Wpis do Fly

```bash
fly secrets set --app mgr-ibm-llm-gateway MISTRAL_API_KEY="<TU_WKLEJ_KLUCZ_MISTRAL>"
```

---

## 3. Claude (Anthropic) z przetwarzaniem w UE: AWS Bedrock

### 3.0 Czy Anthropic ma własne API tylko z UE? Nie

Fakty z oficjalnej dokumentacji (<https://platform.claude.com/docs/en/manage-claude/data-residency>, stan na dziś):

- Parametr `inference_geo` przyjmuje tylko `"global"` (domyślnie) i `"us"`. **Nie ma wartości `"eu"`.**
- Lokalizacja przechowywania danych (workspace geo): dostępna tylko `"us"`.
- Wniosek: bezpośrednie API Anthropic **nie daje przetwarzania wyłącznie w UE**. Dlatego go nie używamy. Claude w UE dostajemy przez **AWS Bedrock** z profilem `eu.` (kierowanie tylko do regionów UE).

### 3.1 Konto AWS (podstawy)

Założenie konta jest bezpłatne, ale wymagana jest karta.

1. <https://aws.amazon.com> > **Create an AWS account**, wybierz plan bez płatnego wsparcia.
2. Zaloguj się jako **Root user**. W prawym górnym rogu kliknij nazwę konta > **Security credentials** > **Multi-factor authentication (MFA)** > **Assign MFA device**, wybierz aplikację uwierzytelniającą (np. Google Authenticator), zeskanuj kod, wpisz dwa kolejne kody. **MFA na root jest obowiązkowe.** (Dokładne nazwy przycisków: **do sprawdzenia**, AWS je zmienia.)
3. Przełącz region na **Europe (Frankfurt) eu-central-1** (lista regionów w prawym górnym rogu konsoli). Pracuj tylko w nim.
4. Nie twórz kluczy dostępu dla root. Do codziennej pracy utwórz w **IAM > Users** użytkownika administracyjnego z MFA (lub użyj **IAM Identity Center**). Dokładne kliknięcia: **do sprawdzenia** w <https://docs.aws.amazon.com/IAM/latest/UserGuide/getting-started.html>.

### 3.2 Alarm budżetowy (nie jest twardym limitem!)

AWS Budgets tylko **wysyła ostrzeżenia**, nie zatrzymuje wydatków. Twardy limit zapewnia klucz wirtualny bramki (`max_budget`, patrz `llm-gateway-pilot.md`, krok 10). Źródło: <https://docs.aws.amazon.com/cost-management/latest/userguide/budget-templates.html>.

1. Konsola > wyszukaj **Billing and Cost Management** > w lewym menu **Budgets** > **Create budget**.
2. **Budget setup**: **Use a template (simplified)** > **Monthly cost budget**.
3. Wpisz nazwę, kwotę (np. **100** USD) i swój e-mail w polu odbiorców alertów.
4. **Create budget**.

### 3.3 Model Claude: dostęp (nie ma już strony "Model access")

W regionach komercyjnych AWS strona **Model access** nie jest potrzebna. Dostęp włącza się przy **pierwszym użyciu**. Źródło: <https://docs.aws.amazon.com/bedrock/latest/userguide/model-access.html>.

1. Otwórz konsolę **Amazon Bedrock** (region eu-central-1).
2. W lewym menu **Model catalog**. Wybierz model Anthropic (np. **Claude Sonnet 5.5**), kliknij **Open in playground**.
3. Dla modeli Anthropic pojawi się formularz **first-time use** (nazwa firmy, strona WWW, branża, opis zastosowania). Osoba bez firmy może podać stronę projektu lub profil GitHub. Wyślij formularz. Zwykle dostęp jest od razu, czasem status jest "pending" i przychodzi e-mail.
4. Wyślij w playground jedno krótkie "hello" (to uruchamia subskrypcję w AWS Marketplace; potrzebne uprawnienia `aws-marketplace:Subscribe` ma Twój użytkownik administracyjny, **nie** użytkownik bramki). Powtórz dla Opus i Haiku, jeśli chcesz je mieć.
5. Poczekaj do 15 minut, jeśli pierwszy test daje `AccessDeniedException`.

### 3.4 Profil UE: sprawdź, dokąd naprawdę trafia ruch

Identyfikatory modeli w katalogu: `bedrock/eu.anthropic.claude-sonnet-5-5` (analogicznie `...claude-opus-5-5`, `...claude-haiku-5-5`). Karta modelu Sonnet 5.5 (<https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-anthropic-claude-sonnet-5-5.html>) pokazuje, że profil `eu.` wywołany z Frankfurtu kieruje do: eu-central-1, eu-north-1, eu-south-1, eu-south-2, eu-west-1, eu-west-3 (wszystko kraje UE). Mimo to AWS zaleca sprawdzić to samemu (**to zadanie dla Claude Code lub terminala**, polecenie w `llm-gateway-pilot.md`, sekcja A pkt 3). Profile `us.` i `global.` są zabronione.

### 3.5 Użytkownik IAM tylko do wywołań modeli

1. Konsola > **IAM > Users > Create user**. Nazwa `bomagent-llm-gateway`. **Nie** zaznaczaj dostępu do konsoli.
2. Wybierz **Attach policies directly > Create policy > JSON** i wklej (podmień `<ACCOUNT_ID>` na 12-cyfrowy numer konta AWS; numer konta nie jest sekretem):

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
    "Resource": [
      "arn:aws:bedrock:eu-central-1:<ACCOUNT_ID>:inference-profile/eu.anthropic.*",
      "arn:aws:bedrock:*::foundation-model/anthropic.*",
      "arn:aws:bedrock:eu-central-1::foundation-model/qwen.*",
      "arn:aws:bedrock:eu-central-1::foundation-model/openai.*"
    ],
    "Condition": {
      "StringEquals": {
        "aws:RequestedRegion": ["eu-central-1","eu-north-1","eu-south-1","eu-south-2","eu-west-1","eu-west-3"]
      }
    }
  }]
}
```

   Zgodne z runbookiem: tylko `InvokeModel*`, tylko zasoby UE, warunek regionu. Wiersze `qwen.*` i `openai.*` są potrzebne dopiero w rozdziale 5A. Czy dokładnie ta składnia ARN przejdzie na Twoim koncie, **do sprawdzenia** przy pierwszym teście (błąd `AccessDenied` = trzeba poprawić ARN, zgłoś to Claude Code).
3. Nazwij politykę `bomagent-bedrock-invoke-eu`, dołącz do użytkownika, **Create user**.
4. Wejdź w użytkownika > **Security credentials** > **Create access key** > przypadek użycia **Application running outside AWS** > **Create access key**.
5. Skopiuj **Access key ID** i **Secret access key** (secret widoczny tylko raz). Jeśli pobierasz plik **.csv**, usuń go po wpisaniu kluczy do Fly.

### 3.6 Koszt (szacunek) i limit

Założenie szacunku (moje, nie wyliczone z Twoich danych): eksperyment ok. 1000 uruchomień po ok. 40 tys. tokenów wejścia i 8 tys. wyjścia (40 mln + 8 mln tokenów). Ceny z katalogu repozytorium to **placeholdery**, sprawdź aktualny cennik: <https://aws.amazon.com/bedrock/pricing/>.

| Model | Cena EUR / 1 mln tokenów (wej. / wyj.) | Szacunek miesięczny |
|---|---|---|
| Claude Haiku 5.5 | 0,1 / 0,5 | ok. 8 EUR |
| Claude Sonnet 5.5 | 1,85 / 9,25 | ok. 150 EUR |
| Claude Opus 5.5 | 3,7 / 18,5 | ok. 300 EUR |
| Mistral Large (Mistral, rozdz. 2) | ok. 0,5 / 1,5 USD, +10% UE | ok. 35 EUR |

Limit: alarm w AWS Budgets (3.2) **plus** `max_budget` w kluczu wirtualnym bramki (twardy limit). Na początek ustaw w bramce `max_budget` 20-50.

### 3.7 Co skopiować

- `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, region `eu-central-1`.

### 3.8 Wpis do Fly

```bash
fly secrets set --app mgr-ibm-llm-gateway \
  AWS_ACCESS_KEY_ID="<TU_WKLEJ_ACCESS_KEY_ID>" \
  AWS_SECRET_ACCESS_KEY="<TU_WKLEJ_SECRET_ACCESS_KEY>" \
  AWS_REGION_NAME="eu-central-1"
```

---

## 4. OpenAI w UE: Azure OpenAI (Data Zone EU)

### 4.0 Czy własne API OpenAI ma opcję UE? Tak, ale z warunkami

Fakty (<https://developers.openai.com/api/docs/guides/your-data>):

- Istnieje rezydencja danych **Europa (EOG + Szwajcaria)**, ustawiana **przy tworzeniu nowego projektu** (lista rozwijana regionu). Adres: `eu.api.openai.com`. Później regionu projektu nie zmienisz.
- Warunek: trzeba skontaktować się z **OpenAI sales** i mieć zatwierdzone m.in. Zero Data Retention albo Modified Abuse Monitoring (dodatkowy aneks). To nie jest opcja "klik i gotowe" dla pojedynczego dewelopera.
- Modele wydane po 5 marca 2026 mają +10% ceny za rezydencję.
- Platforma **nie ma** `eu.api.openai.com` na liście dozwolonych adresów. Dlatego do OpenAI używamy **Azure** (poniżej).

### 4.1 Subskrypcja Azure

1. <https://azure.microsoft.com/free> > załóż konto Azure (karta wymagana). Subskrypcja **Pay-as-you-go**.
2. Włącz MFA dla konta Microsoft (**Security info** na koncie Microsoft). Szczegóły: **do sprawdzenia**.
3. Dostęp do niektórych modeli OpenAI może wymagać zgłoszenia/zatwierdzenia. **Do sprawdzenia** w portalu przy wyborze modelu.

### 4.2 Zasób w regionie UE

Źródło: <https://learn.microsoft.com/en-us/azure/foundry-classic/openai/how-to/create-resource> (wersja "classic"; Microsoft przenosi się do "nowego Foundry", nazwy przycisków mogą się różnić, **do sprawdzenia**).

1. Portal <https://portal.azure.com> > **Create a resource** > wyszukaj **Azure OpenAI** > **Create**.
2. Zakładka **Basics**: **Subscription**, **Resource group** (nowa, np. `rg-bomagent-llm`), **Region** = `swedencentral` (lub `francecentral`, `germanywestcentral`), **Name** (np. `bomagent-openai-eu`), **Pricing Tier** = Standard.
3. **Network**: zostaw domyślnie. **Review + submit** > **Create** > **Go to resource**.
4. Uwaga: dostępność modeli w Data Zone zależy od regionu. Wątek na forum Microsoft (źródło niepewne) sugeruje, że dla gpt-5.4 region `swedencentral` mógł nie być na liście Data Zone EU. Sprawdź dostępność w oknie wdrożenia, a tabelę regionów zobacz tu: <https://learn.microsoft.com/en-us/azure/foundry/foundry-models/concepts/models-sold-directly-by-azure-region-availability>.

### 4.3 Wdrożenie modelu: tylko Data Zone Standard (EU)

1. Portal Foundry <https://ai.azure.com> > wybierz zasób > **Deployments** (lub **Models + endpoints**) > **+ Deploy model** > **Deploy base model** > wybierz model > **Confirm**.
2. **Deployment name**: wpisz `bomagent-gpt-eu-datazone` (tak oczekuje katalog repozytorium; inna nazwa = zmiana w katalogu).
3. **Deployment type**: wybierz **Data Zone Standard** (SKU `DataZoneStandard`, przetwarzanie w strefie UE). **Nigdy** "Global Standard" ani "Global-Batch". Jeśli Data Zone nie ma dla wybranego modelu/regionu, wybierz inny model lub region (**do sprawdzenia**: dokładne nazwy w interfejsie). Źródło: <https://learn.microsoft.com/en-us/azure/ai-foundry/foundry-models/concepts/deployment-types>. Uwaga: strefa UE obejmuje też kraje EFTA (np. Norwegia, Szwajcaria) wg Microsoftu.
4. **Tokens per Minute Rate Limit**: ustaw nisko (to także hamulec kosztów).
5. **Deploy**. Poczekaj na stan **Succeeded**.

### 4.4 Klucz i adres

1. Portal Azure > Twój zasób > **Keys and Endpoint** (położenie w menu: **do sprawdzenia**).
2. Skopiuj **KEY 1** i **Endpoint** w formie `https://<nazwa-zasobu>.openai.azure.com`.

### 4.5 Limit wydatków

Azure **nie ma twardego limitu** przy płatności "pay-as-you-go". Zrób **Cost Management > Budgets > Add** z alertem e-mail (np. 50 EUR) i limit TPM na wdrożeniu (4.3). Dokładna ścieżka w portalu: **do sprawdzenia**. Twardy hamulec: `max_budget` w kluczu wirtualnym bramki.

### 4.6 Koszt (szacunek)

Cennik modeli OpenAI na Azure: **do sprawdzenia** na <https://azure.microsoft.com/pricing/details/cognitive-services/openai-service/> (w katalogu jest 0,0 jako placeholder). Planuj budżet **30-100 EUR / miesiąc** i ustaw alert na ten poziom (to tylko zgrubne założenie, nie wyliczenie).

### 4.7 Wpis do Fly

```bash
fly secrets set --app mgr-ibm-llm-gateway \
  AZURE_API_KEY="<TU_WKLEJ_KEY_1>" \
  AZURE_API_BASE="https://<NAZWA_ZASOBU>.openai.azure.com"
```

---

## 5. Qwen i inne modele open-weight

### 5A. Hostowane na Bedrock w UE (to samo konto AWS co w rozdziale 3)

Wg kart modeli AWS (<https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-qwen-qwen3-235b-a22b-2507.html>):

- **Qwen3 235B A22B 2507**: ID `qwen.qwen3-235b-a22b-2507-v1:0`, dostępny **in-region** (bez przekierowań) w eu-central-1 (Frankfurt), eu-north-1 (Sztokholm), eu-south-1 (Mediolan). Profilu geograficznego `eu.` dla niego nie ma, więc używa się ID bez prefiksu i regionu eu-central-1.
- **gpt-oss-120b / gpt-oss-20b** (OpenAI open-weight): ID `openai.gpt-oss-120b-1:0` / `openai.gpt-oss-20b-1:0`. Tabele AWS wymieniają eu-central-1 i eu-north-1, ale dostępność on-demand **do sprawdzenia** na karcie modelu w Twoim koncie (<https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-openai-gpt-oss-20b.html>).
- Qwen, Mistral, Meta i gpt-oss **nie wymagają subskrypcji AWS Marketplace** (wg <https://docs.aws.amazon.com/bedrock/latest/userguide/model-access.html>), więc zwykle działają od razu po pierwszym wywołaniu.

Kroki:

1. Ten sam użytkownik IAM i ta sama polityka co w 3.5 (wiersze `qwen.*` i `openai.*` już tam są).
2. Konsola Bedrock (eu-central-1) > **Model catalog** > **Qwen3 235B A22B 2507** (lub gpt-oss) > **Open in playground** > wyślij "hello". Jeśli model nie jest widoczny we Frankfurcie, **nie** przełączaj się na region spoza UE. Użyj eu-north-1 (wtedy zmień też `region` we wpisie katalogu i w AWS_REGION_NAME dla tego modelu, **do sprawdzenia** z Claude Code).
3. Zgłoś Claude Code dokładne ID, aby włączył wpis w katalogu (`enabled: true`, `verified: true`) po sprawdzeniu.
4. Własne API Alibaby (DashScope) jest zablokowane. Mistral nie hostuje Qwena (runbook).

Koszt: cennik per token na <https://aws.amazon.com/bedrock/pricing/> (**do sprawdzenia**; w katalogu 0,0 jako placeholder). Zgrubnie zaplanuj **10-40 EUR / miesiąc** (założenie, nie wyliczenie). Limit: jak w 3.2 i 3.6.

Wpis do Fly: **te same klucze AWS co w 3.8** (nic dodatkowego).

### 5B. Lokalnie na Macu: Ollama (za darmo, tylko nauka i testy)

Źródło: `docs/platform/runbooks/local-models.md` (na gałęzi `feat/llm-gateway-pilot`; tabela rozmiarów tam jest sprawdzona na stronach biblioteki Ollama 2026-11-12). Dane nie opuszczają Maca. **Nie działa z pilotem na Fly**: Fly nie ma jak połączyć się z Twoim laptopem, a tunel odsłaniałby Twój komputer.

1. Otwórz **Terminal** i wpisz po kolei:
   ```bash
   brew install ollama
   brew services start ollama
   ollama pull qwen3:8b
   ollama run qwen3:8b "say hi"
   ```
   (wyjście z czatu: wpisz `/bye`).
2. Sprawdź, czy API działa: `curl -s http://localhost:11434/v1/models | head`.
3. Jeśli nie masz Homebrew: <https://brew.sh> (instalacja jedną komendą ze strony).

Ile pamięci RAM potrzeba (zostaw 6-8 GB dla macOS):

| Model (tag Ollama) | Pobieranie | Ok. RAM | 16 GB | 32 GB | 64 GB |
|---|---|---|---|---|---|
| `ministral-3:8b` | 6,0 GB | 9 GB | tak | tak | tak |
| `qwen3:8b` | 5,2 GB | 8 GB | tak | tak | tak |
| `llama3.1:8b` | 4,9 GB | 8 GB | tak | tak | tak |
| `qwen3:14b` | 9,3 GB | 12 GB | na styk | tak | tak |
| `gpt-oss:20b` | 14 GB | 16 GB | nie | tak | tak |
| `mistral-small:24b` | 14 GB | 18 GB | nie | tak | tak |

Prawdziwe zużycie sprawdź komendą `ollama ps`. Koszt: **0 EUR** (prąd i miejsce na dysku). Limit wydatków i klucz: nie dotyczy. Włączenie lokalnego wpisu w katalogu opisuje runbook (plik override poza repozytorium), nie edytujesz `models.yaml`.

---

## 6. Jak wpisać klucze do bramki (`fly secrets`)

Wszystkie wartości poniżej to **zmienne w nawiasach ostrych**. Prawdziwe wartości wpisujesz tylko w swoim terminalu, nigdy w czacie ani w pliku.

Jednorazowo, tylko dla dostawców, których używasz:

```bash
fly secrets set --app mgr-ibm-llm-gateway \
  LITELLM_MASTER_KEY="sk-<LOSOWY_CIAG_ZNAKOW>" \
  MISTRAL_API_KEY="<TU_WKLEJ_KLUCZ_MISTRAL>" \
  AZURE_API_KEY="<TU_WKLEJ_KEY_1>" \
  AZURE_API_BASE="https://<NAZWA_ZASOBU>.openai.azure.com" \
  AWS_ACCESS_KEY_ID="<TU_WKLEJ_ACCESS_KEY_ID>" \
  AWS_SECRET_ACCESS_KEY="<TU_WKLEJ_SECRET_ACCESS_KEY>" \
  AWS_REGION_NAME="eu-central-1"
```

- `LITELLM_MASTER_KEY` musi zaczynać się od `sk-`. Losowy ciąg wygeneruj lokalnie: `openssl rand -hex 32`.
- Baza `DATABASE_URL` dla kluczy wirtualnych i budżetów: patrz `llm-gateway-pilot.md`, kroki 5-6.
- Po zmianie sekretów Fly zrestartuje aplikację. Dalsze kroki (włączenie modeli w katalogu, deploy bramki, klucz wirtualny, przełączenie aplikacji): `llm-gateway-pilot.md`, sekcje C-E. Włączenie wpisów w katalogu (`enabled`/`verified`) robi się przez PR, zwykle z pomocą Claude Code.
- Sprawdzenie, jakie sekrety są ustawione (bez pokazywania wartości): `fly secrets list --app mgr-ibm-llm-gateway`.

---

## 7. Tabela końcowa: co mam / czego brakuje

Wpisz "tak/nie" i datę. Nie wpisuj tu żadnych wartości kluczy.

| Pozycja | Mam? | Brakuje / uwagi |
|---|---|---|
| **Mistral**: konto, organizacja | | |
| Mistral: karta + kredyty | | |
| Mistral: limit miesięczny (organizacja + workspace) | | |
| Mistral: workspace + klucz (`MISTRAL_API_KEY`) | | |
| Mistral: lista modeli sprawdzona na `api.eu.mistral.ai` | | zgłoś Claude Code adres UE |
| **AWS**: konto + MFA na root | | |
| AWS: region eu-central-1, alarm w Budgets | | |
| AWS: formularz first-time use (Anthropic) + test w playground | | |
| AWS: sprawdzone miejsca docelowe profilu `eu.` | | |
| AWS: użytkownik IAM `bomagent-llm-gateway` + polityka | | |
| AWS: klucz dostępu (ID + secret) | | |
| Bedrock: Qwen3 235B / gpt-oss przetestowane w playground | | opcjonalnie |
| **Azure**: subskrypcja + MFA | | |
| Azure: zasób w `swedencentral`/`francecentral` | | |
| Azure: wdrożenie `bomagent-gpt-eu-datazone` = Data Zone Standard | | |
| Azure: klucz + endpoint, budżet w Cost Management | | |
| **Ollama**: zainstalowana, model pobrany | | opcjonalnie, tylko lokalnie |
| `fly secrets set` dla bramki wykonane | | |
| `LITELLM_MASTER_KEY` wygenerowany | | |
| Wpisy w katalogu włączone (PR) i bramka wdrożona | | `llm-gateway-pilot.md` C-D |

## Źródła użyte w tej instrukcji

- Mistral: <https://docs.mistral.ai/inference/regional-inference>, <https://docs.mistral.ai/admin/user-management-finops/billing>, <https://docs.mistral.ai/admin/quickstarts/manage-workspaces>, <https://docs.mistral.ai/admin/workspaces/usage-limits>, <https://docs.mistral.ai/models/overview>, <https://mistral.ai/pricing>
- Anthropic: <https://platform.claude.com/docs/en/manage-claude/data-residency>
- AWS: <https://docs.aws.amazon.com/bedrock/latest/userguide/model-access.html>, <https://docs.aws.amazon.com/bedrock/latest/userguide/inference-profiles-support.html>, <https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-anthropic-claude-sonnet-5-5.html>, <https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-qwen-qwen3-235b-a22b-2507.html>, <https://docs.aws.amazon.com/cost-management/latest/userguide/budget-templates.html>
- OpenAI: <https://developers.openai.com/api/docs/guides/your-data>
- Azure: <https://learn.microsoft.com/en-us/azure/ai-foundry/foundry-models/concepts/deployment-types>, <https://learn.microsoft.com/en-us/azure/foundry-classic/openai/how-to/create-resource>, <https://learn.microsoft.com/azure/foundry/tutorials/quickstart-create-foundry-resources>
- Repozytorium: `docs/adr/0006-llm-gateway-eu-providers.md`, `docs/platform/SECURITY.md`, `packages/py/llm/src/bomagent_llm/catalog/models.yaml`, `docs/platform/runbooks/llm-gateway-pilot.md`, `docs/platform/runbooks/local-models.md` (gałąź `feat/llm-gateway-pilot`)
