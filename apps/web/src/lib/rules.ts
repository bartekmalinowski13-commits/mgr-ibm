import i18n from "../i18n";

/* Short, human titles of rule ids (rule ids contain dots, so they live outside i18next keys).
 * The backend message (English, with specifics) is shown under the title. */
const TITLES: Record<"pl" | "en", Record<string, string>> = {
  pl: {
    "schema.valid": "Pozycja zgodna ze schematem BOM",
    "schema.coerced": "Odpowiedź agenta poprawiona, by zapisać BOM",
    "refdes.unique": "Każde oznaczenie tylko w jednej pozycji",
    "quantity.matches_refdes": "Ilość równa liczbie oznaczeń",
    "footprint.present": "Montowana część ma footprint",
    "mpn.present": "Montowana część ma MPN i producenta",
    "value.parsable": "Wartość elementu biernego poprawna",
    "value.zero_ohm": "Zworka 0 Ω",
    "footprint.package_match": "Obudowa zgodna z footprintem",
    "capacitor.voltage_rating": "Znane napięcie kondensatora",
    "iec60601.isolation_barrier": "IEC 60601: elementy bariery izolacyjnej",
    "iec60601.patient_connector": "IEC 60601: połączenie z pacjentem",
    "iec60601.mains": "IEC 60601: zabezpieczenia sieciowe",
    "iec60601.battery": "IEC 60601: baterie i akumulatory",
    "agents.no_part_selected": "Agent nie wybrał części",
    "kb.mpn_known": "MPN potwierdzony w bazie wiedzy",
    "agent.validate": "Uwaga agenta walidującego",
  },
  en: {
    "schema.valid": "Line matches the BOM schema",
    "schema.coerced": "Agent output coerced to save the BOM",
    "refdes.unique": "Each designator on exactly one line",
    "quantity.matches_refdes": "Quantity equals designator count",
    "footprint.present": "Fitted part has a footprint",
    "mpn.present": "Fitted part has MPN and manufacturer",
    "value.parsable": "Passive value is valid",
    "value.zero_ohm": "0 Ω jumper",
    "footprint.package_match": "Package agrees with footprint",
    "capacitor.voltage_rating": "Capacitor voltage is known",
    "iec60601.isolation_barrier": "IEC 60601: isolation barrier parts",
    "iec60601.patient_connector": "IEC 60601: patient connection",
    "iec60601.mains": "IEC 60601: mains protection",
    "iec60601.battery": "IEC 60601: batteries",
    "agents.no_part_selected": "Agent selected no part",
    "kb.mpn_known": "MPN confirmed in the knowledge base",
    "agent.validate": "Validator agent remark",
  },
};

export function ruleTitle(ruleId: string): string | undefined {
  const lang = i18n.language?.startsWith("en") ? "en" : "pl";
  return TITLES[lang][ruleId];
}
