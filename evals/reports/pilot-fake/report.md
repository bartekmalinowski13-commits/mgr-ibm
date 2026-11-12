# Experiment `pilot-fake`

## Configuration

- designs: ecg-frontend, pulse-ox, eeg-2ch
- variants: A, B; models: fake-closed, fake-open-weight; repetitions: 3; seed: 2026
- reproducibility: commit, prompt versions and rule pack in `manifest.json`

## Results per variant

Mean with 95 % bootstrap interval over runs.

| variant | model | runs | line_f1 | line_precision | line_recall | designator_f1 | acc_mpn | acc_value | mpn_coverage | mpn_out_of_reference_rate | mpn_hallucination_rate | llm_calls | input_tokens | output_tokens | cost_eur | wall_time_s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | fake-closed | 9 | 0.976 [0.963; 0.990] | 0.955 [0.929; 0.980] | 1.000 | 1.000 | 0.778 [0.726; 0.831] | 1.000 | 0.963 [0.926; 1.000] | 0.000 | 0.000 | 16 [12; 20] | 24 428 [17 699; 31 319] | 2 022 [1 529; 2 554] | 0.0000 | 0.07 [0.05; 0.10] |
| A | fake-open-weight | 9 | 0.976 [0.963; 0.990] | 0.955 [0.929; 0.980] | 1.000 | 1.000 | 0.778 [0.726; 0.831] | 1.000 | 0.963 [0.926; 1.000] | 0.000 | 0.000 | 16 [12; 20] | 24 428 [17 699; 31 319] | 2 022 [1 529; 2 554] | 0.0000 | 0.06 [0.05; 0.07] |
| B | fake-closed | 9 | 0.976 [0.963; 0.990] | 0.955 [0.929; 0.980] | 1.000 | 1.000 | 0.858 [0.828; 0.890] | 1.000 | 1.000 | 0.000 | 0.000 | 4 [2; 5] | 7 210 [4 474; 9 835] | 274 [169; 371] | 0.0000 | 0.04 [0.04; 0.05] |
| B | fake-open-weight | 9 | 0.976 [0.963; 0.990] | 0.955 [0.929; 0.980] | 1.000 | 1.000 | 0.858 [0.828; 0.890] | 1.000 | 1.000 | 0.000 | 0.000 | 4 [2; 5] | 7 210 [4 474; 9 835] | 274 [169; 371] | 0.0000 | 0.05 [0.04; 0.05] |

## A vs B (paired)

### fake-closed

Pairs are designs, each the mean over its repetitions (repetitions of one design are not independent). Difference B - A; p: two-sided exact paired permutation test - with n designs the smallest attainable p is 2 / 2^n.

| metric | better | n | A | B | B - A [95 % CI] | p | B better / A better / ties |
|---|---|---|---|---|---|---|---|
| line_f1 | higher | 3 | 0.976 | 0.976 | 0.000 [0.000; 0.000] | 1.0000 | 0 / 0 / 3 |
| line_precision | higher | 3 | 0.955 | 0.955 | 0.000 [0.000; 0.000] | 1.0000 | 0 / 0 / 3 |
| line_recall | higher | 3 | 1.000 | 1.000 | 0.000 [0.000; 0.000] | 1.0000 | 0 / 0 / 3 |
| designator_f1 | higher | 3 | 1.000 | 1.000 | 0.000 [0.000; 0.000] | 1.0000 | 0 / 0 / 3 |
| acc_mpn | higher | 3 | 0.778 | 0.858 | 0.080 [0.038; 0.111] | 0.2500 | 3 / 0 / 0 |
| acc_value | higher | 3 | 1.000 | 1.000 | 0.000 [0.000; 0.000] | 1.0000 | 0 / 0 / 3 |
| mpn_coverage | higher | 3 | 0.963 | 1.000 | 0.037 [0.000; 0.111] | 1.0000 | 1 / 0 / 2 |
| mpn_out_of_reference_rate | lower | 3 | 0.000 | 0.000 | 0.000 [0.000; 0.000] | 1.0000 | 0 / 0 / 3 |
| mpn_hallucination_rate | lower | 3 | 0.000 | 0.000 | 0.000 [0.000; 0.000] | 1.0000 | 0 / 0 / 3 |
| llm_calls | lower | 3 | 16 | 4 | -12 [-18; -9] | 0.2500 | 3 / 0 / 0 |
| input_tokens | lower | 3 | 24 428 | 7 210 | -17 218 [-26 981; -12 115] | 0.2500 | 3 / 0 / 0 |
| output_tokens | lower | 3 | 2 022 | 274 | -1 748 [-2 684; -1 214] | 0.2500 | 3 / 0 / 0 |
| cost_eur | lower | 3 | 0.0000 | 0.0000 | 0.0000 [0.0000; 0.0000] | 1.0000 | 0 / 0 / 3 |
| wall_time_s | lower | 3 | 0.07 | 0.04 | -0.03 [-0.06; -0.00] | 0.2500 | 3 / 0 / 0 |

### fake-open-weight

Pairs are designs, each the mean over its repetitions (repetitions of one design are not independent). Difference B - A; p: two-sided exact paired permutation test - with n designs the smallest attainable p is 2 / 2^n.

