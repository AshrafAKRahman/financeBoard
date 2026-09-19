module.exports = {
  root: true,
  env: { browser: true, es2022: true },
  parser: "@typescript-eslint/parser",
  parserOptions: { ecmaVersion: "latest", sourceType: "module" },
  plugins: ["@typescript-eslint", "react-hooks"],
  extends: ["eslint:recommended", "plugin:@typescript-eslint/recommended"],
  rules: {
    // NFR4: no `any` in application code.
    "@typescript-eslint/no-explicit-any": "error",
    "@typescript-eslint/consistent-type-imports": "error",
    "react-hooks/rules-of-hooks": "error",
    "react-hooks/exhaustive-deps": "warn",
    // R10.AC6 / R4.AC2: an amount is a string and must never meet a float.
    "no-restricted-globals": [
      "error",
      { name: "parseFloat", message: "Amounts are strings; formatting must not use floats." },
      { name: "parseInt", message: "Use Number.parseInt only on non-monetary values." },
    ],
  },
  ignorePatterns: ["dist", "src/api/schema.d.ts"],
};
