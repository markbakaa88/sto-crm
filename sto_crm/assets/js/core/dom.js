// === Module: core/dom.js ===
// DOM querying and manipulation helpers, safe render helpers, escaping, and structured modals.

/* eslint-disable no-unused-vars */

"use strict";

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

function esc(value) {
    return String(value ?? "").replace(/[&<>"']/g, ch => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    }[ch]));
}

function highlightText(text, query) {
    const rawText = String(text ?? "");
    const q = String(query ?? "").trim();
    if (!q) {
        return esc(rawText);
    }
    const escapedQ = q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const regex = new RegExp("(" + escapedQ + ")", "gi");
    return rawText.split(regex).map(part => {
        if (part.toLowerCase() === q.toLowerCase()) {
            return `<mark class="search-match">${esc(part)}</mark>`;
        }
        return esc(part);
    }).join("");
}

function buttonClassName(value) {
    return String(value || "")
        .split(/\s+/)
        .filter(token => BUTTON_STYLE_CLASSES.has(token))
        .join(" ");
}

function safeExternalUrl(value, fallback = "#") {
    const normalize = candidate => {
        try {
            const url = new URL(String(candidate || ""), location.href);
            return url.protocol === "https:" && /(^|\.)github\.com$/i.test(url.hostname) ? url.href : null;
        } catch {
            return null;
        }
    };
    return normalize(value) || normalize(fallback) || "#";
}

function safeInlinePrintScript(htmlText) {
    const source = String(htmlText || "");
    const printScript = 'document.getElementById("printButton").addEventListener("click", () => window.print());';
    const openingTag = "<" + 'script nonce="__STO_CRM_CSP_NONCE__">';
    const closingTag = "<" + "/script>";
    return source.replace(/<script\b[^>]*>([\s\S]*?)<\/script>/gi, (_match, body) => {
        const normalizedBody = String(body || "").replace(/\s+/g, " ").trim();
        return normalizedBody === printScript
            ? `${openingTag}${printScript}${closingTag}`
            : "";
    });
}

function safeRecordId(value) {
    const id = Number(value || 0);
    return Number.isSafeInteger(id) && id > 0 ? String(id) : "";
}

function stableElementId(element, prefix = "ui") {
    const root = document.body || document.documentElement;
    if (!root) return `${prefix}0`;
    const selector = `[id^="${prefix}"]`;
    const nextIndex = root.querySelectorAll(selector).length + 1;
    let candidate = `${prefix}${nextIndex}`;
    let suffix = nextIndex;
    while (document.getElementById(candidate)) {
        suffix += 1;
        candidate = `${prefix}${suffix}`;
    }
    if (element?.dataset) element.dataset.generatedId = candidate;
    return candidate;
}

function assertSafeModalMarkup(markup) {
    const template = document.createElement("template");
    template.innerHTML = String(markup || "");
    const forbiddenTags = new Set(["script", "style", "iframe", "object", "embed", "link", "meta", "base"]);
    const urlAttributes = new Set(["action", "formaction", "href", "src", "xlink:href", "poster"]);
    const normalizeAttributeUrl = value => Array.from(String(value || ""), ch => {
        const codePoint = ch.codePointAt(0) || 0;
        return codePoint <= 0x20 || codePoint === 0x7f || ch.trim() === "" ? "" : ch;
    }).join("").toLowerCase();
    for (const element of template.content.querySelectorAll("*")) {
        if (forbiddenTags.has(element.tagName.toLowerCase())) {
            throw new Error("Небезопасная разметка модального окна.");
        }
        for (const attribute of element.attributes) {
            const name = attribute.name.toLowerCase();
            const value = normalizeAttributeUrl(attribute.value);
            if (
                name.startsWith("on") ||
                name === "srcdoc" ||
                (urlAttributes.has(name) && (value.startsWith("javascript:") || value.startsWith("data:text/html")))
            ) {
                throw new Error("Небезопасная разметка модального окна.");
            }
        }
    }
}

function inEditable(el) {
    if (!el) return false;
    const tag = el.tagName;
    return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || el.isContentEditable;
}

function clampPercent(value) {
    const number = Number(value || 0);
    if (!Number.isFinite(number)) return 0;
    return Math.max(0, Math.min(100, Math.round(number)));
}

function widthClassFromPercent(value) {
    const percent = clampPercent(value);
    return `w-${String(Math.round(percent / 5) * 5).padStart(3, "0")}`;
}

const RUB_FORMAT_FULL = new Intl.NumberFormat("ru-RU", { style: "currency", currency: "RUB", minimumFractionDigits: 2, maximumFractionDigits: 2 });
const RUB_FORMAT_COMPACT = new Intl.NumberFormat("ru-RU", { style: "currency", currency: "RUB", minimumFractionDigits: 0, maximumFractionDigits: 0 });

function money(value) {
    return RUB_FORMAT_FULL.format(Number(value || 0));
}

function moneyCompact(value) {
    return RUB_FORMAT_COMPACT.format(Number(value || 0));
}

function qty(value) {
    const number = num(value);
    return Number.isInteger(number) ? String(number) : number.toFixed(2).replace(/0+$/, "").replace(/\.$/, "");
}

function num(value, fallback = 0) {
    if (value === null || value === undefined || value === "") return fallback;
    const parsed = Number(String(value).replace(/\s+/g, "").replace(/,/g, "."));
    return Number.isFinite(parsed) ? parsed : fallback;
}

function parseNumericInput(value, fallback = 0) {
    if (value === null || value === undefined || value === "") return { valid: true, value: fallback };
    const parsed = Number(String(value).replace(/\s+/g, "").replace(/,/g, "."));
    return Number.isFinite(parsed)
        ? { valid: true, value: parsed }
        : { valid: false, value: fallback };
}

const PLURAL_MAP = {
    "задача": ["задача", "задачи", "задач"],
    "заказ": ["заказ", "заказа", "заказов"],
    "активный заказ": ["активный заказ", "активных заказа", "активных заказов"],
    "Активный заказ": ["Активный заказ", "Активных заказа", "Активных заказов"],
    "событие": ["событие", "события", "событий"],
    "Запись сегодня": ["Запись сегодня", "Записи сегодня", "Записей сегодня"],
    "Дефицитная позиция": ["Дефицитная позиция", "Дефицитные позиции", "Дефицитных позиций"],
    "раз": ["раз", "раза", "раз"]
};

function pluralRu(value, one, few, many) {
    const number = Math.abs(Number(value || 0));
    const mod10 = number % 10;
    const mod100 = number % 100;
    let oneForm = one;
    let fewForm = few;
    let manyForm = many;
    if (typeof one === "string" && few === undefined && many === undefined) {
        const mapped = PLURAL_MAP[one] || PLURAL_MAP[one.toLowerCase()];
        if (mapped) {
            oneForm = mapped[0];
            fewForm = mapped[1];
            manyForm = mapped[2];
        } else {
            oneForm = one;
            fewForm = one;
            manyForm = one;
        }
    }
    if (mod10 === 1 && mod100 !== 11) return oneForm;
    if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return fewForm;
    return manyForm;
}

function bytesText(value) {
    const bytes = Number(value || 0);
    if (!Number.isFinite(bytes) || bytes <= 0) return "—";
    const units = ["Б", "КБ", "МБ", "ГБ"];
    let size = bytes;
    let index = 0;
    while (size >= 1024 && index < units.length - 1) {
        size /= 1024;
        index += 1;
    }
    return `${size >= 10 || index === 0 ? size.toFixed(0) : size.toFixed(1)} ${units[index]}`;
}

function helpTip(text, label = "?") {
    return `<button type="button" class="help-tip" aria-label="${esc(text)}" title="${esc(text)}" data-help-tip="true"><span aria-hidden="true">${esc(label)}</span></button>`;
}

function textOrDash(value, fallback = "—") {
    const text = String(value ?? "").trim();
    return text ? esc(text) : `<span class="muted">${esc(fallback)}</span>`;
}

function dateOrDash(value, fallback = "Без срока") {
    return value ? dateShort(value) : `<span class="muted">${esc(fallback)}</span>`;
}

function statusBadge(status) {
    const label = state.data?.statuses?.[status] || status;
    return `<span class="status s-${classToken(status)}">${esc(label)}</span>`;
}

function appointmentStatusBadge(status) {
    const label = state.data?.appointment_statuses?.[status] || appointmentStatusFallback[status] || status;
    return `<span class="status a-${classToken(status)}">${esc(label)}</span>`;
}

function classToken(value) {
    return String(value ?? "").toLowerCase().replace(/[^a-z0-9_-]+/g, "-") || "unknown";
}

function toneToken(value, fallback = "info") {
    const token = classToken(value || fallback);
    const aliases = { ok: "success", warn: "warning", bad: "danger", error: "danger", attention: "warning" };
    const normalized = aliases[token] || token;
    return ["success", "warning", "danger", "info", "neutral"].includes(normalized) ? normalized : fallback;
}

function semanticToneClass(value, fallback = "") {
    return value ? toneToken(value, fallback || "neutral") : fallback;
}

// -------------------------------------------------------------
// Core UI Safe Render Sink primitives (Documented allowlist for raw DOM sinks)
// Primary mechanism to prevent unsafe dynamically evaluated raw markup sinks.
// All dynamically generated HTML strings must pass through these wrappers.
// -------------------------------------------------------------
function setHTMLSafe(element, markup) {
    if (!element) return;
    // Perform standard sanitization review
    assertSafeModalMarkup(markup);
    element.innerHTML = markup;
}
