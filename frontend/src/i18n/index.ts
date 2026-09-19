/**
 * Two languages, and the direction that comes with one of them (R3).
 *
 * Arabic is not a translation layer over an English layout: choosing it mirrors the document,
 * swaps Ant Design's locale, and changes how every screen is laid out. The only thing kept
 * between visits is the choice itself (R3.AC7, NFR6).
 */
import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import ar from "./ar.json";
import en from "./en.json";

export const LOCALES = ["en", "ar"] as const;
export type Locale = (typeof LOCALES)[number];

export const STORAGE_KEY = "finance.language";

export function directionOf(locale: Locale): "ltr" | "rtl" {
  return locale === "ar" ? "rtl" : "ltr";
}

function isLocale(value: string | null): value is Locale {
  return value !== null && (LOCALES as readonly string[]).includes(value);
}

/** The language for this visit: the remembered one, the browser's, or English. */
export function initialLocale(): Locale {
  try {
    const remembered = localStorage.getItem(STORAGE_KEY);
    if (isLocale(remembered)) {
      return remembered;
    }
  } catch {
    // A browser that refuses storage still gets a language.
  }
  return typeof navigator !== "undefined" && navigator.language?.startsWith("ar") ? "ar" : "en";
}

/** Apply a language to the document, so CSS and Ant Design both follow (R3.AC3). */
export function applyLocale(locale: Locale): void {
  const direction = directionOf(locale);
  if (typeof document !== "undefined") {
    document.documentElement.lang = locale;
    document.documentElement.dir = direction;
  }
  try {
    localStorage.setItem(STORAGE_KEY, locale);
  } catch {
    // Not being able to remember is not a reason to fail.
  }
}

void i18n.use(initReactI18next).init({
  resources: { en: { translation: en }, ar: { translation: ar } },
  lng: initialLocale(),
  fallbackLng: "en",
  interpolation: { escapeValue: false },
  returnNull: false,
});

applyLocale(i18n.language as Locale);

export default i18n;
