import js from "@eslint/js";
import globals from "globals";

export default [
    {
        ignores: [
            ".venv/**",
            "node_modules/**",
            "tests/**",
            "dist/**",
            "build/**",
            "sto_crm/assets/js/core/*.js",
            "sto_crm/assets/js/app_main.js"
        ]
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
            "no-undef": "error",
            "no-duplicate-imports": "error",
            "no-self-compare": "error",
            "no-template-curly-in-string": "error"
        }
    }
];
