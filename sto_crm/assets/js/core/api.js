// === Module: core/api.js ===
// Core fetch and REST API interactions with retry hooks, token propagation, and csrf verification.

"use strict";

function exportUrl(entity) {
    const safeEntity = String(entity || "").trim();
    if (!EXPORT_ENTITIES.has(safeEntity)) {
        throw new Error("Недопустимый тип CSV-экспорта.");
    }
    return `/api/export/${safeEntity}.csv`;
}

function safeDownloadFilename(value, fallback = "export.csv") {
    const rawFilename = String(value || "")
        .split(/[\\/]/)
        .pop()
        .trim();
    const filename = Array.from(rawFilename)
        .filter(c => {
            const code = c.charCodeAt(0);
            return code >= 32 && code !== 127;
        })
        .join("");
    return filename && !/[<>:"|?*]/.test(filename) ? filename : fallback;
}

function entityCollectionPath(kind) {
    const path = ENTITY_COLLECTION_PATHS[String(kind || "")];
    if (!path) throw new Error("Недопустимый раздел CRM.");
    return path;
}

function entityRecordPath(kind, id) {
    const recordId = Number(id || 0);
    if (!Number.isSafeInteger(recordId) || recordId <= 0) {
        throw new Error("Недопустимый идентификатор записи.");
    }
    return `${entityCollectionPath(kind)}/${encodeURIComponent(String(recordId))}`;
}

async function downloadCsv(entity) {
    const source = arguments[1] || null;
    if (!requiresFreshCsrf("экспорт CSV")) return;
    if (source) {
        if (source.disabled || source.dataset.debounced === "true") return;
        source.disabled = true;
        source.dataset.debounced = "true";
        source.setAttribute("aria-busy", "true");
    }
    try {
        const safeEntity = String(entity || "").trim();
        const headers = {};
        if (state.data?.app?.csrf_token) headers["X-CSRF-Token"] = state.data.app.csrf_token;
        const accessToken = state.data?.app?.access_token || state.accessToken;
        if (accessToken) headers["X-CRM-Access-Token"] = accessToken;
        const response = await fetch(exportUrl(entity), {
            headers,
            cache: "no-store"
        });
        if (!response.ok) {
            const contentType = response.headers.get("Content-Type") || "";
            const payload = contentType.includes("application/json") ? await response.json() : await response.text();
            const error = new Error(payload?.error || payload || "Не удалось экспортировать CSV");
            error.status = response.status;
            throw error;
        }
        const blob = await response.blob();
        const disposition = response.headers.get("Content-Disposition") || "";
        const match = disposition.match(/filename="?([^";]+)"?/i);
        const filename = safeDownloadFilename(match ? match[1] : "", `${safeEntity}.csv`);
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = filename;
        document.body.append(link);
        link.click();
        link.remove();
        window.setTimeout(() => URL.revokeObjectURL(url), 1000);
        toast("CSV экспортирован");
    } finally {
        if (source) {
            source.disabled = false;
            delete source.dataset.debounced;
            source.setAttribute("aria-busy", "false");
        }
    }
}

function isBootstrapRequestPath(path) {
    const value = String(path || "");
    return value === "/api/bootstrap" || value.startsWith("/api/bootstrap?");
}

function withBootstrapToken(path) {
    if (!state.bootstrapToken) return path;
    const separator = path.includes("?") ? "&" : "?";
    return `${path}${separator}bootstrap_token=${encodeURIComponent(state.bootstrapToken)}`;
}

async function parseResponsePayload(response) {
    const contentType = response.headers.get("Content-Type") || "";
    if (response.status === 204 || response.status === 205) return null;
    if (contentType.includes("application/json")) return response.json();
    return response.text();
}

async function api(path, options = {}, retries = null) {
    const method = String(options.method || "GET").toUpperCase();
    if (method !== "GET" && !state.data?.app?.csrf_token) {
        const error = new Error("Сессия безопасности устарела. Обновите данные CRM и повторите действие.");
        error.status = 403;
        error.retryable = false;
        throw error;
    }
    const maxRetries = retries ?? (method === "GET" ? 2 : 0);
    for (let attempt = 0; attempt <= maxRetries; attempt++) {
        try {
            const headers = { ...(options.headers || {}) };
            const accessToken = state.data?.app?.access_token || state.accessToken;
            if (accessToken) headers["X-CRM-Access-Token"] = accessToken;
            if (method !== "GET") {
                headers["Content-Type"] = headers["Content-Type"] || "application/json";
                if (state.data?.app?.csrf_token) headers["X-CSRF-Token"] = state.data.app.csrf_token;
            }
            const requestPath = isBootstrapRequestPath(path) ? withBootstrapToken(path) : path;
            const response = await fetch(requestPath, {
                ...options,
                headers
            });
            let data;
            try {
                data = await parseResponsePayload(response);
            } catch (parseError) {
                const error = new Error("Сервер вернул некорректный ответ. Обновите данные и повторите действие.");
                error.status = response.status;
                error.retryable = response.status >= 500;
                error.cause = parseError;
                throw error;
            }
            if (!response.ok) {
                const message = (data && typeof data === "object" ? data.error : data) || `Ошибка запроса (HTTP ${response.status})`;
                const error = new Error(message);
                error.status = response.status;
                error.retryable = response.status >= 500 || [408, 425, 429].includes(response.status);
                throw error;
            }
            return data;
        } catch (error) {
            if (error?.name === "AbortError") throw error;
            if (options?.signal?.aborted) throw error;
            if (!Number(error?.status || 0) && error instanceof TypeError) error.networkError = true;
            const retryable = error?.retryable === true || !Number(error?.status || 0);
            if (attempt === maxRetries || !retryable) throw error;
            await new Promise(r => setTimeout(r, 400 * (attempt + 1)));
        }
    }
}

function requiresFreshCsrf(actionName = "это действие") {
    if (state.data?.app?.csrf_token) return true;
    toast(`Нет активной сессии безопасности: обновите данные, чтобы выполнить ${actionName}.`, "error");
    loadData().catch(showError);
    return false;
}
