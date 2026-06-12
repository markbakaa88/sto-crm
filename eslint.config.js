import js from "@eslint/js";
import globals from "globals";

export default [
    {
        ignores: [".venv/**", "node_modules/**", "tests/**", "dist/**", "build/**"]
    },
    js.configs.recommended,
    {
        languageOptions: {
            ecmaVersion: 2022,
            sourceType: "module",
            globals: {
                ...globals.browser
            }
        },
        rules: {
            "no-unused-vars": "warn",
            "no-undef": "error"
        }
    }
];