| metric | better | n | A | B | B - A [95 % CI] | p | B better / A better / ties |
|---|---|---|---|---|---|---|---|
| line_f1 | higher | 3 | 0.976 | 0.976 | 0.000 [0.000; 0.000] | 1.0000 | 0 / 0 / 3 |
| line_precision | higher | 3 | 0.955 | 0.955 | 0.000 [0.000; 0.000] | 1.0000 | 0 / 0 / 3 |
| line_recall | higher | 3 | 1.000 | 1.000 | 0.000 [0.000; 0.000] | 1.0000 | 0 / 0 / 3 |
| designator_f1 | higher | 3 | 1.000 | 1.000 | 0.000 [0.000; 0.000] | 1.0000 | 0 / 0 / 3 |
| acc_mpn | higher | 3 | 0.778 | 0.858 | 0.080 [0.038; 0.111] | 0.2500 | 3 / 0 / 0 |
| acc_value | higher | 3 | 1.000 | 1.000 | 0.000 [0.000; 0.000] | 1.0000 | 0 / 0 / 3 |
| mpn_coverage | higher | 3 | 0.963 | 1.000 | 0.037 [0.000; 0.111] | 1.0000 | 1 / 0 / 2 |
| mpn_out_of_reference_rate | lower | 3 | 0.000 | 0.000 | 0.000 [0.000; 0.000] | 1.0000 | 0 / 0 / 3 |
| mpn_hallucination_rate | lower | 3 | 0.000 | 0.000 | 0.000 [0.000; 0.000] | 1.0000 | 0 / 0 / 3 |
| llm_calls | lower | 3 | 16 | 4 | -12 [-18; -9] | 0.2500 | 3 / 0 / 0 |
| input_tokens | lower | 3 | 24 428 | 7 210 | -17 218 [-26 981; -12 115] | 0.2500 | 3 / 0 / 0 |
| output_tokens | lower | 3 | 2 022 | 274 | -1 748 [-2 684; -1 214] | 0.2500 | 3 / 0 / 0 |
| cost_eur | lower | 3 | 0.0000 | 0.0000 | 0.0000 [0.0000; 0.0000] | 1.0000 | 0 / 0 / 3 |
| wall_time_s | lower | 3 | 0.06 | 0.05 | -0.01 [-0.02; 0.00] | 0.5000 | 2 / 1 / 0 |

## Validation effectiveness (error injection)

5 errors injected into each reference BOM, 3 different mutations per design; A and B review the same faulty BOMs. Detected = a new finding on the affected line naming the field or a matching rule (variant-neutral); false alarm = a new finding matching no error.

| variant | model | trials | injected | detected | detection rate [95 % CI] | false alarm rate |
|---|---|---|---|---|---|---|
| A | fake-closed | 9 | 45 | 21 | 0.467 [0.311; 0.622] | 0.000 |
| A | fake-open-weight | 9 | 45 | 21 | 0.467 [0.311; 0.622] | 0.000 |
| B | fake-closed | 9 | 45 | 45 | 1.000 [1.000; 1.000] | 0.032 |
| B | fake-open-weight | 9 | 45 | 45 | 1.000 [1.000; 1.000] | 0.032 |

| variant | model | error kind | injected | detected |
|---|---|---|---|---|
| A | fake-closed | drop_footprint | 12 | 12 |
| A | fake-closed | drop_mpn | 9 | 9 |
| A | fake-closed | duplicate_refdes | 9 | 0 |
| A | fake-closed | footprint_size_swap | 5 | 0 |
| A | fake-closed | invalid_value | 2 | 0 |
| A | fake-closed | quantity_off_by_one | 8 | 0 |
| A | fake-open-weight | drop_footprint | 12 | 12 |
| A | fake-open-weight | drop_mpn | 9 | 9 |
| A | fake-open-weight | duplicate_refdes | 9 | 0 |
| A | fake-open-weight | footprint_size_swap | 5 | 0 |
| A | fake-open-weight | invalid_value | 2 | 0 |
| A | fake-open-weight | quantity_off_by_one | 8 | 0 |
| B | fake-closed | drop_footprint | 12 | 12 |
| B | fake-closed | drop_mpn | 9 | 9 |
| B | fake-closed | duplicate_refdes | 9 | 9 |
| B | fake-closed | footprint_size_swap | 5 | 5 |
| B | fake-closed | invalid_value | 2 | 2 |
| B | fake-closed | quantity_off_by_one | 8 | 8 |
| B | fake-open-weight | drop_footprint | 12 | 12 |
| B | fake-open-weight | drop_mpn | 9 | 9 |
| B | fake-open-weight | duplicate_refdes | 9 | 9 |
| B | fake-open-weight | footprint_size_swap | 5 | 5 |
| B | fake-open-weight | invalid_value | 2 | 2 |
| B | fake-open-weight | quantity_off_by_one | 8 | 8 |

Paired (designs), fake-closed:

- detection_rate: A 0.467, B 1.000, B - A 0.533 [0.333; 0.667], p 0.2500, n 3
- false_alarm_rate: A 0.000, B 0.032, B - A 0.032 [0.000; 0.048], p 0.5000, n 3

Paired (designs), fake-open-weight:

- detection_rate: A 0.467, B 1.000, B - A 0.533 [0.333; 0.667], p 0.2500, n 3
- false_alarm_rate: A 0.000, B 0.032, B - A 0.032 [0.000; 0.048], p 0.5000, n 3

## Figures and tables

`figures/*.svg` (quality with intervals, paired line F1 per design, cost, validation on injected errors) and `tables/*.csv` (per-variant estimates, paired tests, detection per error kind) are generated from the same records.

## Repeatability

Mean pairwise agreement of decisions (value, MPN per designator) between repetitions.

| variant | model | agreement |
|---|---|---|
| A | fake-closed | 1.000 |
| A | fake-open-weight | 1.000 |
| B | fake-closed | 1.000 |
| B | fake-open-weight | 1.000 |

Run statuses: `{"A/fake-closed": {"completed": 9}, "A/fake-open-weight": {"completed": 9}, "B/fake-closed": {"completed": 9}, "B/fake-open-weight": {"completed": 9}}`
