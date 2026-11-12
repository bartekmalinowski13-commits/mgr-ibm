import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import en from "../locales/en.json";
import pl from "../locales/pl.json";

const KEY = "bomagent.lang";

function initial(): "pl" | "en" {
  try {
    const saved = localStorage.getItem(KEY);
    if (saved === "pl" || saved === "en") return saved;
  } catch {
    /* no storage */
  }
  return navigator.language.toLowerCase().startsWith("pl") ? "pl" : "en";
}

void i18n.use(initReactI18next).init({
  resources: { pl: { translation: pl }, en: { translation: en } },
  lng: typeof window === "undefined" ? "pl" : initial(),
  fallbackLng: "en",
  interpolation: { escapeValue: false },
});

i18n.on("languageChanged", (lng) => {
  document.documentElement.lang = lng;
  try {
    localStorage.setItem(KEY, lng);
  } catch {
    /* no storage */
  }
});
if (typeof document !== "undefined") document.documentElement.lang = i18n.language;

export default i18n;
