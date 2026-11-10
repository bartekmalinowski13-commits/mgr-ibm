# Zbiór ewaluacyjny – kandydaci (otwarte projekty urządzeń biomedycznych)

Status: **lista robocza** (2026-11-09, przegląd nocny). Każdą pozycję przed użyciem trzeba sprawdzić w repozytorium źródłowym: plik LICENSE, wersja KiCad, obecność BOM. Kolumna „Pewność” mówi, co zostało już potwierdzone w źródłach.

## Kryteria doboru
1. Pliki źródłowe EDA dostępne (priorytet: KiCad 6–9; KiCad 5 jako test formatu legacy).
2. Licencja otwarta, pozwalająca trzymać kopię w repo jako fixture (zachować oryginalny LICENSE obok plików).
3. Dostępny BOM producenta albo możliwość wiarygodnego zbudowania BOM referencyjnego (np. z pól MPN w schemacie + ręczna weryfikacja).
4. Zróżnicowana złożoność: mały (< 40 komponentów), średni (40–150), duży (> 150).
5. Zróżnicowany typ urządzenia: biopotencjały (EKG/EEG/EMG), PPG/pulsoksymetria, urządzenia o wyższym ryzyku (AED, wentylator) – te ostatnie są cenne dla reguł IEC 60601.

## Kandydaci – KiCad
| Projekt | Typ | Złożoność (szac.) | Licencja sprzętu | BOM | Pewność | Źródło |
|---|---|---|---|---|---|---|
| Upside Down Labs **BioAmp EXG Pill** | AFE biopotencjałów (EKG/EMG/EOG/EEG), 1 kanał | mała | CERN-OHL-S-2.0 | sprawdzić | KiCad ✔, licencja ✔ | github.com/upsidedownlabs/BioAmp-EXG-Pill |
| Upside Down Labs **Muscle BioAmp BisCute** | EMG, elementy przewlekane | mała | CERN-OHL-S v2 | sprawdzić | KiCad ✔, licencja ✔ | GitHub Upside Down Labs |
| Upside Down Labs **BioAmp EMG Pill** | EMG | mała | CERN-OHL-S | sprawdzić | KiCad ✔, licencja ✔ | GitHub Upside Down Labs |
| **Card/IO** | jednoodprowadzeniowe EKG w formacie wizytówki, ESP32 | średnia | **do sprawdzenia** (firmware: MIT) | sprawdzić | KiCad 7 ✔ | github.com/card-io-ecg/card-io-hw |
| OpenBCI **Ganglion** | 4 kanały EEG/EMG/EKG, BLE | średnia | dokumentacja OpenBCI: MIT; OSHWA: „Other” – sprawdzić LICENSE w repo | ✔ (BOM z pierwszej serii) | KiCad ✔ | github.com/OpenBCI/Ganglion_Hardware_Design_Files |
| ProtoCentral **HealthyPi Move** | noszony monitor wieloparametrowy (nRF5340 + płytka sensorów) | duża | CERN-OHL-P v2 | sprawdzić | KiCad ✔ (najnowsze wersje), licencja ✔ | github.com/Protocentral/healthypi-move-hw |
| **dcmini** | EEG/EMG 4–16 kanałów (ADS1299, nRF52840, nPM1300) | duża | CERN-OHL-P v2 | sprawdzić | licencja ✔, format do sprawdzenia | github.com/dcmini-org/dcmini-hw |
| ProtoCentral **HealthyPi 6** | wieloparametrowy (EKG, PPG, oddech, temperatura), STM32H7 | duża | CERN-OHL v2 (zapowiedź) | – | pliki publikowane przy wysyłce – sprawdzić dostępność | Crowd Supply / GitHub Protocentral |
| Silicon Witchery **S1 ECG Kit** | EKG (AD8233) | mała | do sprawdzenia | sprawdzić | KiCad **5.1** – test formatu legacy | github.com/siliconwitchery/s1-ecg-demo |

## Kandydaci – inne formaty (do M7 i testów konwersji)
| Projekt | Format | Licencja | Uwagi |
|---|---|---|---|
| **HackEEG** (ADS1299, shield Arduino Due) | EAGLE | OSHWA US000027; dokumentacja CC BY-SA | EAGLE poza listą formatów v1; KiCad potrafi importować EAGLE – możliwy test ścieżki „konwersja → KiCad” |
| **Adam-EEG** (4× ADS1299) | EAGLE | Apache-2.0 | duży projekt EEG |
| OpenBCI **Cyton** | DesignSpark | MIT (dokumentacja OpenBCI) | BOM i Gerbery dostępne; dobry przykład „mamy tylko BOM + PDF schematu” → test ścieżki PDF |
| SparkFun **AD8232 Heart Rate Monitor** | do sprawdzenia | CC BY-SA | klasyczny breakout EKG |
| **Open-AED** (Centro E. Piaggio, HardwareX 2017) | do sprawdzenia | CC BY-SA 3.0 | urządzenie wysokiego ryzyka – cenne dla reguł bezpieczeństwa |

## Odrzucone / ostrożnie
- **Open Ventilator (Medtronic PB560 → KiCad)** – pliki pochodzą z udostępnienia na warunkach licencji Medtronic z ograniczeniami, bez BOM; nie używać bez analizy licencji.
- Projekty bez pliku LICENSE (np. liczne repozytoria hobbystyczne z AD8232/MAX30102) – domyślnie „wszystkie prawa zastrzeżone”.

## Rekomendacja na start (M1)
1. **Mały:** BioAmp EXG Pill – szybki test parsera i reguł.
2. **Średni:** OpenBCI Ganglion (ma BOM producenta – gotowa referencja).
3. **Duży:** HealthyPi Move.
4. **Kontrolny, własny:** 2–3 małe projekty KiCad przygotowane samodzielnie (np. z zajęć laboratoryjnych z projektowania PCB – tylko za zgodą autorów) z ręcznie zweryfikowanym BOM; pozwalają wstrzykiwać kontrolowane błędy (zły footprint, brak MPN, komponent wycofany) do oceny walidacji.

## Zasady przechowywania
`evals/fixtures/<projekt>/` – kopia plików z przypiętym commitem źródła, oryginalny `LICENSE`, `SOURCE.md` (URL, commit, data pobrania, licencja), `reference_bom.csv` (opis sposobu weryfikacji). Licencje CERN-OHL-S są wzajemne: modyfikacje plików projektu udostępniane dalej muszą zachować tę licencję – nie modyfikujemy fixture’ów, błędy wstrzykujemy w kopiach w `evals/fixtures/_mutations/` z tą samą licencją.

## Przydatne do rozdziału 2 / 3 pracy
- „AD8232 to Biopotentials Sensors: Open Source Project and Benchmark”, *Electronics* (MDPI), luty 2023 – otwarte płytki biopotencjałów z benchmarkiem.
- „Open-source automated external defibrillator”, *HardwareX*, październik 2017.
- Przegląd otwartej elektroniki w urządzeniach medycznych: *Electronics* 2019, 8(11), 1256 (MDPI).
