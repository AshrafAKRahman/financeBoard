/** Both languages say everything (R3.AC1, R3.AC8), and only the choice is remembered. */
import { describe, expect, it } from "vitest";

import ar from "./ar.json";
import en from "./en.json";
import { LOCALES, STORAGE_KEY, applyLocale, directionOf, initialLocale } from "./index";

type Catalogue = { [key: string]: string | Catalogue };

function keysOf(catalogue: Catalogue, prefix = ""): string[] {
  return Object.entries(catalogue).flatMap(([key, value]) =>
    typeof value === "string"
      ? [`${prefix}${key}`]
      : keysOf(value, `${prefix}${key}.`),
  );
}

describe("the catalogues", () => {
  it("offers exactly English and Arabic", () => {
    // R3.AC1
    expect([...LOCALES]).toEqual(["en", "ar"]);
  });

  it("says everything in both languages", () => {
    // R3.AC8 — a key in one catalogue and not the other is a half-translated screen.
    const english = new Set(keysOf(en as Catalogue));
    const arabic = new Set(keysOf(ar as Catalogue));

    expect([...english].filter((key) => !arabic.has(key))).toEqual([]);
    expect([...arabic].filter((key) => !english.has(key))).toEqual([]);
  });

  it("leaves no phrase empty", () => {
    for (const catalogue of [en, ar] as Catalogue[]) {
      for (const key of keysOf(catalogue)) {
        const value = key
          .split(".")
          .reduce<string | Catalogue>((node, part) => (node as Catalogue)[part]!, catalogue);
        expect(String(value).trim().length).toBeGreaterThan(0);
      }
    }
  });

  it("writes Arabic in Arabic, not transliterated", () => {
    expect(ar.reports.trialBalance).toMatch(/[؀-ۿ]/);
    expect(ar.signIn.title).toMatch(/[؀-ۿ]/);
  });
});

describe("direction", () => {
  it("mirrors for Arabic only", () => {
    // R3.AC3
    expect(directionOf("ar")).toBe("rtl");
    expect(directionOf("en")).toBe("ltr");
  });

  it("sets the document's language and direction", () => {
    applyLocale("ar");
    expect(document.documentElement.dir).toBe("rtl");
    expect(document.documentElement.lang).toBe("ar");

    applyLocale("en");
    expect(document.documentElement.dir).toBe("ltr");
  });
});

describe("remembering the choice", () => {
  it("remembers it for the next visit", () => {
    // R3.AC7
    applyLocale("ar");
    expect(initialLocale()).toBe("ar");
  });

  it("remembers the language and nothing else", () => {
    // NFR6 — no figure, no session, nothing from the ledger.
    applyLocale("ar");
    expect(Object.keys(localStorage)).toEqual([STORAGE_KEY]);
  });

  it("copes with a browser that refuses storage", () => {
    const original = Storage.prototype.setItem;
    Storage.prototype.setItem = () => {
      throw new Error("denied");
    };
    expect(() => applyLocale("en")).not.toThrow();
    Storage.prototype.setItem = original;
  });
});
