# bomagent-rules (`bomagent_rules`)

**Responsibility:** deterministic, versioned validation of BOMs (variant B validator; also
used to grade variant A outputs). Pure domain code.

## Public interface
- `validate(bom, requirements) -> ValidationReport` (default pack `core@1.0.0`)
- `run_pack(pack, bom, RuleContext, only=...)`, `PACKS`, `RulePack`, `Rule`
- Every `Finding` carries `rule_pack` + `rule_pack_version` (provenance, ADR-0011)

## Pack `core` 1.0.0
| Rule | Severity | Finding codes |
|---|---|---|
| JSON Schema of each line | error | `schema.valid` |
| designator on one line only | error | `refdes.unique` |
| quantity = number of designators | error | `quantity.matches_refdes` |
| fitted parts have a footprint | error | `footprint.present` |
| MPN + manufacturer present | warning | `mpn.present`, `manufacturer.present` |
| passive values valid and in range | error/info | `value.parsable`, `value.range`, `value.zero_ohm` |
| footprint package = MPN / value / description size | error | `footprint.package_match` |
| capacitor voltage known | warning | `capacitor.voltage_rating` |
| IEC 60601-1 checklist (flags for a human reviewer) | review | `iec60601.isolation_barrier`, `iec60601.patient_connector`, `iec60601.mains_fuse`, `iec60601.y_capacitor`, `iec60601.battery` |

IEC 60601 rules are **review flags**, not compliance verdicts; they depend on
`Requirements` (applied part type, defibrillation-proof, power source). A new pack version
is a new `RulePack` object - old versions stay available for reproducing experiments.

## Testing
`uv run pytest packages/py/rules`; `packages/py/eval/tests` checks that the pack detects
100 % of injected errors.
