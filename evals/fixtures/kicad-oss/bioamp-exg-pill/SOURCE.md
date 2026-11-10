# BioAmp EXG Pill (Upside Down Labs) - unmodified copy

| Field | Value |
|---|---|
| Source | https://github.com/upsidedownlabs/BioAmp-EXG-Pill |
| Commit | 86bb1f45575054b4b9af78517c24ad682c3a65b6 (2024-08-23) |
| Retrieved | 2026-11-10 |
| Files | `hardware/BioAmp-EXG-Pill.kicad_sch`, `.kicad_pro`, `.kicad_pcb` (KiCad 6, 20211123), `hardware/BioAmp-EXG-Pill.sch` (KiCad 5 legacy) |
| Licence | Hardware: CERN-OHL-S v2 (strongly reciprocal); software: MIT - see `LICENSE.md` (copied verbatim) |

Files are kept **unmodified** (CERN-OHL-S: modifications shared further must keep the
licence). Error injection works on in-memory copies or `evals/fixtures/_mutations/`.

No reference BOM yet: the project's interactive BOM (`hardware/bom/ibom.html`) lists
values/footprints but no MPNs; a reference BOM must be built and **verified by a human**
before this design is used for thesis metrics (`docs/thesis/ZBIOR_EWALUACYJNY_KANDYDACI.md`).
Values `RG`, `BPFC_C`, `BPFC_R` are assembly-time placeholders (gain / band-pass values
chosen by the user) - a realistic case for the validation rules.
