
const state = {
    route: "dashboard",
    q: "",
    status: "all",
    catalogQ: "",
    data: null,
    updateStatus: null,
    updateLoading: false,
    updateInstalling: false,
    updateCheckScheduled: false,
    loadSeq: 0,
    lastError: "",
    orderDraftItems: [],
    orderDraftReadOnly: false,
    bootstrapAbortController: null,
    modalDirty: false,
    saving: false,
    loading: false,
    lastLoadedAt: "",
    offlineMode: false,
    compactMode: true,
    customerPage: 1,
    customerPageSize: 50,
    catalogLimit: 60
};

const BOOTSTRAP_CACHE_KEY = "sto-crm-bootstrap";
const BOOTSTRAP_CACHE_SCHEMA_VERSION = 2;
const BOOTSTRAP_CACHE_TTL_MS = 30 * 60 * 1000;

const routes = {
    dashboard: "Панель",
    appointments: "Запись",
    orders: "Заказы",
    customers: "Клиенты",
    vehicles: "Автомобили",
    catalog: "Каталог авто",
    inventory: "Склад",
    reports: "Отчеты",
    updates: "Обновления"
};

const routeSubtitles = {
    dashboard: "Сводка смены",
    appointments: "Визиты и приемка",
    orders: "Заказы, сроки и оплаты",
    customers: "Контакты и история",
    vehicles: "Авто, VIN и сервисный план",
    catalog: "Марки и модели",
    inventory: "Остатки и закупка",
    reports: "Финансы и риски",
    updates: "Релизы и установка"
};

const requestedRoute = new URLSearchParams(location.search).get("route") || location.hash.replace("#", "");
if (requestedRoute && routes[requestedRoute]) {
    state.route = requestedRoute;
}

const priorityLabels = { low: "Низкий", normal: "Обычный", high: "Высокий", urgent: "Срочно" };
const orderStatusTransitions = {
    new: ["diagnostics", "estimate", "approved", "in_progress", "done", "closed", "cancelled"],
    diagnostics: ["estimate", "approved", "in_progress", "done", "closed", "cancelled"],
    estimate: ["approved", "in_progress", "done", "closed", "cancelled"],
    approved: ["in_progress", "done", "closed", "cancelled"],
    in_progress: ["done", "closed", "cancelled"],
    done: ["closed", "cancelled"],
    closed: ["cancelled"],
    cancelled: []
};
const channelLabels = { phone: "Телефон", sms: "SMS", email: "Email", messenger: "Мессенджер", none: "Не писать" };
function channelLabel(key) {
    return (state.data?.preferred_channels || channelLabels)[key] || channelLabels[key] || key;
}
const appointmentStatusFallback = { scheduled: "Запланирована", confirmed: "Подтверждена", arrived: "Клиент приехал", done: "Завершена", no_show: "Не приехал", cancelled: "Отменена" };
const itemApprovalFallback = { approved: "Согласовано", deferred: "Отложено", declined: "Отказ" };

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

function esc(value) {
    return String(value ?? "").replace(/[&<>"']/g, ch => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    }[ch]));
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

function safeRecordId(value) {
    const id = Number(value || 0);
    return Number.isSafeInteger(id) && id > 0 ? String(id) : "";
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

function pluralRu(value, one, few, many) {
    const number = Math.abs(Number(value || 0));
    const mod10 = number % 10;
    const mod100 = number % 100;
    if (mod10 === 1 && mod100 !== 11) return one;
    if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few;
    return many;
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

function exportUrl(entity) {
    return `/api/export/${encodeURIComponent(entity)}.csv`;
}

async function downloadCsv(entity) {
    if (!requiresFreshCsrf("экспорт CSV")) return;
    const response = await fetch(exportUrl(entity), {
        headers: state.data?.app?.csrf_token ? { "X-CSRF-Token": state.data.app.csrf_token } : {},
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
    const filename = match ? match[1] : `${entity}.csv`;
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.append(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    toast("CSV экспортирован");
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

function ensureBootstrapReady(actionName = "действие") {
    if (state.data) return true;
    const message = state.loading
        ? `Данные CRM ещё загружаются — ${actionName} будет доступно после загрузки.`
        : `Данные CRM не загружены — обновите приложение, чтобы выполнить ${actionName}.`;
    toast(message, "error");
    return false;
}

function dateShort(value) {
    if (!value) return "";
    const parsed = new Date(String(value).replace(" ", "T"));
    if (Number.isNaN(parsed.getTime())) return esc(String(value).slice(0, 16));
    return parsed.toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function inputDateValue(value) {
    if (!value) return "";
    return esc(String(value).replace(" ", "T").slice(0, 16));
}

function vehicleName(vehicle) {
    if (!vehicle) return "";
    return [vehicle.make, vehicle.model, vehicle.year, vehicle.plate].filter(Boolean).join(" ");
}

function orderVehicle(order) {
    return [order.vehicle_make, order.vehicle_model, order.vehicle_year, order.vehicle_plate].filter(Boolean).join(" ");
}


function appointmentVehicle(appointment) {
    return [appointment.vehicle_make, appointment.vehicle_model, appointment.vehicle_year, appointment.vehicle_plate].filter(Boolean).join(" ");
}

function classToken(value) {
    return String(value ?? "").toLowerCase().replace(/[^a-z0-9_-]+/g, "-") || "unknown";
}

function helpTip(text, label = "?") {
    return `<span class="help-tip" role="note" tabindex="0" aria-label="${esc(text)}" title="${esc(text)}"><span aria-hidden="true">${esc(label)}</span></span>`;
}

function textOrDash(value, fallback = "—") {
    const text = String(value ?? "").trim();
    return text ? esc(text) : `<span class="muted">${esc(fallback)}</span>`;
}

function dateOrDash(value, fallback = "Без срока") {
    return value ? dateShort(value) : `<span class="muted">${esc(fallback)}</span>`;
}

function paginationControls(kind, page, maxPage, total, pageSize, noun = "записей") {
    if (total <= pageSize) return "";
    const start = (page - 1) * pageSize + 1;
    const end = Math.min(total, page * pageSize);
    return `<nav class="pagination" aria-label="Страницы списка">
        <span>${start}–${end} из ${total} ${esc(noun)}</span>
        <button class="btn" type="button" data-action="page-${esc(kind)}" data-page="${page - 1}" ${page <= 1 ? "disabled" : ""}>Назад</button>
        <span class="count-pill">${page}/${maxPage}</span>
        <button class="btn" type="button" data-action="page-${esc(kind)}" data-page="${page + 1}" ${page >= maxPage ? "disabled" : ""}>Вперед</button>
    </nav>`;
}

function formatClockTime(value) {
    if (!value) return "—";
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return "—";
    return parsed.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
}

function localDateKey(value = new Date()) {
    const date = value instanceof Date ? value : new Date(value);
    if (Number.isNaN(date.getTime())) return "";
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, "0");
    const day = String(date.getDate()).padStart(2, "0");
    return `${year}-${month}-${day}`;
}

function contextPill(label, value, hint, tone = "") {
    const toneClass = tone ? ` ${classToken(tone)}` : "";
    return `<article class="context-pill${toneClass}" aria-label="${esc(`${label}: ${value}. ${hint}`)}"><div class="context-label"><span class="live-dot" aria-hidden="true"></span>${esc(label)}</div><strong>${esc(value)}</strong><span>${esc(hint)}</span></article>`;
}

function contextStripHtml() {
    if (!state.data) return "";
    const r = state.data.reports || {};
    const riskCount = Number(r.overdue_orders_count || 0) + Number(r.low_stock_count || 0);
    const riskTone = riskCount > 0 ? (riskCount > 3 ? "danger" : "warning") : "success";
    return `<section class="context-strip" aria-label="Операционный статус CRM">
        ${contextPill("Смена", `${Math.max(0, Math.min(100, Number(r.business_health_score || 0)))}/100 · ${r.business_health_label || "Контроль"}`, "Индекс здоровья сервиса", riskTone)}
        ${contextPill("Воронка", moneyCompact(r.pipeline_value || 0), `${r.active_orders || 0} ${pluralRu(r.active_orders, "активный заказ", "активных заказа", "активных заказов")}`, "info")}
        ${contextPill("К оплате", moneyCompact(r.due_total || 0), "Дебиторская задолженность", Number(r.due_total || 0) > 0 ? "warning" : "success")}
        ${contextPill(
            "Обновлено",
            formatClockTime(state.lastLoadedAt),
            `${state.offlineMode ? "Кэш" : "Онлайн"} · ${state.data.app?.version || ""}`,
            state.offlineMode ? "warning" : "success"
        )}
    </section>`;
}

function statusBadge(status) {
    const label = state.data?.statuses?.[status] || status;
    return `<span class="status s-${classToken(status)}">${esc(label)}</span>`;
}

function appointmentStatusBadge(status) {
    const label = state.data?.appointment_statuses?.[status] || appointmentStatusFallback[status] || status;
    return `<span class="status a-${classToken(status)}">${esc(label)}</span>`;
}



let announceFrame = 0;
function announce(message, urgent = false) {
    const status = $("#appStatus");
    if (!status) return;
    status.setAttribute("aria-live", urgent ? "assertive" : "polite");
    status.textContent = "";
    if (announceFrame) cancelAnimationFrame(announceFrame);
    announceFrame = requestAnimationFrame(() => {
        announceFrame = 0;
        status.textContent = message;
    });
}

function toast(message, type = "info") {
    const isError = type === "error";
    const node = $("#toast");
    if (!node) {
        announce(message, isError);
        return;
    }
    node.textContent = message;
    node.classList.toggle("error", isError);
    node.setAttribute("role", isError ? "alert" : "status");
    node.setAttribute("aria-live", isError ? "assertive" : "polite");
    node.classList.add("show");
    announce(message, isError);
    clearTimeout(node.timer);
    node.timer = setTimeout(() => node.classList.remove("show"), isError ? 5200 : 3200);
}

function clearAllFormErrors(form) {
    if (!form) return;
    $$(".invalid", form).forEach(clearFormError);
    $$(".field-error", form).forEach(node => node.remove());
}

function applyFormError(error) {
    const form = $("#entityForm") || $("#orderForm");
    if (!form) return;
    clearAllFormErrors(form);
    const message = error?.message || String(error || "");
    let target = null;
    const lower = message.toLocaleLowerCase("ru-RU");
    const isVisibleFieldTarget = candidate => candidate instanceof HTMLElement && !(candidate instanceof HTMLInputElement && candidate.type === "hidden");
    const fieldTarget = names => {
        for (const name of Array.isArray(names) ? names : [names]) {
            let candidate = form.elements[name] || form.querySelector(`[data-item="${name}"]`);
            if (window.RadioNodeList && candidate instanceof RadioNodeList) {
                candidate = Array.from(candidate).find(isVisibleFieldTarget);
            }
            if (isVisibleFieldTarget(candidate)) return candidate;
        }
        return null;
    };
    const hints = [
        ["email", ["email", "почт"]],
        ["preferred_channel", ["канал связи"]],
        ["reminder_consent", ["согласие на напоминания", "напоминан"]],
        ["vin", ["vin"]],
        ["plate", ["госномер", "номер"]],
        ["make", ["марку", "марка"]],
        ["model", ["модель"]],
        ["year", ["год"]],
        ["next_service_at", ["дата следующего сервиса", "следующий сервис"]],
        ["next_service_mileage", ["сервисный пробег"]],
        ["odometer", ["пробег в заказ"]],
        ["mileage", ["пробег"]],
        ["scheduled_at", ["дата и время записи", "время записи", "запис"]],
        ["duration_minutes", ["длитель"]],
        ["promised_at", ["срок заказа", "срок"]],
        ["authorized_at", ["дата согласования"]],
        ["follow_up_at", ["follow-up"]],
        ["customer_id", ["клиент"]],
        ["vehicle_id", ["автомоб"]],
        ["approval_status", ["статус согласования", "согласован"]],
        ["kind", ["тип позиции"]],
        ["title", ["наименование", "запчаст"]],
        ["min_quantity", ["миним"]],
        ["quantity", ["количество", "остаток"]],
        ["unit_cost", ["себестоимость позиции"]],
        ["cost", ["себестоим"]],
        ["unit_price", ["цена позиции"]],
        ["price", ["цена"]],
        ["inventory_id", ["склад"]],
        ["discount", ["скидк"]],
        ["tax_rate", ["налог"]],
        ["paid", ["оплат"]],
        ["priority", ["приоритет"]],
        ["status", ["статус"]],
        ["sku", ["артикул"]],
        ["name", ["имя", "название"]]
    ];
    for (const [names, tokens] of hints) {
        if (tokens.some(token => lower.includes(token))) {
            target = fieldTarget(names);
            if (target) break;
        }
    }
    if (!(target instanceof HTMLElement)) {
        const errorNode = document.createElement("div");
        errorNode.className = "field-error form-error";
        errorNode.id = "form-error";
        errorNode.setAttribute("role", "alert");
        errorNode.tabIndex = -1;
        errorNode.textContent = message;
        form.prepend(errorNode);
        errorNode.focus({ preventScroll: false });
        return;
    }
    target.classList.add("invalid");
    target.setAttribute("aria-invalid", "true");
    const id = `${target.name || target.id || "field"}-error`;
    const previous = (target.getAttribute("aria-describedby") || "").split(/\s+/).filter(Boolean).filter(token => token !== id);
    target.dataset.errorDescribedby = id;
    target.setAttribute("aria-describedby", [...previous, id].join(" "));
    const errorNode = document.createElement("div");
    errorNode.className = "field-error";
    errorNode.id = id;
    errorNode.textContent = message;
    (target.closest(".field") || target.parentElement)?.append(errorNode);
    target.focus({ preventScroll: false });
}

function clearFormError(target) {
    if (!target) return;
    target.closest("form")?.querySelectorAll(".form-error").forEach(node => node.remove());
    target.classList.remove("invalid");
    target.removeAttribute("aria-invalid");
    if (typeof target.setCustomValidity === "function") target.setCustomValidity("");
    const errorId = target.dataset.errorDescribedby;
    if (errorId) document.getElementById(errorId)?.remove();
    const describedBy = (target.getAttribute("aria-describedby") || "").split(/\s+/).filter(Boolean).filter(token => token !== errorId);
    if (describedBy.length) target.setAttribute("aria-describedby", describedBy.join(" "));
    else target.removeAttribute("aria-describedby");
    delete target.dataset.errorDescribedby;
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
            if (method !== "GET") {
                headers["Content-Type"] = headers["Content-Type"] || "application/json";
                if (state.data?.app?.csrf_token) headers["X-CSRF-Token"] = state.data.app.csrf_token;
            }
            const response = await fetch(path, {
                ...options,
                headers
            });
            const contentType = response.headers.get("Content-Type") || "";
            const data = contentType.includes("application/json") ? await response.json() : await response.text();
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
            const retryable = error?.retryable === true || !Number(error?.status || 0);
            if (attempt === maxRetries || !retryable) throw error;
            await new Promise(r => setTimeout(r, 400 * (attempt + 1)));
        }
    }
}

function cacheBootstrap(data, loadedAt = new Date().toISOString(), query = {}) {
    try {
        if (!window.sessionStorage) return;
        const q = String(query.q || "");
        const status = String(query.status || "all");
        const route = String(query.route || state.route || "dashboard");
        if (q || status !== "all") {
            clearCachedBootstrap();
            return;
        }
        const cached = JSON.parse(JSON.stringify(data || {}));
        if (cached.app) delete cached.app.csrf_token;
        const payload = {
            schemaVersion: BOOTSTRAP_CACHE_SCHEMA_VERSION,
            cachedAt: Date.now(),
            loadedAt,
            appVersion: cached.app?.version || "",
            dbPath: cached.app?.db_path || "",
            query: { q, status, route },
            data: cached
        };
        sessionStorage.setItem(BOOTSTRAP_CACHE_KEY, JSON.stringify(payload));
    } catch { /* sessionStorage can be unavailable in locked-down browsers */ }
}

function clearCachedBootstrap() {
    try {
        if (window.sessionStorage) sessionStorage.removeItem(BOOTSTRAP_CACHE_KEY);
    } catch { /* sessionStorage can be unavailable in locked-down browsers */ }
}

function readCachedBootstrap() {
    try {
        if (!window.sessionStorage) return null;
        const raw = sessionStorage.getItem(BOOTSTRAP_CACHE_KEY);
        if (!raw) return null;
        const parsed = JSON.parse(raw);
        if (parsed?.data && typeof parsed.data === "object") {
            if (parsed.schemaVersion !== BOOTSTRAP_CACHE_SCHEMA_VERSION) {
                clearCachedBootstrap();
                return null;
            }
            const query = parsed.query || {};
            if (String(query.q || "") || String(query.status || "all") !== "all") {
                clearCachedBootstrap();
                return null;
            }
            const cachedAt = Number(parsed.cachedAt || 0);
            if (!Number.isFinite(cachedAt) || Date.now() - cachedAt > BOOTSTRAP_CACHE_TTL_MS) {
                clearCachedBootstrap();
                return null;
            }
            return parsed;
        }
        if (parsed?.app) {
            clearCachedBootstrap();
            return null;
        }
    } catch { /* sessionStorage can be unavailable or contain stale data */ }
    return null;
}

function restoreCachedBootstrap() {
    try {
        if (!window.sessionStorage) return false;
        const cached = readCachedBootstrap();
        if (!cached?.data?.app) return false;
        const data = cached.data;
        if (state.data?.app?.csrf_token) data.app.csrf_token = state.data.app.csrf_token;
        state.data = data;
        state.lastLoadedAt = cached.loadedAt || state.lastLoadedAt || "";
        state.offlineMode = true;
        setOnlineState(false);
        const dbPath = $("#dbPath");
        if (dbPath) {
            dbPath.textContent = `База: ${state.data.app.db_path}`;
            dbPath.title = state.data.app.db_directory ? `Папка базы: ${state.data.app.db_directory}` : "";
        }
        render();
        updateSearchClear();
        const loadedText = state.lastLoadedAt ? ` от ${new Date(state.lastLoadedAt).toLocaleString("ru-RU")}` : "";
        announce(`Показаны сохраненные данные${loadedText}. Сервер CRM недоступен.`, true);
        return true;
    } catch {
        return false;
    }
}

function setLoadingState(isLoading) {
    state.loading = isLoading;
    const content = $("#content");
    if (content) content.setAttribute("aria-busy", String(isLoading));
    $("#refreshBtn")?.toggleAttribute("disabled", isLoading);
    const progress = $("#appProgress");
    if (progress) {
        progress.classList.toggle("is-active", Boolean(isLoading));
        progress.setAttribute("aria-hidden", isLoading ? "false" : "true");
    }
    const syncChip = $("#syncChip");
    if (syncChip && isLoading) syncChip.dataset.state = "syncing";
    renderShell();
}

function updateTopbarOffset() {
    const topbar = $(".topbar");
    if (!topbar) return;
    const bottom = Math.max(0, Math.ceil(topbar.getBoundingClientRect().bottom));
    const offset = bottom > 152 ? "xl" : bottom > 128 ? "lg" : bottom > 112 ? "md" : "sm";
    document.documentElement.setAttribute("data-topbar-offset", offset);
}

function closeTransientPanels(except = "", { restoreFocus = false } = {}) {
    const closePanel = (panelSelector, buttonSelector, key) => {
        if (except === key) return null;
        const panel = $(panelSelector);
        const button = $(buttonSelector);
        if (!panel || panel.hidden) return null;
        panel.hidden = true;
        button?.setAttribute("aria-expanded", "false");
        return button;
    };
    const restoreTarget =
        closePanel("#primaryCtaMenu", "#primaryCtaMore", "cta") ||
        closePanel("#bellPanel", "#bellBtn", "bell") ||
        closePanel("#systemMenu", "#systemMenuBtn", "system");
    if (restoreFocus) restoreTarget?.focus({ preventScroll: true });
}

async function loadData() {
    const seq = ++state.loadSeq;
    if (state.bootstrapAbortController) state.bootstrapAbortController.abort();
    const controller = new AbortController();
    state.bootstrapAbortController = controller;
    setLoadingState(true);
    const params = new URLSearchParams({ q: state.q });
    const requestStatus = state.route === "orders" ? state.status : "all";
    if (requestStatus !== "all") {
        params.set("status", requestStatus);
    }
    try {
        const data = await api(`/api/bootstrap?${params}`, { signal: controller.signal });
        if (seq !== state.loadSeq) return;
        const loadedAt = new Date().toISOString();
        state.data = data;
        state.lastLoadedAt = loadedAt;
        state.offlineMode = false;
        cacheBootstrap(data, loadedAt, { q: state.q, status: requestStatus, route: state.route });
        state.lastError = "";
        setOnlineState(true);
        const dbPath = $("#dbPath");
        if (dbPath) {
            dbPath.textContent = `База: ${state.data.app.db_path}`;
            dbPath.title = state.data.app.db_directory ? `Папка базы: ${state.data.app.db_directory}` : "";
        }
        render();
        updateSearchClear();
        announce(`Данные обновлены. Раздел: ${routes[state.route]}.`);
    } catch (error) {
        if (error?.name === "AbortError") return;
        throw error;
    } finally {
        if (state.bootstrapAbortController === controller) state.bootstrapAbortController = null;
        if (seq === state.loadSeq) setLoadingState(false);
    }
}

function prefersReducedMotion() {
    return window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function setRoute(route, updateUrl = true) {
    if (!routes[route]) return;
    closeTransientPanels();
    const previousRoute = state.route;
    const sameRoute = previousRoute === route;
    const hasOrderFilter = state.status !== "all" && !state.offlineMode;
    const leavingFilteredOrders = hasOrderFilter && route !== "orders" && previousRoute === "orders";
    const enteringFilteredOrders = hasOrderFilter && route === "orders" && previousRoute !== "orders";
    const needsRouteFilterReload = enteringFilteredOrders || leavingFilteredOrders;
    if (leavingFilteredOrders) state.status = "all";
    state.route = route;
    if (route === "updates" && !state.updateStatus && !state.updateLoading && !state.updateCheckScheduled) {
        state.updateCheckScheduled = true;
        window.setTimeout(() => checkForUpdates(false).catch(showError), 0);
    }
    if (updateUrl && !sameRoute) {
        const url = new URL(location.href);
        url.searchParams.set("route", route);
        url.hash = "";
        history.pushState({ route }, "", url);
    }
    $("#viewTitle").textContent = routes[route];
    $("#viewSubtitle").textContent = routeSubtitles[route] || "";
    $$("#nav button").forEach(button => {
        const active = button.dataset.route === route;
        button.classList.toggle("active", active);
        if (active) button.setAttribute("aria-current", "page");
        else button.removeAttribute("aria-current");
    });
    renderShell();
    render();
    if (needsRouteFilterReload) {
        loadData().catch(showError);
    }
    if (previousRoute !== route) {
        setMobileNavOpen(false);
        const content = $("#content");
        content?.scrollIntoView({ behavior: prefersReducedMotion() ? "auto" : "smooth", block: "start" });
        content?.focus({ preventScroll: true });
        announce(`Открыт раздел ${routes[route]}.`);
    }
}

function routeFromLocation() {
    const params = new URLSearchParams(location.search);
    const requested = params.get("route") || location.hash.replace("#", "");
    return routes[requested] ? requested : "dashboard";
}

function render() {
    if (!state.data) return;
    const content = $("#content");
    if (!content) return;
    resetWorkspaceToolbarObserver();
    const renderers = {
        dashboard: renderDashboard,
        appointments: renderAppointments,
        orders: renderOrders,
        customers: renderCustomers,
        vehicles: renderVehicles,
        catalog: renderCatalog,
        inventory: renderInventory,
        reports: renderReports,
        updates: renderUpdates
    };
    const busy = content.getAttribute("aria-busy") || "false";
    let viewHtml = "";
    try {
        viewHtml = renderers[state.route]();
    } catch (error) {
        console.error(error);
        state.lastError = error?.message || String(error);
        viewHtml = `<div class="notice" role="alert"><strong>Не удалось отрисовать раздел.</strong><p>${esc(state.lastError)}</p><button class="btn primary" type="button" data-action="retry-load">Обновить данные</button></div>`;
    }
    content.innerHTML = `${offlineBannerHtml()}${errorBannerHtml()}${contextStripHtml()}${viewHtml}`;
    content.setAttribute("aria-busy", busy);
    bindViewActions(content);
    bindCatalogFilter(content);
    bindWorkspaceToolbar(content);
    updateScrollHints(content);
    applyCellTitles(content);
    updateNavigationBadges();
}

function applyCellTitles(root) {
    $$(".cell-title strong, .cell-title .muted", root).forEach(node => {
        const text = (node.textContent || "").trim();
        if (!text) { node.removeAttribute("title"); return; }
        // Используем scrollWidth vs clientWidth для точной детекции эллипсиса,
        // но выставляем title всегда при непустом тексте — браузер всё равно
        // показывает подсказку только если текст действительно обрезан.
        if (node.scrollWidth > node.clientWidth + 1) {
            node.setAttribute("title", text);
        } else {
            node.removeAttribute("title");
        }
    });
}

let workspaceToolbarObserver = null;
function resetWorkspaceToolbarObserver() {
    if (workspaceToolbarObserver) {
        workspaceToolbarObserver.disconnect();
        workspaceToolbarObserver = null;
    }
}

function bindWorkspaceToolbar(root) {
    const toolbar = root.querySelector(".workspace-toolbar");
    if (!toolbar || !("IntersectionObserver" in window)) return;
    const sentinel = document.createElement("div");
    sentinel.className = "workspace-toolbar-sentinel";
    sentinel.setAttribute("aria-hidden", "true");
    toolbar.parentNode.insertBefore(sentinel, toolbar);
    workspaceToolbarObserver = new IntersectionObserver(entries => {
        for (const entry of entries) toolbar.classList.toggle("is-stuck", !entry.isIntersecting);
    }, { rootMargin: "-1px 0px 0px 0px", threshold: [1] });
    workspaceToolbarObserver.observe(sentinel);
}

function updateScrollHints(root = document) {
    const refresh = () => {
        $$(".table-wrap, .items-table", root).forEach(container => {
            if (!container.querySelector(":scope > .scroll-hint")) {
                const hint = document.createElement("div");
                hint.className = "scroll-hint";
                hint.setAttribute("aria-hidden", "true");
                hint.textContent = "Прокрутите вправо →";
                container.append(hint);
            }
            let srHint = container.querySelector(":scope > .scroll-hint-sr");
            if (!srHint) {
                srHint = document.createElement("div");
                srHint.className = "sr-only scroll-hint-sr";
                srHint.id = `scrollHint${Math.random().toString(36).slice(2)}`;
                srHint.textContent = "Таблица прокручивается горизонтально. Используйте Shift и колесо мыши, тач-жест или горизонтальную прокрутку клавиатурой.";
                container.append(srHint);
            }
            const hasOverflow = container.scrollWidth > container.clientWidth + 1;
            container.classList.toggle("has-horizontal-overflow", hasOverflow);
            if (hasOverflow) {
                container.setAttribute("tabindex", container.getAttribute("tabindex") || "0");
                const describedBy = new Set((container.getAttribute("aria-describedby") || "").split(/\s+/).filter(Boolean));
                describedBy.add(srHint.id);
                container.setAttribute("aria-describedby", [...describedBy].join(" "));
            } else {
                const describedBy = (container.getAttribute("aria-describedby") || "").split(/\s+/).filter(Boolean).filter(id => id !== srHint.id);
                if (describedBy.length) container.setAttribute("aria-describedby", describedBy.join(" "));
                else container.removeAttribute("aria-describedby");
                if (container.getAttribute("tabindex") === "0") container.removeAttribute("tabindex");
            }
        });
    };
    refresh();
    requestAnimationFrame(refresh);
}

function offlineBannerHtml(force = false) {
    if (!force && !state.offlineMode) return "";
    const loadedText = state.lastLoadedAt ? ` Данные из кэша от ${esc(new Date(state.lastLoadedAt).toLocaleString("ru-RU"))}.` : "";
    return `<div class="offline-banner" role="alert">Нет связи с локальным сервером. Проверьте, что СТО CRM запущена, или нажмите «Обновить».${loadedText} Доступные данные могут быть устаревшими.</div>`;
}

function errorBannerHtml() {
    if (!state.lastError) return "";
    return `<div class="error-banner" role="alert"><strong>Последнее действие не выполнено.</strong><span>${esc(state.lastError)}</span><button class="btn ghost" type="button" data-action="dismiss-error">Скрыть</button></div>`;
}

function setOnlineState(isOnline) {
    state.offlineMode = !isOnline;
    const app = $(".app");
    if (app) app.classList.toggle("offline", !isOnline);
    renderShell();
}

function updateNavigationBadges() {
    const r = state.data?.reports || {};
    const badgeValues = {
        dashboard: r.action_plan_total || 0,
        appointments: r.appointments_today_count || 0,
        orders: r.active_orders || 0,
        inventory: r.low_stock_count || 0,
        updates: state.updateStatus?.ok && state.updateStatus.release?.is_newer ? "!" : 0
    };
    $$('[data-nav-badge]').forEach(badge => {
        const value = badgeValues[badge.dataset.navBadge] || 0;
        const visible = value === "!" || Number(value) > 0;
        badge.hidden = !visible;
        badge.textContent = visible ? String(value) : "";
        badge.setAttribute("aria-label", value === "!" ? "Доступно обновление" : `${value} требует внимания`);
    });
    $$("#nav button[data-route]").forEach(button => {
        const label = button.querySelector(".nav-label")?.textContent?.trim() || button.dataset.route || "Раздел";
        const badge = button.querySelector("[data-nav-badge]");
        const badgeText = badge && !badge.hidden ? badge.getAttribute("aria-label") : "";
        button.setAttribute("aria-label", badgeText ? `${label}: ${badgeText}` : label);
    });
    renderShell();
}

const BREADCRUMB_MAP = {
    dashboard:    [{ label: "Панель",        route: null }],
    appointments: [{ label: "Смена", route: "dashboard" }, { label: "Запись",        route: null }],
    orders:       [{ label: "Смена", route: "dashboard" }, { label: "Заказ-наряды",  route: null }],
    customers:    [{ label: "Справочники", route: null },  { label: "Клиенты",       route: null }],
    vehicles:     [{ label: "Справочники", route: null },  { label: "Автомобили",    route: null }],
    catalog:      [{ label: "Справочники", route: null },  { label: "Каталог авто",  route: null }],
    inventory:    [{ label: "Справочники", route: null },  { label: "Склад",         route: null }],
    reports:      [{ label: "Аналитика",   route: null },  { label: "Отчеты",        route: null }],
    updates:      [{ label: "Аналитика",   route: null },  { label: "Обновления",    route: null }]
};

function shortStamp(value) {
    if (!value) return "—";
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return "—";
    const diff = Math.max(0, Date.now() - d.getTime());
    if (diff < 45 * 1000) return "только что";
    if (diff < 60 * 60 * 1000) return `${Math.max(1, Math.round(diff / 60000))} мин назад`;
    if (diff < 24 * 60 * 60 * 1000) return `${Math.round(diff / 3600000)} ч назад`;
    return d.toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function clockStr() {
    return new Date().toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
}

function updateSyncChip() {
    const chip = $("#syncChip");
    if (!chip) return;
    const textEl = chip.querySelector(".sync-text");
    let nextState = "online";
    let text = "Актуально";
    let stampTip = "";
    if (state.loading) {
        nextState = "syncing";
        text = "Синхронизация…";
    } else if (state.offlineMode) {
        nextState = "offline";
        text = "Нет связи";
    } else if (state.lastLoadedAt) {
        const age = Date.now() - new Date(state.lastLoadedAt).getTime();
        if (Number.isFinite(age) && age > 5 * 60 * 1000) {
            nextState = "stale";
            text = `Устарели · ${shortStamp(state.lastLoadedAt)}`;
        } else {
            text = `Актуально · ${shortStamp(state.lastLoadedAt)}`;
        }
        stampTip = new Date(state.lastLoadedAt).toLocaleString("ru-RU");
    } else {
        text = "Ожидание данных";
    }
    chip.dataset.state = nextState;
    if (textEl) textEl.textContent = text;
    chip.setAttribute("aria-label", `Синхронизация: ${text}`);
    chip.setAttribute("data-tooltip", stampTip ? `Обновлено ${stampTip}. Нажмите, чтобы синхронизировать.` : "Нажмите, чтобы обновить данные");
}

function renderBreadcrumbs() {
    const container = $("#breadcrumbs");
    if (!container) return;
    const route = state.route || "dashboard";
    const trail = BREADCRUMB_MAP[route] || [{ label: routes[route] || "Раздел", route: null }];
    if (route === "dashboard") {
        container.hidden = true;
        container.innerHTML = "";
        return;
    }
    container.hidden = false;
    const parts = ['<button class="crumb" type="button" data-crumb-route="dashboard" aria-label="На панель">⌂</button>'];
    trail.forEach((crumb, index) => {
        parts.push('<span class="sep" aria-hidden="true">/</span>');
        const isLast = index === trail.length - 1;
        if (crumb.route && !isLast) {
            parts.push(`<button class="crumb" type="button" data-crumb-route="${esc(crumb.route)}">${esc(crumb.label)}</button>`);
        } else if (isLast) {
            parts.push(`<span aria-current="page">${esc(crumb.label)}</span>`);
        } else {
            parts.push(`<span>${esc(crumb.label)}</span>`);
        }
    });
    container.innerHTML = parts.join("");
}

function renderStatusBar() {
    const connection = $("#statusConnectionText");
    const connectionWrap = $("#statusConnection");
    if (connectionWrap) {
        connectionWrap.dataset.tone = state.offlineMode ? "bad" : "ok";
        if (connection) connection.textContent = state.offlineMode ? "Нет связи" : "Подключено";
    }
    const dbPath = state.data?.app?.db_path || "";
    const dbPathEl = $("#statusDbPathText");
    if (dbPathEl) dbPathEl.textContent = dbPath;
    const dbWrap = $("#statusDbPath");
    if (dbWrap) dbWrap.hidden = !dbPath;

    const syncEl = $("#statusSyncText");
    if (syncEl) syncEl.textContent = state.lastLoadedAt ? shortStamp(state.lastLoadedAt) : "—";

    const backupEl = $("#statusBackupText");
    const backupWrap = $("#statusBackup");
    const lastBackup = state.lastBackupAt || state.data?.app?.last_backup_at || "";
    if (backupEl) backupEl.textContent = lastBackup ? `Бэкап · ${shortStamp(lastBackup)}` : "Создать бэкап";
    if (backupWrap) {
        backupWrap.dataset.tone = lastBackup ? "ok" : "warn";
        backupWrap.setAttribute("data-tooltip", lastBackup ? `Последний бэкап: ${shortStamp(lastBackup)}. Создать ещё.` : "Резервная копия не создавалась в этой сессии — нажмите, чтобы сохранить сейчас");
    }

    const versionEl = $("#statusVersionText");
    const version = state.data?.app?.version || state.updateStatus?.current_version || "";
    if (versionEl) versionEl.textContent = version ? `v${version}` : "v—";

    const clockEl = $("#statusClockText");
    if (clockEl) clockEl.textContent = clockStr();
}

function collectBellItems() {
    const items = [];
    const r = state.data?.reports || {};
    (r.action_plan || []).slice(0, 6).forEach(action => {
        if (!action) return;
        items.push({
            tone: action.tone === "danger" ? "danger" : action.tone === "warning" ? "warning" : "info",
            icon: action.tone === "danger" ? "!" : action.tone === "warning" ? "◐" : "◎",
            title: action.title || "Задача смены",
            hint: action.subtitle || action.description || action.detail || "",
            action: action.action || "",
            id: action.record_id || "",
            route: action.route || action.route_target || ""
        });
    });
    if (Number(r.low_stock_count || 0) > 0) {
        items.push({ tone: "warning", icon: "▦", title: `Склад: ${r.low_stock_count} позиций ниже минимума`, hint: "Проверьте закупки", action: "open-inventory", route: "inventory" });
    }
    if (state.updateStatus?.ok && state.updateStatus?.release?.is_newer) {
        items.push({ tone: "info", icon: "⬢", title: "Доступно обновление CRM", hint: state.updateStatus.release?.name || "", action: "open-updates", route: "updates" });
    }
    return items;
}

function renderBell() {
    const list = $("#bellList");
    const emptyEl = $("#bellEmpty");
    const count = $("#bellCount");
    if (!list) return;
    const items = collectBellItems();
    if (!items.length) {
        list.innerHTML = "";
        if (emptyEl) emptyEl.hidden = false;
        if (count) { count.hidden = true; count.textContent = "0"; }
        $("#bellBtn")?.setAttribute("aria-label", "Уведомления: новых событий нет");
        return;
    }
    if (emptyEl) emptyEl.hidden = true;
    if (count) { count.hidden = false; count.textContent = String(items.length > 99 ? "99+" : items.length); }
    $("#bellBtn")?.setAttribute("aria-label", `Уведомления: ${items.length} ${pluralRu(items.length, "событие", "события", "событий")}`);
    list.innerHTML = items.map(item => `
        <button type="button" class="bell-item" data-tone="${esc(classToken(item.tone || "info"))}"
            data-bell-action="${esc(item.action)}"
            data-bell-route="${esc(item.route || "")}"
            data-bell-id="${esc(item.id || "")}">
            <span aria-hidden="true">${esc(item.icon)}</span>
            <span><strong>${esc(item.title)}</strong>${item.hint ? `<div class="meta">${esc(item.hint)}</div>` : ""}</span>
            <span class="muted" aria-hidden="true">›</span>
        </button>
    `).join("");
}

function renderShell() {
    renderBreadcrumbs();
    renderStatusBar();
    updateSyncChip();
    renderBell();
}

let mobileNavTabbableSnapshot = [];
let mobileNavLastFocusedElement = null;

function meaningfulActiveElement(fallback = null) {
    const active = document.activeElement;
    return active instanceof HTMLElement && active !== document.body && active !== document.documentElement
        ? active
        : fallback;
}

function mobileNavFocusableElements() {
    const sidebar = $("#appSidebar");
    return sidebar ? $$('a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])', sidebar)
        .filter(element => !element.closest('[hidden], [aria-hidden="true"]') && (element.getClientRects().length > 0 || element === document.activeElement)) : [];
}

function setSidebarInteractive(sidebar, isInteractive) {
    if (!sidebar) return;
    if ("inert" in sidebar) {
        sidebar.inert = !isInteractive;
    }
    if (isInteractive) {
        mobileNavTabbableSnapshot.forEach(({ element, tabindex }) => {
            if (!document.contains(element)) return;
            if (tabindex === null) element.removeAttribute("tabindex");
            else element.setAttribute("tabindex", tabindex);
        });
        mobileNavTabbableSnapshot = [];
        return;
    }
    if ("inert" in sidebar || mobileNavTabbableSnapshot.length) return;
    mobileNavTabbableSnapshot = $$('a[href], button, textarea, input, select, [tabindex]', sidebar).map(element => ({
        element,
        tabindex: element.getAttribute("tabindex")
    }));
    mobileNavTabbableSnapshot.forEach(({ element }) => element.setAttribute("tabindex", "-1"));
}

function focusMobileNavStart() {
    const sidebar = $("#appSidebar");
    const preferred = $("#nav button.active", sidebar) || mobileNavFocusableElements()[0] || sidebar;
    preferred?.focus({ preventScroll: true });
}

function setMobileNavOpen(isOpen, options = {}) {
    const isMobile = window.matchMedia && window.matchMedia("(max-width: 1024px)").matches;
    const nextOpen = Boolean(isOpen && isMobile);
    const wasOpen = document.body.classList.contains("mobile-nav-open");
    document.body.classList.toggle("mobile-nav-open", nextOpen);
    const button = $("#mobileNavToggle");
    const backdrop = $("#mobileNavBackdrop");
    const sidebar = $("#appSidebar");
    const main = $(".main");
    if (button) {
        button.setAttribute("aria-expanded", nextOpen ? "true" : "false");
        button.setAttribute("aria-label", nextOpen ? "Закрыть навигацию" : "Открыть навигацию");
    }
    if (backdrop) backdrop.hidden = !nextOpen;
    if (sidebar) {
        if (isMobile && !nextOpen) sidebar.setAttribute("aria-hidden", "true");
        else sidebar.removeAttribute("aria-hidden");
        setSidebarInteractive(sidebar, !isMobile || nextOpen);
    }
    if (main) {
        if ("inert" in main) main.inert = nextOpen;
        main.toggleAttribute("aria-hidden", nextOpen);
    }
    if (nextOpen && !wasOpen) {
        mobileNavLastFocusedElement = meaningfulActiveElement(button);
        requestAnimationFrame(focusMobileNavStart);
    } else if (!nextOpen && wasOpen && options.restoreFocus !== false) {
        const restoreTarget = mobileNavLastFocusedElement && document.contains(mobileNavLastFocusedElement)
            ? mobileNavLastFocusedElement
            : button;
        restoreTarget?.focus({ preventScroll: true });
        mobileNavLastFocusedElement = null;
    }
}

function handleMobileNavKeydown(event) {
    if (!document.body.classList.contains("mobile-nav-open")) return;
    if (event.key === "Escape") {
        event.preventDefault();
        setMobileNavOpen(false);
        return;
    }
    if (event.key !== "Tab") return;
    const focusable = mobileNavFocusableElements();
    if (!focusable.length) {
        event.preventDefault();
        $("#appSidebar")?.focus({ preventScroll: true });
        return;
    }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (!$("#appSidebar")?.contains(document.activeElement)) {
        event.preventDefault();
        first.focus({ preventScroll: true });
    } else if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus({ preventScroll: true });
    } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus({ preventScroll: true });
    }
}

function initMobileNavigation() {
    const button = $("#mobileNavToggle");
    const backdrop = $("#mobileNavBackdrop");
    const sidebar = $("#appSidebar");
    if (!button || !backdrop || !sidebar || button.dataset.bound) return;
    button.dataset.bound = "1";
    const sync = () => {
        const mobile = window.matchMedia ? window.matchMedia("(max-width: 1024px)").matches : false;
        if (!mobile) {
            setMobileNavOpen(false, { restoreFocus: false });
            sidebar.removeAttribute("aria-hidden");
            setSidebarInteractive(sidebar, true);
        } else {
            setMobileNavOpen(document.body.classList.contains("mobile-nav-open"), { restoreFocus: false });
        }
    };
    button.addEventListener("click", () => {
        closeTransientPanels();
        setMobileNavOpen(!document.body.classList.contains("mobile-nav-open"));
    });
    backdrop.addEventListener("click", () => setMobileNavOpen(false));
    document.addEventListener("keydown", handleMobileNavKeydown);
    window.addEventListener("resize", () => {
        updateTopbarOffset();
        sync();
    });
    if (window.matchMedia) {
        const query = window.matchMedia("(max-width: 1024px)");
        const onMediaChange = () => {
            updateTopbarOffset();
            sync();
        };
        if (query.addEventListener) query.addEventListener("change", onMediaChange);
        else if (query.addListener) query.addListener(onMediaChange);
    }
    updateTopbarOffset();
    sync();
}

function menuPanelItems(panel) {
    return panel ? $$('button:not([disabled]), [role="menuitem"]:not([disabled])', panel) : [];
}

function focusMenuPanelItem(panel, index = 0) {
    const items = menuPanelItems(panel);
    if (!items.length) return;
    items[((index % items.length) + items.length) % items.length].focus();
}

function handleMenuPanelKeydown(event, panel, triggerButton, closePanel, onOpenItem = null) {
    const items = menuPanelItems(panel);
    const activeIndex = items.findIndex(item => item === document.activeElement);
    if (event.key === "Escape") {
        event.preventDefault();
        closePanel(false, { restoreFocus: true });
    } else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        focusMenuPanelItem(panel, activeIndex + (event.key === "ArrowDown" ? 1 : -1));
    } else if (event.key === "Home") {
        event.preventDefault();
        focusMenuPanelItem(panel, 0);
    } else if (event.key === "End") {
        event.preventDefault();
        focusMenuPanelItem(panel, items.length - 1);
    } else if ((event.key === "Enter" || event.key === " ") && activeIndex >= 0) {
        if (onOpenItem) {
            event.preventDefault();
            onOpenItem(items[activeIndex]);
        }
    } else if (!panel?.contains(document.activeElement) && triggerButton) {
        focusMenuPanelItem(panel, 0);
    }
}

function initShell() {
    initMobileNavigation();
    const collapseBtn = $("#sidebarCollapse");
    if (collapseBtn && !collapseBtn.dataset.bound) {
        collapseBtn.dataset.bound = "1";
        const saved = safeStorageGet("sto-crm-sidebar") === "collapsed";
        document.body.classList.toggle("sidebar-collapsed", saved);
        collapseBtn.setAttribute("aria-pressed", saved ? "true" : "false");
        collapseBtn.addEventListener("click", () => {
            const mobile = window.matchMedia && window.matchMedia("(max-width: 1024px)").matches;
            if (mobile) {
                setMobileNavOpen(!document.body.classList.contains("mobile-nav-open"));
                return;
            }
            const next = !document.body.classList.contains("sidebar-collapsed");
            document.body.classList.toggle("sidebar-collapsed", next);
            safeStorageSet("sto-crm-sidebar", next ? "collapsed" : "open");
            collapseBtn.setAttribute("aria-pressed", next ? "true" : "false");
        });
    }

    $("#brandHome")?.addEventListener("click", () => setRoute("dashboard"));

    const primary = $("#primaryCtaBtn");
    const more = $("#primaryCtaMore");
    const ctaMenu = $("#primaryCtaMenu");
    if (primary && more && ctaMenu && !more.dataset.bound) {
        more.dataset.bound = "1";
        const actionMap = {
            "new-order": openOrderModal,
            "new-appointment": openAppointmentModal,
            "new-customer": openCustomerModal,
            "new-vehicle": openVehicleModal,
            "new-inventory": openInventoryModal
        };
        const runAction = action => {
            if (typeof actionMap[action] === "function") actionMap[action]();
        };
        const setCtaMenuOpen = (isOpen, { focusFirst = false, restoreFocus = false } = {}) => {
            if (isOpen) closeTransientPanels("cta");
            ctaMenu.hidden = !isOpen;
            more.setAttribute("aria-expanded", isOpen ? "true" : "false");
            if (isOpen) updateTopbarOffset();
            if (isOpen && focusFirst) focusMenuPanelItem(ctaMenu, 0);
            if (!isOpen && restoreFocus) more.focus({ preventScroll: true });
        };
        const activateCtaItem = item => {
            if (!item) return;
            setCtaMenuOpen(false);
            runAction(item.dataset.action);
        };
        primary.addEventListener("click", () => runAction(primary.dataset.action || "new-order"));
        more.addEventListener("click", event => {
            event.stopPropagation();
            setCtaMenuOpen(ctaMenu.hidden, { focusFirst: ctaMenu.hidden });
        });
        more.addEventListener("keydown", event => {
            if (!["ArrowDown", "Enter", " "].includes(event.key)) return;
            event.preventDefault();
            setCtaMenuOpen(true, { focusFirst: true });
        });
        ctaMenu.addEventListener("keydown", event => handleMenuPanelKeydown(event, ctaMenu, more, setCtaMenuOpen, activateCtaItem));
        ctaMenu.addEventListener("click", event => {
            const item = event.target.closest("[data-action]");
            if (!item) return;
            activateCtaItem(item);
        });
        document.addEventListener("click", event => {
            if (ctaMenu.hidden) return;
            if (ctaMenu.contains(event.target) || more.contains(event.target)) return;
            setCtaMenuOpen(false);
        });
    }

    const bellBtn = $("#bellBtn");
    const bellPanel = $("#bellPanel");
    if (bellBtn && bellPanel && !bellBtn.dataset.bound) {
        bellBtn.dataset.bound = "1";
        const setBellPanelOpen = (isOpen, { focusFirst = false, restoreFocus = false } = {}) => {
            if (isOpen) closeTransientPanels("bell");
            bellPanel.hidden = !isOpen;
            bellBtn.setAttribute("aria-expanded", isOpen ? "true" : "false");
            if (isOpen) {
                renderBell();
                updateTopbarOffset();
            }
            if (isOpen && focusFirst) focusMenuPanelItem(bellPanel, 0);
            if (!isOpen && restoreFocus) bellBtn.focus({ preventScroll: true });
        };
        const activateBellItem = item => {
            if (!item) return;
            const route = item.dataset.bellRoute;
            const action = item.dataset.bellAction;
            const id = item.dataset.bellId || "";
            setBellPanelOpen(false);
            if (action && ["edit-order", "edit-appointment", "edit-customer", "edit-vehicle", "edit-inventory"].includes(action)) {
                openBellTarget(action, id, route).catch(showError);
                return;
            }
            if (route && routes[route]) setRoute(route);
        };
        bellBtn.addEventListener("click", event => {
            event.stopPropagation();
            setBellPanelOpen(bellPanel.hidden, { focusFirst: bellPanel.hidden });
        });
        bellBtn.addEventListener("keydown", event => {
            if (!["ArrowDown", "Enter", " "].includes(event.key)) return;
            event.preventDefault();
            setBellPanelOpen(true, { focusFirst: true });
        });
        document.addEventListener("click", event => {
            if (bellPanel.hidden) return;
            if (bellPanel.contains(event.target) || bellBtn.contains(event.target)) return;
            setBellPanelOpen(false);
        });
        bellPanel.addEventListener("keydown", event => handleMenuPanelKeydown(event, bellPanel, bellBtn, setBellPanelOpen, activateBellItem));
        $("#bellClose")?.addEventListener("click", () => setBellPanelOpen(false, { restoreFocus: true }));
        bellPanel.addEventListener("click", event => {
            const item = event.target.closest("[data-bell-route], [data-bell-action]");
            if (!item) return;
            activateBellItem(item);
        });
    }

    $("#syncChip")?.addEventListener("click", () => {
        if (!state.loading) loadData().then(() => toast("Обновлено")).catch(showError);
    });
    $("#breadcrumbs")?.addEventListener("click", event => {
        const btn = event.target.closest("[data-crumb-route]");
        if (btn?.dataset.crumbRoute && routes[btn.dataset.crumbRoute]) setRoute(btn.dataset.crumbRoute);
    });

    bindShellShortcuts();
    setInterval(renderShell, 30000);
    renderShell();
}

function bindShellShortcuts() {
    if (document.documentElement.dataset.shellShortcutsBound) return;
    document.documentElement.dataset.shellShortcutsBound = "1";
    const routeKeys = { d: "dashboard", p: "dashboard", a: "appointments", o: "orders", c: "customers", v: "vehicles", k: "catalog", s: "inventory", r: "reports", u: "updates" };
    const newKeys = { o: openOrderModal, a: openAppointmentModal, c: openCustomerModal, v: openVehicleModal, s: openInventoryModal };
    let keySequence = "";
    let keyTimer = null;
    const resetSequence = () => { keySequence = ""; };
    const inEditable = el => {
        if (!el) return false;
        const tag = el.tagName;
        return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || el.isContentEditable;
    };
    const inInteractiveContext = el => Boolean(el?.closest?.('input, textarea, select, button, a[href], [role="button"], [role="menuitem"], [role="option"], [contenteditable="true"]'));
    document.addEventListener("keydown", event => {
        if (event.defaultPrevented || event.metaKey || event.altKey || event.isComposing) return;
        const interactive = inInteractiveContext(event.target);
        if (event.ctrlKey && (event.key === "b" || event.key === "B")) {
            if (inEditable(event.target)) return;
            event.preventDefault();
            $("#sidebarCollapse")?.click();
            return;
        }
        if (event.ctrlKey || interactive) return;
        if ($("#modalBackdrop")?.classList.contains("open") || $("#commandPalette")?.classList.contains("open")) return;
        if (event.key === "/") {
            const input = $("#globalSearch");
            if (input) {
                event.preventDefault();
                input.focus({ preventScroll: false });
                input.select?.();
            }
            return;
        }
        if (event.key === "?") {
            event.preventDefault();
            openCommandPalette();
            return;
        }
        if (event.key === "Escape") { resetSequence(); return; }
        const lower = event.key.length === 1 ? event.key.toLowerCase() : event.key;
        if (keySequence === "g" && routeKeys[lower]) {
            event.preventDefault();
            setRoute(routeKeys[lower]);
            resetSequence();
            return;
        }
        if (keySequence === "n" && newKeys[lower]) {
            event.preventDefault();
            newKeys[lower]();
            resetSequence();
            return;
        }
        if (lower === "g" || lower === "n") {
            keySequence = lower;
            clearTimeout(keyTimer);
            keyTimer = setTimeout(resetSequence, 1100);
            return;
        }
        if (lower === "r" && keySequence === "") {
            event.preventDefault();
            loadData().then(() => toast("Обновлено")).catch(showError);
            return;
        }
        resetSequence();
    });
}


function updateSearchClear() {
    const clearButton = $("#clearSearch");
    if (clearButton) clearButton.hidden = !state.q;
}

function clearGlobalSearch() {
    const input = $("#globalSearch");
    state.q = "";
    state.customerPage = 1;
    state.catalogLimit = 60;
    if (input) {
        input.value = "";
        input.focus({ preventScroll: true });
    }
    updateSearchClear();
    clearTimeout(state.searchTimer);
    loadData().catch(showError);
}

function commandItems() {
    return [
        { icon: "П", title: "Панель", hint: "Сводка смены", keys: "G D", run: () => setRoute("dashboard") },
        { icon: "З", title: "Новая запись", hint: "Календарь приемки", keys: "N A", run: () => openAppointmentModal() },
        { icon: "№", title: "Новый заказ", hint: "Работы и оплаты", keys: "N O", run: () => openOrderModal() },
        { icon: "К", title: "Новый клиент", hint: "Контакт CRM", keys: "N C", run: () => openCustomerModal() },
        { icon: "А", title: "Новый автомобиль", hint: "Карточка авто", keys: "N V", run: () => openVehicleModal() },
        { icon: "С", title: "Новая позиция", hint: "Складской учет", keys: "N S", run: () => openInventoryModal() },
        { icon: "О", title: "Отчеты", hint: "Финансы и риски", keys: "G R", run: () => setRoute("reports") },
        { icon: "М", title: "Каталог авто", hint: "Марки и модели", keys: "G K", run: () => setRoute("catalog") },
        { icon: "↻", title: "Обновить", hint: "Перезагрузить данные", keys: "R", run: () => loadData().then(() => toast("Обновлено")).catch(showError) },
        { icon: "↕", title: "Плотность", hint: "Компактно / обычно", keys: "Ctrl+K → Плотность", run: () => toggleDensity() },
        { icon: "⇩", title: "Резерв", hint: "Backup SQLite", keys: "Ctrl+K → Резерв", run: () => createBackupFromUi() },
        { icon: "⬢", title: "Обновления", hint: "GitHub Releases", keys: "G U", run: () => { setRoute("updates"); checkForUpdates(true).catch(showError); } }
    ];
}

function filteredCommandItems() {
    const needle = String($("#commandSearch")?.value || "").trim().toLocaleLowerCase("ru-RU");
    if (!needle) return commandItems();
    return commandItems().filter(item => `${item.title} ${item.hint} ${item.keys}`.toLocaleLowerCase("ru-RU").includes(needle));
}

function updateCommandSearchAria(activeId = "") {
    const input = $("#commandSearch");
    if (!input) return;
    input.setAttribute("aria-expanded", $("#commandPalette")?.classList.contains("open") ? "true" : "false");
    if (activeId) input.setAttribute("aria-activedescendant", activeId);
    else input.removeAttribute("aria-activedescendant");
}

function renderCommandPalette() {
    const list = $("#commandList");
    if (!list) return;
    const items = filteredCommandItems();
    list.innerHTML = items.map((item, index) => {
        const optionId = `commandOption${index}`;
        return `
        <div id="${optionId}" class="command-item ${index === 0 ? "active" : ""}" role="option" data-command-index="${index}" aria-selected="${index === 0 ? "true" : "false"}">
            <span aria-hidden="true">${esc(item.icon)}</span>
            <span><strong>${esc(item.title)}</strong><div class="muted">${esc(item.hint)}</div></span>
            <kbd>${esc(item.keys)}</kbd>
        </div>`;
    }).join("") || `<div class="empty"><strong>Команда не найдена</strong><span>Попробуйте другой запрос.</span></div>`;
    updateCommandSearchAria(items.length ? "commandOption0" : "");
}

function openCommandPalette() {
    if (!state.data) return;
    if ($("#modalBackdrop")?.classList.contains("open")) return;
    const palette = $("#commandPalette");
    if (!palette) return;
    setMobileNavOpen(false, { restoreFocus: false });
    closeTransientPanels();
    lastFocusedElement = meaningfulActiveElement(null);
    palette.hidden = false;
    $("#commandPalette")?.classList.add("open");
    setAppInert(true);
    const input = $("#commandSearch");
    if (input) {
        input.value = "";
        renderCommandPalette();
        updateCommandSearchAria("commandOption0");
        requestAnimationFrame(() => input.focus({ preventScroll: true }));
    }
}

function closeCommandPalette() {
    const palette = $("#commandPalette");
    const wasOpen = palette?.classList.contains("open");
    palette?.classList.remove("open");
    if (palette) {
        palette.hidden = true;
    }
    if (wasOpen) setAppInert(false);
    updateCommandSearchAria("");
    if (wasOpen && lastFocusedElement && document.contains(lastFocusedElement)) {
        lastFocusedElement.focus({ preventScroll: true });
    }
    if (wasOpen) lastFocusedElement = null;
}

function runCommand(index = 0) {
    const item = filteredCommandItems()[index];
    if (!item) return;
    closeCommandPalette();
    item.run();
}

function requiresFreshCsrf(actionName = "это действие") {
    if (state.data?.app?.csrf_token) return true;
    toast(`Нет активной сессии безопасности: обновите данные, чтобы выполнить ${actionName}.`, "error");
    loadData().catch(showError);
    return false;
}

function requireRecord(record, label = "Запись") {
    if (record) return true;
    toast(`${label} не найдена в текущей выборке. Очистите поиск или обновите данные.`, "error");
    return false;
}

async function createBackupFromUi() {
    if (!requiresFreshCsrf("резервное копирование")) return;
    try {
        const result = await api("/api/backup", { method: "POST", body: "{}" });
        state.lastBackupAt = new Date().toISOString();
        renderShell();
        toast(`Резервная копия: ${result.display_path || result.filename || result.path}`);
    } catch (error) {
        showError(error);
    }
}

function sectionIntro(title, text, options = {}) {
    const className = options.hero ? "section-card hero-card" : "section-card";
    const eyebrow = options.eyebrow ? `<div class="hero-eyebrow">${esc(options.eyebrow)}</div>` : "";
    const summary = (options.summary || []).length
        ? `<div class="hero-summary">${options.summary.map(item => `<span class="context-pill ${esc(classToken(item.tone || ""))}"><small>${esc(item.label)}</small><strong>${esc(item.value)}</strong></span>`).join("")}</div>`
        : "";
    const actions = (options.actions || []).length
        ? `<div class="hero-actions">${options.actions.map(action => action.action === "export-csv"
            ? `<button class="btn ghost" type="button" data-action="export-csv" data-export="${esc(action.export || "")}">${esc(action.label || "CSV")}</button>`
            : `<button class="btn ${esc(action.className || "")}" type="button" data-action="${esc(action.action || "")}">${esc(action.label || "Открыть")}</button>`).join("")}</div>`
        : "";
    const stats = (options.stats || []).length
        ? `<div class="hero-stat-stack">${options.stats.map(item => `<div class="hero-stat"><strong>${esc(item.value)}</strong><span>${esc(item.label)}</span></div>`).join("")}</div>`
        : "";
    if (options.hero) {
        return `<section class="${className}"><div class="hero-layout"><div>${eyebrow}<h3>${esc(title)}</h3><p>${esc(text)}</p>${summary}${actions}</div>${stats}</div></section>`;
    }
    return `<section class="${className}"><h3>${esc(title)}</h3><p>${esc(text)}</p></section>`;
}

function emptyState(title, text, action = "") {
    return `<div class="empty"><strong>${esc(title)}</strong><span>${esc(text)}</span>${action}</div>`;
}

function insightCard(label, value, hint, options = {}) {
    const icon = options.icon || String(label || "").trim().slice(0, 1).toLocaleUpperCase("ru-RU") || "•";
    const help = options.help ? helpTip(options.help) : "";
    return `<article class="insight-card" aria-label="${esc(`${label}: ${value}. ${hint}`)}"><div class="insight-head"><small>${esc(label)}${help}</small><span class="insight-icon" aria-hidden="true">${esc(icon)}</span></div><strong>${esc(value)}</strong><span class="muted">${esc(hint)}</span></article>`;
}

function viewHeading(title, text, meta = [], actions = []) {
    const metaHtml = meta.length ? `<div class="view-meta">${meta.map(item => `<span class="count-pill">${esc(item)}</span>`).join("")}</div>` : "";
    const actionsHtml = actions.length ? `<div class="view-heading-actions">${actions.map(action => {
        const disabledAttr = action.disabled ? " disabled" : "";
        const titleAttr = action.title ? ` title="${esc(action.title)}"` : "";
        const exportAttr = action.export ? ` data-export="${esc(action.export)}"` : "";
        const ariaDisabledAttr = action.disabled ? ' aria-disabled="true"' : "";
        if (action.action === "export-csv") {
            return `<button class="btn ghost" type="button" data-action="export-csv" data-export="${esc(action.export || "")}"${titleAttr}${disabledAttr}${ariaDisabledAttr}>${esc(action.label || "CSV")}</button>`;
        }
        return `<button class="btn ${esc(action.className || "")}" type="button" data-action="${esc(action.action || "")}"${exportAttr}${titleAttr}${disabledAttr}${ariaDisabledAttr}>${esc(action.label || "Открыть")}</button>`;
    }).join("")}</div>` : "";
    return `<section class="view-heading"><div><h2>${esc(title)}</h2><p>${esc(text)}</p>${metaHtml}</div>${actionsHtml}</section>`;
}

function tableHead(labels) {
    return `<tr>${labels.map(label => {
        if (typeof label === "string") {
            const text = label || "Действия";
            const content = label ? esc(label) : `<span class="sr-only">${esc(text)}</span>`;
            return `<th scope="col">${content}</th>`;
        }
        const text = label.text || "Действия";
        const className = label.className ? ` class="${esc(label.className)}"` : "";
        const content = label.text ? esc(label.text) : `<span class="sr-only">${esc(text)}</span>`;
        return `<th scope="col"${className}>${content}</th>`;
    }).join("")}</tr>`;
}

function labeledField(id, label, controlHtml, span = "", hint = "") {
    const hintId = hint ? `${id}_hint` : "";
    const control = hint
        ? String(controlHtml).replace(/<(input|select|textarea)\b(?![^>]*\baria-describedby=)/i, `<$1 aria-describedby="${esc(hintId)}"`)
        : controlHtml;
    const hintHtml = hint ? `<div class="field-hint" id="${esc(hintId)}">${esc(hint)}</div>` : "";
    return `<div class="field ${esc(span)}"><label for="${esc(id)}">${esc(label)}</label>${control}${hintHtml}</div>`;
}

function fieldId(formScope, name) {
    return `${formScope}_${name}`.replace(/[^a-zA-Z0-9_-]/g, "_");
}

function inputField(formScope, name, label, attributes = "", span = "", hint = "") {
    const id = fieldId(formScope, name);
    return labeledField(id, label, `<input id="${id}" name="${esc(name)}" ${attributes}>`, span, hint);
}

function readonlyValue(value) {
    return String(value ?? "").trim() ? esc(value) : "—";
}

function readonlyField(label, value, span = "") {
    return `<div class="field readonly-field ${esc(span)}"><span class="readonly-label">${esc(label)}</span><strong>${value}</strong></div>`;
}

function readonlyTextareaValue(value) {
    return `<span class="readonly-multiline">${readonlyValue(value)}</span>`;
}

function selectField(formScope, name, label, optionsHtml, attributes = "", span = "", hint = "") {
    const id = fieldId(formScope, name);
    return labeledField(id, label, `<select id="${id}" name="${esc(name)}" ${attributes}>${optionsHtml}</select>`, span, hint);
}

function hiddenInput(name, value) {
    return `<input type="hidden" name="${esc(name)}" value="${esc(value)}">`;
}

function textareaField(formScope, name, label, value = "", attributes = "", span = "", hint = "") {
    const id = fieldId(formScope, name);
    return labeledField(id, label, `<textarea id="${id}" name="${esc(name)}" ${attributes}>${esc(value)}</textarea>`, span, hint);
}

function renderDashboard() {
    const r = state.data.reports || {};
    const recent = [...(state.data.orders || [])].slice(0, 5);
    const procurement = r.procurement_plan || [];
    return `
        ${viewHeading("Рабочая смена", "Главный фокус — ближайшие действия. Смотрите план смены, риски и закупку в одном месте.", [], [
            { label: "Новый заказ", action: "new-order", className: "primary" },
            { label: "Запись", action: "new-appointment", className: "ghost" }
        ])}
        ${sectionIntro("Смена под контролем", "Premium workspace для мастера-приёмщика: индекс смены, деньги, риски, воронка и календарь на одном экране.", {
            hero: true,
            eyebrow: "Premium workspace",
            summary: [
                { label: "План", value: `${r.action_plan_total || 0} задач`, tone: r.action_plan_total ? "warn" : "ok" },
                { label: "Выручка", value: moneyCompact(r.revenue_month || 0), tone: "ok" },
                { label: "Риски", value: r.risk_total || 0, tone: r.risk_total ? "danger" : "ok" }
            ],
            actions: [
                { label: "Открыть план", action: "open-action-plan", className: "primary" },
                { label: "Отчёты", action: "open-reports", className: "ghost" }
            ],
            stats: [
                { label: "Активных заказов", value: r.active_orders || 0 },
                { label: "Записей сегодня", value: r.appointments_today_count || 0 },
                { label: "Закупка", value: procurement.length }
            ]
        })}
        <section class="primary-kpi-grid" aria-label="Ключевые показатели смены">
            ${healthMetric(r)}
            ${metric("Активная воронка", money(r.pipeline_value || 0), `${money(r.pipeline_due || 0)} ожидает оплаты`)}
            ${metric("К оплате", money(r.due_total || 0), "Долг по открытым заказам")}
            ${metric("Низкий склад", r.low_stock_count || 0, "Позиции ниже минимума", { tone: (r.low_stock_count || 0) ? "warning" : "" })}
        </section>
        ${safeStorageGet("sto-crm-dashboard-hints-dismissed") === "1" ? "" : `<section class="business-hints" aria-label="Визуальные подсказки панели">
            <strong>Подсказки</strong>
            <span class="hint-chip" data-tone="ok"><span class="hint-dot ok" aria-hidden="true"></span>Индекс 0–100 показывает здоровье смены</span>
            <span class="hint-chip" data-tone="warn"><span class="hint-dot warning" aria-hidden="true"></span>Приоритет — что открыть первым</span>
            <span class="hint-chip" data-tone="danger"><span class="hint-dot danger" aria-hidden="true"></span>Красный и янтарный — зона риска</span>
            <button type="button" class="hint-dismiss" data-action="dismiss-dashboard-hints" aria-label="Скрыть подсказки" data-tooltip="Скрыть подсказки">×</button>
        </section>`}
        <section class="workspace-grid dashboard-focus-grid">
            <div class="dashboard-main-stack">
                <div class="panel action-center action-center-large">
                    <div class="panel-head">
                        <h3>План смены ${helpTip("Автоматический список важных действий: просрочки, сметы, follow-up, сервисные напоминания и закупка.")}</h3>
                        <span class="count-pill">${r.action_plan_total || 0}</span>
                    </div>
                    <div class="panel-body">${actionPlanList(r.action_plan || [])}</div>
                </div>
                <section class="grid-2" aria-label="Воронка и календарь смены">
                    <div class="panel">
                        <div class="panel-head"><h3>Воронка заказов</h3><button class="btn" type="button" data-action="open-orders">Заказы</button></div>
                        <div class="panel-body">${pipelineBoard(r.pipeline_by_status || [])}</div>
                    </div>
                    <div class="panel">
                        <div class="panel-head"><h3>Загрузка календаря</h3><button class="btn" type="button" data-action="open-appointments">Запись</button></div>
                        <div class="panel-body">${appointmentTimeline(r.appointment_load_7_days || [])}</div>
                    </div>
                </section>
                <details class="panel dashboard-details" open>
                    <summary><span>Последние заказы</span><span class="count-pill">${recent.length}</span></summary>
                    ${ordersTable(recent, true)}
                </details>
            </div>
            <aside class="dashboard-rail dashboard-support" aria-label="Краткий контроль смены">
                <div class="panel">
                    <div class="panel-head"><h3>Быстрые переходы</h3></div>
                    <div class="panel-body">${quickActions()}</div>
                </div>
                <div class="panel">
                    <div class="panel-head"><h3>Радар риска</h3></div>
                    <div class="panel-body">${riskRadar(r)}</div>
                </div>
                <div class="panel">
                    <div class="panel-head"><h3>Сводка базы</h3></div>
                    <div class="panel-body">${miniLedger(r)}</div>
                </div>
                <div class="panel">
                    <div class="panel-head"><h3>Закупка и CRM</h3><button class="btn" type="button" data-action="open-inventory">Склад</button></div>
                    <div class="panel-body split-stack">
                        <div><h4 class="mini-title">Закупка</h4>${procurementList(r.procurement_plan || [])}</div>
                        <div><h4 class="mini-title">Задачи</h4>${crmTaskList(r)}</div>
                    </div>
                </div>
                <div class="panel">
                    <div class="panel-head"><h3>Ответственные</h3></div>
                    <div class="panel-body">${workloadList(r.workload_by_responsible || [])}</div>
                </div>
            </aside>
        </section>
    `;
}

function metric(label, value, hint, options = {}) {
    const toneClass = options.tone ? ` tone-${classToken(options.tone)}` : "";
    const icon = options.icon || String(label || "").trim().slice(0, 1).toLocaleUpperCase("ru-RU") || "•";
    const help = options.help ? helpTip(options.help) : "";
    return `<article class="metric${toneClass}" aria-label="${esc(`${label}: ${value}. ${hint}`)}"><div class="metric-top"><small>${esc(label)}${help}</small><span class="metric-icon" aria-hidden="true">${esc(icon)}</span></div><strong>${esc(value)}</strong><div class="trend">${esc(hint)}</div></article>`;
}

function miniLedger(report) {
    const cells = [
        ["Заказов", report.orders_total || 0],
        ["Закрыто", report.closed_orders_count || 0],
        ["Клиентов", report.customers_total ?? state.data.lookups.customers.length],
        ["Авто", report.vehicles_total ?? state.data.lookups.vehicles.length]
    ];
    return `<div class="mini-ledger">${cells.map(([label, value]) => `<div class="mini-ledger-card"><small>${esc(label)}</small><strong>${esc(value)}</strong></div>`).join("")}</div>`;
}

function riskRadar(report) {
    const rows = [
        { label: "Просрочки", value: report.overdue_orders_count || 0, max: 8, tone: "danger" },
        { label: "Склад", value: report.low_stock_count || 0, max: 8, tone: "info" },
        { label: "Сметы", value: (report.authorizations_pending || []).length, max: 8, tone: "warning" }
    ];
    return `<div class="signal-grid">${rows.map(row => {
        const width = Number(row.value || 0) / Math.max(1, row.max) * 100;
        return `<div class="signal-row"><div class="signal-row-head"><strong>${esc(row.label)}</strong><span>${esc(row.value)}</span></div><div class="signal-track" role="img" aria-label="${esc(row.label)}: ${esc(row.value)}"><div class="signal-fill ${esc(row.tone)} ${widthClassFromPercent(width)}"></div></div></div>`;
    }).join("")}</div>`;
}

function quickActions() {
    const actions = [
        ["open-orders", "№", "Заказы", "Открыть воронку и статусы", "orders", "G O"],
        ["open-appointments", "▤", "Календарь", "Записи и ближайшие визиты", "appointments", "G A"],
        ["open-inventory", "▦", "Склад", "Остатки и закупка", "inventory", "G S"],
        ["open-reports", "↗", "Отчёты", "Финансы и загрузка", "reports", "G R"]
    ];
    return `<div class="quick-grid">${actions.map(([action, icon, title, hint, target, keys]) => `<button class="quick-tile" type="button" data-action="${esc(action)}" data-route-target="${esc(target)}" data-tooltip="${esc(title)} · ${esc(keys)}"><span class="quick-icon" aria-hidden="true">${esc(icon)}</span><strong>${esc(title)} <kbd>${esc(keys)}</kbd></strong><span>${esc(hint)}</span></button>`).join("")}</div>`;
}

function healthMetric(report) {
    const score = Math.max(0, Math.min(100, Number(report.business_health_score || 0)));
    return `<article class="metric health-card" aria-label="Индекс смены: ${score} из 100"><div class="metric-top"><small>Индекс смены</small><span class="metric-icon" aria-hidden="true">↗</span></div><strong><span class="health-score">${score}</span><span>/100</span></strong><div class="trend">${esc(report.business_health_label || "Контроль")} · просрочки и склад</div></article>`;
}

function pipelineBoard(statuses = []) {
    const active = statuses.filter(column => !["cancelled"].includes(column.status));
    if (!active.length) return `<div class="muted">Воронка пока пуста.</div>`;
    return `<div class="pipeline-board">${active.map(column => `
        <article class="pipeline-column">
            <div class="pipeline-head"><strong>${esc(column.label)}</strong><span class="count-pill">${column.count}</span></div>
            <div class="pipeline-body">
                <div class="muted">${money(column.total)} · долг ${money(column.due)}</div>
                ${(column.orders || []).slice(0, 3).map(order => {
                    const overdue = (state.data?.reports?.overdue_orders || []).some(item => Number(item.id) === Number(order.id));
                    return `
                    <div class="deal-card ${overdue ? "overdue" : ""}">
                        <strong>${esc(order.number || "Без номера")}</strong>
                        <div class="muted">${esc(order.customer_name || "")} · ${esc(order.vehicle || "Авто не выбрано")}</div>
                        <div>${money(order.total)} · ${esc(priorityLabels[order.priority] || order.priority || "")}</div>
                        <button class="btn ghost" type="button" data-action="edit-order" data-id="${safeRecordId(order.id)}" aria-label="Открыть заказ-наряд ${esc(order.number || order.id)}">Открыть</button>
                    </div>`;
                }).join("") || `<div class="muted">Нет заказов в статусе.</div>`}
            </div>
        </article>`).join("")}</div>`;
}

function appointmentTimeline(days = []) {
    if (!days.length) return `<div class="muted">Нет данных календаря.</div>`;
    const todayKey = localDateKey();
    const maxCount = Math.max(...days.map(day => Number(day.count || 0)), 1);
    return `<div class="timeline">${days.map(day => {
        const width = Number(day.count || 0) ? Math.max(8, Math.round(Number(day.count || 0) / maxCount * 100)) : 0;
        return `
        <article class="timeline-day ${day.date === todayKey ? "today" : ""}">
            <strong><span>${esc(day.label)}</span><span class="count-pill">${esc(day.count)}</span></strong>
            <div class="bar-track" aria-label="Загрузка ${esc(day.label)}: ${esc(day.count)}"><div class="bar-fill ${widthClassFromPercent(width)}"></div></div>
            <div class="timeline-list">${(day.appointments || []).slice(0, 2).map(item => `<span>${esc(dateShort(item.scheduled_at))} · ${esc(item.customer_name || "")}</span>`).join("") || `<span class="muted">Свободно</span>`}</div>
        </article>`;
    }).join("")}</div>`;
}


function procurementList(items = []) {
    if (!items.length) return `<div class="muted">Склад в нормативе.</div>`;
    return `<div class="stack">${items.map(item => `
        <div>
            <strong>${esc(item.name)} ${item.urgency === "critical" ? `<span class="danger-text">критично</span>` : ""}</strong>
            <div class="muted">${esc(item.sku || "без артикула")} · заказать ${qty(item.reorder_quantity)} ${esc(item.unit || "шт")} · бюджет ${money(item.budget)}</div>
        </div>`).join("")}</div>`;
}

function workloadList(items = []) {
    if (!items.length) return `<div class="muted">Ответственные пока не назначены.</div>`;
    return `<div class="stack">${items.map(item => `
        <div>
            <strong>${esc(item.name)}</strong>
            <div class="muted">${item.orders_count} заказов · ${money(item.total)} в работе · ${item.overdue_count} просрочено</div>
        </div>`).join("")}</div>`;
}

function actionPlanList(items = []) {
    if (!items.length) {
        return `<div class="empty"><strong>План смены чист</strong><span>Нет просрочек, срочных закупок и задач follow-up.</span></div>`;
    }
    const visible = items.slice(0, 8);
    const hiddenCount = Math.max(0, items.length - visible.length);
    const hiddenNote = hiddenCount ? `<div class="action-more muted">Еще ${hiddenCount} ${pluralRu(hiddenCount, "задача", "задачи", "задач")} — откройте профильный раздел.</div>` : "";
    return `<div class="action-stream">${visible.map(item => {
        const meta = [
            item.customer_name,
            item.vehicle,
            item.due_at ? dateShort(item.due_at) : "",
            Number(item.amount || 0) ? moneyCompact(item.amount) : ""
        ].filter(Boolean);
        return `<article class="action-card" data-tone="${esc(classToken(item.tone || "info"))}">
            <div>
                <strong>${esc(item.title)}</strong>
                <p>${esc(item.detail || "")}</p>
                <div class="action-meta">
                    <span class="action-priority">${esc(item.priority_label || "Планово")}</span>
                    ${meta.map(value => `<span class="count-pill">${esc(value)}</span>`).join("")}
                </div>
            </div>
            <div class="action-side">
                <span class="action-score" title="Приоритет задачи: ${Number(item.priority || 0)} из 100" aria-label="Приоритет задачи: ${Number(item.priority || 0)} из 100">Приоритет ${Number(item.priority || 0)}/100</span>
                <button class="btn primary" type="button" data-action="${esc(item.action || "")}" data-id="${safeRecordId(item.record_id)}" data-route-target="${esc(item.route || "dashboard")}" data-reload-before-action="1">${esc(item.cta || "Открыть")}</button>
            </div>
        </article>`;
    }).join("")}${hiddenNote}</div>`;
}

function renderAppointments() {
    const rows = state.data.appointments || [];
    const upcoming = state.data.reports?.appointments_upcoming || [];
    const body = rows.map(appointment => `
                        <tr>
                            <td class="nowrap">${dateShort(appointment.scheduled_at)}</td>
                            <td><div class="cell-title"><strong>${esc(appointment.customer_name)}</strong><div class="muted">${esc(appointment.customer_phone)} · ${esc(appointmentVehicle(appointment) || "Авто не выбрано")}</div></div></td>
                            <td>${appointmentStatusBadge(appointment.status)}</td>
                            <td>${Number(appointment.duration_minutes || 0)} мин</td>
                            <td>${esc(appointment.advisor || "")}</td>
                            <td><div class="cell-title"><strong>${esc(appointment.reason || "")}</strong><div class="muted">${esc(appointment.notes || "")}</div></div></td>
                            <td><div class="row-actions"><button class="btn" type="button" data-action="edit-appointment" data-id="${safeRecordId(appointment.id)}" aria-label="Открыть запись ${esc(appointment.customer_name || appointment.id)} на ${esc(dateShort(appointment.scheduled_at))}">Открыть</button></div></td>
                        </tr>`).join("");
    return `
        ${viewHeading("Календарь приемки", "Планируйте визиты, подтверждения, прибытия и неявки в одном аккуратном рабочем списке.", [
            `${rows.length} записей`,
            `${upcoming.length} ближайших`,
            `${state.data.reports.appointments_today_count || 0} сегодня`
        ], [
            { label: "CSV", action: "export-csv", export: "appointments", className: "ghost" },
            { label: "Новая запись", action: "new-appointment", className: "primary" }
        ])}
        <section class="kpi-grid">
            ${metric("Записей сегодня", state.data.reports.appointments_today_count || 0, "Подтверждения, приемка и прибытия")}
            ${metric("Ближайшие записи", upcoming.length, "Активные записи в календаре")}
            ${metric("Клиентов в базе", state.data.lookups.customers.length, "Можно быстро поставить в календарь")}
            ${metric("CRM задачи", state.data.reports.crm_tasks_count, "Напоминания, follow-up и отложенные работы")}
        </section>
        ${rows.length ? `<div class="table-wrap">
            <table aria-label="Таблица записей клиентов">
                <thead>${tableHead(["Дата и время", "Клиент и авто", "Статус", "Длительность", "Мастер", "Причина", ""])}</thead>
                <tbody>${body}</tbody>
            </table>
        </div>` : emptyState("Записей пока нет", "Создайте запись клиента в календаре — и она появится здесь.", `<button class="btn primary" type="button" data-action="new-appointment">+ Новая запись</button>`)}
    `;
}








function vipCustomerList(customers = []) {
    if (!customers.length) return `<div class="muted">Недостаточно истории для VIP-сегмента.</div>`;
    return `<div class="stack">${customers.map(customer => `
        <div>
            <strong>${esc(customer.customer_name)}</strong>
            <div class="muted">${esc(customer.customer_phone || "без телефона")} · ${customer.orders_count} заказов · ${money(customer.revenue)}</div>
        </div>`).join("")}</div>`;
}

function renderOrders() {
    return `
        ${viewHeading("Заказ-наряды", "Контролируйте статусы ремонта, сроки, оплаты, согласование строк и повторные продажи.", [
            `${state.data.orders.length} найдено`,
            `${state.data.reports.active_orders || 0} активных`,
            `${money(state.data.reports.pipeline_value || 0)} в работе`
        ], [
            { label: "CSV", action: "export-csv", export: "orders", className: "ghost" },
            { label: "Новый заказ", action: "new-order", className: "primary" }
        ])}
        <div class="workspace-toolbar">
            <div class="segmented" role="group" aria-label="Фильтр заказов по статусу">
                ${[["all", state.data.orders.length], ["new"], ["diagnostics"], ["estimate"], ["approved"], ["in_progress"], ["done"], ["closed"], ["cancelled"]].map(entry => {
                    const status = entry[0];
                    const label = status === "all" ? "Все" : esc(state.data.statuses[status]);
                    const counts = state.data.reports?.status_counts || {};
                    const count = status === "all"
                        ? Object.values(counts).reduce((sum, value) => sum + Number(value || 0), 0)
                        : Number(counts[status] || 0);
                    const countHtml = count ? ` <span class="seg-count" aria-hidden="true">${count}</span>` : "";
                    return `<button type="button" data-action="filter-status" data-status="${status}" class="${state.status === status ? "active" : ""}" aria-pressed="${state.status === status ? "true" : "false"}">${label}${countHtml}<span class="sr-only">${count ? ` (${count})` : ""}</span></button>`;
                }).join("")}
            </div>
        </div>
        ${ordersTable(state.data.orders, false)}
    `;
}

function orderRowActions(order) {
    const number = order.number || "заказа";
    return `<div class="row-actions order-row-actions">
        <button class="btn" type="button" data-action="edit-order" data-id="${safeRecordId(order.id)}" aria-label="Открыть заказ-наряд ${esc(number)}" data-tooltip="Открыть">Открыть</button>
        <button class="btn ghost icon-sm" type="button" data-action="print-order" data-id="${safeRecordId(order.id)}" aria-label="Печать заказ-наряда ${esc(number)}" data-tooltip="Печать"><span aria-hidden="true">⎙</span></button>
        <button class="btn ghost icon-sm" type="button" data-action="duplicate-order" data-id="${safeRecordId(order.id)}" aria-label="Повторить заказ-наряд ${esc(number)}" data-tooltip="Повторить заказ"><span aria-hidden="true">⎘</span></button>
    </div>`;
}

function ordersTable(orders, compact) {
    if (!orders.length) return emptyState("Заказ-нарядов не найдено", "Создайте первый заказ или измените поиск/фильтр.", `<button class="btn primary" type="button" data-action="new-order">Новый заказ</button>`);
    if (compact) {
        return `<div class="table-wrap">
            <table class="compact-table" aria-label="Таблица последних заказ-нарядов">
                <thead>${tableHead(["Номер", "Клиент и авто", "Статус", {text: "Итого", className: "money"}, ""])}</thead>
                <tbody>
                    ${orders.map(order => `
                        <tr>
                            <td><div class="cell-title"><strong>${esc(order.number)}</strong><span class="priority-dot" data-priority="${esc(order.priority)}">${esc(priorityLabels[order.priority] || order.priority)}</span></div></td>
                            <td><div class="cell-title"><strong>${esc(order.customer_name)}</strong><div class="muted">${esc(orderVehicle(order) || "Авто не выбрано")}</div></div></td>
                            <td>${statusBadge(order.status)}</td>
                            <td class="money">${money(order.total)}</td>
                            <td>
                                ${orderRowActions(order)}
                            </td>
                        </tr>
                    `).join("")}
                </tbody>
            </table>
        </div>`;
    }
    return `<div class="table-wrap">
        <table aria-label="Таблица заказ-нарядов">
            <thead>${tableHead(["Номер", "Клиент и авто", "Статус", "Срок", "Мастер", {text: "Итого", className: "money"}, {text: "К оплате", className: "money"}, ""])}</thead>
            <tbody>
                ${orders.map(order => `
                    <tr>
                        <td><div class="cell-title"><strong>${esc(order.number)}</strong><span class="priority-dot" data-priority="${esc(order.priority)}">${esc(priorityLabels[order.priority] || order.priority)}</span></div></td>
                        <td><div class="cell-title"><strong>${esc(order.customer_name)}</strong><div class="muted">${esc(orderVehicle(order) || "Авто не выбрано")}</div></div></td>
                        <td>${statusBadge(order.status)}</td>
                        <td class="nowrap">${dateOrDash(order.promised_at)}</td>
                        <td>${textOrDash(order.mechanic || order.advisor, "Не назначен")}</td>
                        <td class="money">${money(order.total)}</td>
                        <td class="money">${money(order.due)}</td>
                        <td>
                            ${orderRowActions(order)}
                        </td>
                    </tr>
                `).join("")}
            </tbody>
        </table>
    </div>`;
}

function renderCustomers() {
    const rows = state.data.customers;
    const total = rows.length;
    const pageSize = state.customerPageSize || 50;
    const maxPage = Math.max(1, Math.ceil(total / pageSize));
    state.customerPage = Math.min(Math.max(1, state.customerPage || 1), maxPage);
    const startIndex = (state.customerPage - 1) * pageSize;
    const pageRows = rows.slice(startIndex, startIndex + pageSize);
    const rangeText = total ? `${startIndex + 1}–${Math.min(total, startIndex + pageRows.length)} показаны` : "0 показано";
    return `
        ${viewHeading("Клиенты", "Единая клиентская база с каналами связи, согласием на напоминания, автомобилями и историей заказов.", [
            `${total} найдено`,
            rangeText,
            `${state.data.reports.customers_total ?? state.data.lookups.customers.length} всего`,
            `${state.data.reports.vip_customers?.length || 0} VIP`
        ], [
            { label: "CSV", action: "export-csv", export: "customers", className: "ghost" },
            { label: "Новый клиент", action: "new-customer", className: "primary" }
        ])}
        ${paginationControls("customers", state.customerPage, maxPage, total, pageSize, "клиентов")}
        <div class="table-wrap">
            <table aria-label="Таблица клиентов">
                <thead>${tableHead(["Клиент", "Телефон", "Email", "Канал", "Источник", "Авто", "Заказы", ""])}</thead>
                <tbody>
                    ${pageRows.map(c => `
                        <tr>
                            <td><div class="cell-title"><strong>${esc(c.name)}</strong><div class="muted">${textOrDash(c.notes)}</div></div></td>
                            <td>${textOrDash(c.phone, "Нет телефона")}</td>
                            <td>${textOrDash(c.email, "Нет email")}</td>
                            <td>${esc(channelLabel(c.preferred_channel))}${Number(c.reminder_consent) ? "" : `<div><span class="count-pill" data-tone="warn" title="Клиент отказался от напоминаний" aria-label="Без напоминаний">без напоминаний</span></div>`}</td>
                            <td>${textOrDash(c.source)}</td>
                            <td>${c.vehicles_count}</td>
                            <td><div class="cell-title"><strong>${c.orders_count}</strong><div class="muted">${c.last_order_at ? `посл. ${dateShort(c.last_order_at)}` : "нет заказов"}</div></div></td>
                            <td><div class="row-actions"><button class="btn" type="button" data-action="edit-customer" data-id="${safeRecordId(c.id)}" aria-label="Открыть клиента ${esc(c.name || c.id)}">Открыть</button></div></td>
                        </tr>`).join("") || `<tr><td colspan="8" class="empty"><strong>Клиентов не найдено</strong><span>Добавьте клиента или измените поиск.</span></td></tr>`}
                </tbody>
            </table>
        </div>
        ${paginationControls("customers", state.customerPage, maxPage, total, pageSize, "клиентов")}
    `;
}

function renderVehicles() {
    const rows = state.data.vehicles;
    const catalog = state.data.car_catalog?.stats || { makes: 0, models: 0 };
    const body = rows.map(v => `
                        <tr>
                            <td><div class="cell-title"><strong>${esc(vehicleName(v))}</strong><div class="muted">${esc(v.notes)}</div></div></td>
                            <td>${v.plate ? `<span class="plate">${esc(v.plate)}</span>` : ""}</td>
                            <td>${esc(v.vin)}</td>
                            <td><div class="cell-title">${esc(v.customer_name)}<div class="muted">${esc(v.customer_phone)}</div></div></td>
                            <td>${num(v.mileage).toLocaleString("ru-RU")} км</td>
                            <td><div class="cell-title">${esc(v.next_service_at || "")}<div class="muted">${v.next_service_mileage ? `${num(v.next_service_mileage).toLocaleString("ru-RU")} км` : ""}</div></div></td>
                            <td><div class="row-actions"><button class="btn" type="button" data-action="edit-vehicle" data-id="${safeRecordId(v.id)}" aria-label="Открыть автомобиль ${esc(vehicleName(v) || v.plate || v.id)}">Открыть</button></div></td>
                        </tr>`).join("");
    return `
        ${viewHeading("Автомобили", "Паспорт автомобиля, VIN, пробег, сервисный план и быстрый доступ к офлайн-каталогу марок и моделей.", [
            `${rows.length} авто`,
            `${catalog.makes} марок`,
            `${state.data.reports.service_reminders?.length || 0} напоминаний`
        ], [
            { label: "Каталог", action: "open-catalog", className: "ghost" },
            { label: "CSV", action: "export-csv", export: "vehicles", className: "ghost" },
            { label: "Новый автомобиль", action: "new-vehicle", className: "primary" }
        ])}
        ${rows.length ? `<div class="table-wrap">
            <table aria-label="Таблица автомобилей">
                <thead>${tableHead(["Автомобиль", "Госномер", "VIN", "Клиент", "Пробег", "Следующий сервис", ""])}</thead>
                <tbody>${body}</tbody>
            </table>
        </div>` : emptyState("Автомобилей пока нет", "Заведите карточку авто клиента — она свяжется с VIN, пробегом и сервисным планом.", `<button class="btn primary" type="button" data-action="new-vehicle">+ Новый автомобиль</button>`)}
    `;
}

function crmTaskList(report) {
    const blocks = [];
    if (report.authorizations_pending?.length) {
        blocks.push(...report.authorizations_pending.map(order => `
            <div>
                <strong>Согласовать смету ${esc(order.number)}</strong>
                <div class="muted">${esc(order.customer_name)} · ${esc(orderVehicle(order))} · ${money(order.total)}</div>
            </div>`));
    }
    if (report.followups_due?.length) {
        blocks.push(...report.followups_due.map(order => `
            <div>
                <strong>Связаться после визита ${esc(order.number)}</strong>
                <div class="muted">${esc(order.customer_name)} · ${dateShort(order.follow_up_at)}</div>
            </div>`));
    }
    if (report.service_reminders?.length) {
        blocks.push(...report.service_reminders.map(vehicle => `
            <div>
                <strong>Напомнить о сервисе</strong>
                <div class="muted">${esc(vehicle.customer_name)} · ${esc(vehicleName(vehicle))} · ${esc(channelLabels[vehicle.customer_preferred_channel] || "Телефон")}</div>
            </div>`));
    }
    if (report.deferred_work?.length) {
        blocks.push(...report.deferred_work.map(item => `
            <div>
                <strong>Вернуть ${esc(itemApprovalFallback[item.approval_status] || item.approval_status)}: ${esc(item.title)}</strong>
                <div class="muted">${esc(item.customer_name)} · ${esc(item.vehicle || "")} · ${money(item.amount)}</div>
            </div>`));
    }
    return blocks.length ? `<div class="stack">${blocks.slice(0, 8).join("")}</div>` : `<div class="muted">Нет срочных CRM задач.</div>`;
}

function renderCatalog() {
    const catalog = state.data.car_catalog || { makes: [], models: {}, stats: { makes: 0, models: 0, empty_makes: 0 } };
    const stats = catalog.stats || { makes: 0, models: 0, empty_makes: 0 };
    const entries = filteredCatalogEntries();
    const visibleEntries = entries.slice(0, Math.max(1, state.catalogLimit || 60));
    const hiddenEntries = Math.max(0, entries.length - visibleEntries.length);
    return `
        ${viewHeading("Каталог автомобилей", "Офлайн-справочник производителей и моделей помогает быстро и единообразно заполнять карточки автомобилей.", [
            `${stats.makes} производителей`,
            `${stats.models} моделей`,
            `${entries.length} в подборке`,
            `${visibleEntries.length} показано`
        ], [
            { label: "CSV каталога", action: "export-csv", export: "catalog", className: "ghost" },
            { label: "Новый автомобиль", action: "new-vehicle", className: "primary" }
        ])}
        <section class="catalog-summary">
            ${metric("Производители", stats.makes, "Полный офлайн-справочник марок", { icon: "М" })}
            ${metric("Модели", stats.models, "Доступны в карточке авто", { icon: "▦" })}
            ${metric("Без моделей", stats.empty_makes || 0, "Редкие производители из официального списка", { icon: "○", tone: stats.empty_makes ? "warn" : "" })}
            ${metric("В подборке", entries.length, `${visibleEntries.length} показано`, { icon: "⌕", tone: "info" })}
        </section>
        <div class="toolbar">
            <div class="toolbar-left">
                <div class="catalog-search">
                    <span aria-hidden="true">⌕</span>
                    <label class="sr-only" for="catalogFilter">Фильтр по марке или модели</label>
                    <input id="catalogFilter" value="${esc(state.catalogQ)}" placeholder="Фильтр по марке или модели" autocomplete="off" aria-label="Фильтр по марке или модели">
                </div>
            </div>

        </div>
        <section class="catalog-grid">
            ${visibleEntries.map(entry => catalogMakeHtml(entry.make, entry.models)).join("") || emptyState("В каталоге ничего не найдено", "Измените фильтр по марке или модели.")}
        </section>
        ${hiddenEntries ? `<div class="load-more"><button class="btn" type="button" data-action="catalog-more">Показать ещё ${Math.min(60, hiddenEntries)} из ${hiddenEntries}</button></div>` : ""}
    `;
}

function filteredCatalogEntries() {
    const catalog = state.data.car_catalog || { makes: [], models: {} };
    const needle = String(state.catalogQ || "").trim().toLocaleLowerCase("ru-RU");
    return (catalog.makes || []).map(make => ({
        make,
        models: catalog.models?.[make] || []
    })).filter(entry => {
        if (!needle) return true;
        return entry.make.toLocaleLowerCase("ru-RU").includes(needle)
            || entry.models.some(model => model.toLocaleLowerCase("ru-RU").includes(needle));
    });
}

function catalogMakeHtml(make, models) {
    const list = models.length
        ? models.map(model => `<span class="model-pill" title="${esc(make)} ${esc(model)}">${esc(model)}</span>`).join("")
        : `<span class="model-pill muted-pill">модели не указаны</span>`;
    return `<article class="catalog-make">
        <div class="catalog-make-head">
            <strong title="${esc(make)}">${esc(make)}</strong>
            <span class="count-pill">${models.length}</span>
        </div>
        <div class="model-list">${list}</div>
    </article>`;
}

function bindCatalogFilter(root) {
    const input = $("#catalogFilter", root);
    if (!input) return;
    let catalogTimer;
    input.addEventListener("input", event => {
        state.catalogQ = event.target.value;
        state.catalogLimit = 60;
        clearTimeout(catalogTimer);
        const selectionStart = input.selectionStart;
        const selectionEnd = input.selectionEnd;
        const wasFocused = document.activeElement === input;
        catalogTimer = setTimeout(() => {
            render();
            const next = $("#catalogFilter");
            if (wasFocused && next) {
                next.focus({ preventScroll: true });
                if (typeof next.setSelectionRange === "function" && selectionStart !== null && selectionEnd !== null) {
                    next.setSelectionRange(selectionStart, selectionEnd);
                }
            }
        }, 180);
    });
}

function renderInventory() {
    const rows = state.data.inventory;
    const lowCount = rows.filter(part => Number(part.is_low)).length;
    const body = rows.map(p => `
                        <tr>
                            <td><div class="cell-title"><strong>${esc(p.name)}</strong>${Number(p.is_low) ? `<div><span class="count-pill" data-tone="danger" title="Остаток ниже минимального" aria-label="Ниже минимума">ниже минимума</span></div>` : ""}</div></td>
                            <td>${esc(p.sku)}</td>
                            <td>${esc(p.brand)}</td>
                            <td>${qty(p.quantity)} ${esc(p.unit)}<div class="muted">мин. ${qty(p.min_quantity)}</div></td>
                            <td class="money">${money(p.price)}</td>
                            <td class="money">${money(p.cost)}</td>
                            <td>${esc(p.supplier)}</td>
                            <td><div class="row-actions"><button class="btn" type="button" data-action="edit-inventory" data-id="${safeRecordId(p.id)}" aria-label="Открыть складскую позицию ${esc(p.name || p.sku || p.id)}">Открыть</button></div></td>
                        </tr>`).join("");
    return `
        ${viewHeading("Склад", "Следите за остатками, себестоимостью, поставщиками и закупкой до остановки ремонта.", [
            `${rows.length} позиций`,
            `${lowCount} ниже минимума`,
            `${money(state.data.reports.inventory_value || 0)} себестоимость`
        ], [
            { label: "CSV", action: "export-csv", export: "inventory", className: "ghost" },
            { label: "Новая позиция", action: "new-inventory", className: "primary" }
        ])}
        <section class="insight-grid">
            ${insightCard("Активных позиций", rows.length, "Складские остатки в базе")}
            ${insightCard("Ниже минимума", lowCount, "Позиции для закупки")}
            ${insightCard("Стоимость склада", money(state.data.reports.inventory_value || 0), "По себестоимости остатков")}
        </section>
        ${rows.length ? `<div class="table-wrap">
            <table aria-label="Таблица складских позиций">
                <thead>${tableHead(["Позиция", "Артикул", "Бренд", "Остаток", {text: "Цена", className: "money"}, {text: "Себестоимость", className: "money"}, "Поставщик", ""])}</thead>
                <tbody>${body}</tbody>
            </table>
        </div>` : emptyState("Склад пока пуст", "Добавьте первую позицию, и она появится в таблице с остатками и минимумом.", `<button class="btn primary" type="button" data-action="new-inventory">+ Новая позиция</button>`)}
    `;
}

function renderReports() {
    const r = state.data.reports || {};
    const statusCounts = r.status_counts || {};
    const topServices = r.top_services || [];
    const maxStatus = Math.max(...Object.values(statusCounts), 1);
    const maxService = Math.max(...topServices.map(x => Number(x.total || 0)), 1);
    return `
        ${viewHeading("Отчеты и аналитика", "Финансы, маржа, загрузка, закупки и удержание клиентов для управленческих решений.", [
            `${money(r.revenue_month)} выручка`,
            `${num(r.margin_percent_month).toFixed(1)}% маржа`,
            `${r.low_stock_count || 0} складских рисков`
        ], [
            { label: "Открыть заказы", action: "open-orders", className: "ghost" },
            { label: "Склад", action: "open-inventory", className: "ghost" }
        ])}
        <div class="report-group-heading"><h3>Финансы и маржа</h3><small>Выручка, маржа и воронка</small></div>
        <section class="kpi-grid">
            ${healthMetric(r)}
            ${metric("Средний чек", money(r.avg_check), "Закрытые заказы текущего месяца")}
            ${metric("Выручка месяца", money(r.revenue_month), "Факт по закрытым")}
            ${metric("Низкий склад", r.low_stock_count, "Требуют закупки")}
        </section>
        <section class="insight-grid">
            ${insightCard("К оплате", money(r.due_total), "Все незакрытые долги")}
            ${insightCard("Маржа месяца", money(r.gross_margin_month || 0), `${num(r.margin_percent_month).toFixed(1)}% валовой маржи`)}
            ${insightCard("Конверсия смет", `${num(r.conversion_rate).toFixed(1)}%`, "Согласование → работа")}
            ${insightCard("Активная воронка", money(r.pipeline_value || 0), `${money(r.pipeline_due || 0)} ожидает оплаты`)}
            ${insightCard("Стоимость склада", money(r.inventory_value || 0), "Себестоимость остатков")}
            ${insightCard("Просрочено", r.overdue_orders_count || 0, "Заказы со сроком раньше текущего времени")}
        </section>
        <div class="report-group-heading"><h3>Операции</h3><small>Загрузка, структура заказов и топ работ</small></div>
        <section class="grid-2">
            <div class="panel">
                <div class="panel-head"><h3>Статусы заказов</h3></div>
                <div class="panel-body bars">
                    ${Object.entries(state.data.statuses).map(([key, label]) => `
                        <div class="bar">
                            <span>${esc(label)}</span>
                            <div class="bar-track" role="img" aria-label="${esc(label)}: ${statusCounts[key] || 0}"><div class="bar-fill ${widthClassFromPercent((statusCounts[key] || 0) / maxStatus * 100)}"></div></div>
                            <strong>${statusCounts[key] || 0}</strong>
                        </div>`).join("")}
                </div>
            </div>
            <div class="panel">
                <div class="panel-head"><h3>Топ работ</h3></div>
                <div class="panel-body bars">
                    ${topServices.map(item => `
                        <div class="bar">
                            <span>${esc(item.title)}</span>
                            <div class="bar-track" role="img" aria-label="${esc(item.title)}: ${money(item.total)}"><div class="bar-fill ${widthClassFromPercent(item.total / maxService * 100)}"></div></div>
                            <strong>${money(item.total)}</strong>
                        </div>`).join("") || `<div class="muted">Нет данных по работам.</div>`}
                </div>
            </div>
        </section>
        <section class="grid-2">
            <div class="panel">
                <div class="panel-head"><h3>План закупки</h3><button class="btn" type="button" data-action="open-inventory">Склад</button></div>
                <div class="panel-body">${procurementList(r.procurement_plan || [])}</div>
            </div>
            <div class="panel">
                <div class="panel-head"><h3>Загрузка ответственных</h3></div>
                <div class="panel-body">${workloadList(r.workload_by_responsible || [])}</div>
            </div>
        </section>
        <div class="report-group-heading"><h3>Клиенты</h3><small>Удержание и VIP-сегмент</small></div>
        <section class="panel">
            <div class="panel-head"><h3>VIP и удержание клиентов</h3></div>
            <div class="panel-body">${vipCustomerList(r.vip_customers)}</div>
        </section>
    `;
}

function updateStatusBadge(status) {
    if (!status) return `<span class="status s-new">Не проверено</span>`;
    if (!status.ok) return `<span class="status s-cancelled">Ошибка проверки</span>`;
    if (status.release?.is_newer) return `<span class="status s-approved">Доступна версия ${esc(status.release.version || status.release.tag)}</span>`;
    return `<span class="status s-closed">Актуальная версия</span>`;
}

function updateReleaseHtml(status) {
    if (!status) return `<div class="notice">Нажмите «Проверить обновления», чтобы получить последний релиз GitHub.</div>`;
    if (!status.ok) {
        return `<div class="notice" role="alert"><strong>Не удалось проверить обновления.</strong><p>${esc(status.error || "Проверьте интернет или доступ к GitHub.")}</p></div>`;
    }
    const release = status.release || {};
    const asset = release.asset || {};
    return `
        <div class="update-release">
            <h4>${release.is_newer ? "Новый релиз найден" : "Последний релиз GitHub"}</h4>
            <div class="update-meta">
                <span class="status ${release.is_newer ? "s-approved" : "s-closed"}">${esc(release.tag || release.version || "без тега")}</span>
                ${release.prerelease ? `<span class="status s-estimate">pre-release</span>` : ""}
                <span class="count-pill">${asset.name ? esc(asset.name) : "нет .exe в релизе"}</span>
                <span class="count-pill">${bytesText(asset.size)}</span>
            </div>
            <div class="muted">Опубликовано: ${esc(release.published_at || "—")}</div>
            ${release.body ? `<pre>${esc(release.body)}</pre>` : `<div class="muted">Описание релиза не заполнено.</div>`}
            <div class="row-actions row-actions-start">
                <a class="btn ghost" href="${esc(safeExternalUrl(release.release_url || status.releases_url, state.data?.app?.releases_url || "#"))}" target="_blank" rel="noopener noreferrer">Открыть релиз</a>
            </div>
        </div>`;
}

function renderUpdates() {
    const app = state.data.app;
    const status = state.updateStatus;
    const canInstall = Boolean(status?.ok && status.release?.is_newer && status.release?.has_asset && status.can_install);
    const installDisabled = !canInstall || state.updateInstalling;
    const installTitle = !status?.ok
        ? "Сначала выполните успешную проверку обновлений"
        : !status.release?.is_newer
            ? "Установлена последняя версия"
            : !status.release?.has_asset
                ? "В релизе нет файла STO_CRM.exe"
                : !status.can_install
                    ? "Автоустановка доступна только в собранном Windows .exe"
                    : "Скачать и установить обновление";
    return `
        ${viewHeading("Обновления", "Проверка и установка новых релизов CRM из GitHub Releases.", [
            `Версия ${esc(app.version)}`,
            status?.release?.is_newer ? `Есть ${esc(status.release.version || status.release.tag || "")}` : "Актуальная версия"
        ], [
            { label: state.updateLoading ? "Проверяем…" : "Проверить", action: "check-update", className: "ghost", disabled: state.updateLoading },
            { label: state.updateInstalling ? "Устанавливаем…" : "Установить", action: "install-update", className: "primary", disabled: installDisabled, title: installTitle }
        ])}
        <section class="update-card">
            <div class="toolbar">
                <div class="toolbar-left">
                    <h3>Обновление с GitHub</h3>
                    ${updateStatusBadge(status)}
                </div>
                <div class="toolbar-right">
                    <button class="btn ghost" type="button" data-action="check-update" ${state.updateLoading ? "disabled" : ""}>${state.updateLoading ? "Проверяем..." : "Проверить обновления"}</button>
                    <button class="btn primary" type="button" data-action="install-update" title="${esc(installTitle)}" aria-describedby="updateInstallHint" ${installDisabled ? "disabled" : ""}>${state.updateInstalling ? "Устанавливаем..." : "Установить"}</button>
                </div>
            </div>
            <p id="updateInstallHint" class="muted">${esc(installTitle)}</p>
            <p>CRM проверяет GitHub Releases выбранного публичного репозитория, читает manifest <strong>latest.json</strong> и скачивает только готовый <strong>STO_CRM.exe</strong>. Перед установкой создается резервная копия SQLite-базы, затем обновление скачивается с контролем размера и SHA-256, делает резерв текущего exe и перезапускает приложение.</p>
            <div class="update-meta">
                <span class="count-pill">Текущая версия: ${esc(app.version)}</span>
                <a class="count-pill" href="${esc(safeExternalUrl(app.repository_url))}" target="_blank" rel="noopener noreferrer">${esc(app.repository)}</a>
                <span class="count-pill">База не переносится: ${esc(app.db_path)}</span>
            </div>
            ${app.can_install_update ? "" : `<div class="notice"><strong>Вы запустили исходник Python.</strong><p>Автоустановка включается в Windows-сборке STO_CRM.exe. Для исходников обновляйте проект командой <code>git pull --ff-only</code> и перезапускайте Python.</p></div>`}
            ${updateReleaseHtml(status)}
        </section>
    `;
}

async function checkForUpdates(showToast = true) {
    if (state.updateLoading) return;
    state.updateCheckScheduled = false;
    state.updateLoading = true;
    // Перерисовываем ТОЛЬКО если пользователь находится в разделе обновлений,
    // иначе теряется фокус в глобальном поиске и перерисовываются все таблицы.
    if (state.route === "updates") render();
    try {
        state.updateStatus = await api("/api/update/status", {}, 0);
        if (showToast) {
            if (state.updateStatus.ok && state.updateStatus.release?.is_newer) toast(`Доступна версия ${state.updateStatus.release.version || state.updateStatus.release.tag}`);
            else if (state.updateStatus.ok) toast("Установлена актуальная версия");
            else toast(state.updateStatus.error || "Не удалось проверить обновления", "error");
        }
    } catch (error) {
        state.updateCheckScheduled = false;
        throw error;
    } finally {
        state.updateLoading = false;
        if (state.route === "updates") render();
        updateNavigationBadges();
    }
}

async function installUpdate() {
    if (!requiresFreshCsrf("установку обновления")) return;
    const status = state.updateStatus;
    const release = status?.release || {};
    if (state.updateInstalling) return;
    if (!status?.ok || !release.is_newer) {
        toast("Новых обновлений нет");
        return;
    }
    if (!release.has_asset) {
        toast("В релизе нет файла STO_CRM.exe", "error");
        return;
    }
    if (!status.can_install) {
        toast("Автоустановка доступна только в собранном Windows .exe", "error");
        return;
    }
    if (!confirm("Скачать обновление, закрыть CRM и перезапустить новую версию? Перед установкой будут созданы резервные копии базы SQLite и текущего exe.")) return;
    state.updateInstalling = true;
    render();
    try {
        const result = await api("/api/update/install", { method: "POST", body: "{}" }, 0);
        if (!result.updated) {
            state.updateInstalling = false;
            toast(result.message || "Обновление не требуется");
            state.updateStatus = { ...(state.updateStatus || {}), release: result.release || state.updateStatus?.release || {} };
            render();
            updateNavigationBadges();
            return;
        }
        toast(result.message || "Обновление запущено");
        const backupText = result.backup?.display_path ? ` Резервная копия базы: ${esc(result.backup.display_path)}.` : " Перед установкой создана резервная копия базы.";
        document.body.innerHTML = `<main class="shutdown-state"><section class="shutdown-card"><h1>СТО CRM обновляется</h1><p>Приложение закроется, заменит exe и запустится снова.${backupText}</p></section></main>`;
    } catch (error) {
        state.updateInstalling = false;
        render();
        throw error;
    }
}

function dispatchViewAction(source, event = null) {
    if (!source) return;
    const action = source.dataset.action;
    const id = Number(source.dataset.id || 0);
    const routeTarget = source.dataset.routeTarget;
    const runAction = () => {
        if (routeTarget && routes[routeTarget] && routeTarget !== state.route) {
            setRoute(routeTarget);
        }
        if (action === "retry-load") loadData().catch(showError);
        else if (action === "dismiss-error") {
            state.lastError = "";
            render();
        }
        else if (action === "dismiss-dashboard-hints") {
            safeStorageSet("sto-crm-dashboard-hints-dismissed", "1");
            render();
        }
        else if (action === "backup-now") {
            createBackupFromUi();
        }
        else if (action === "export-csv") {
            event?.preventDefault();
            downloadCsv(source.dataset.export).catch(showError);
        }
        else if (action === "filter-status") {
            const nextStatus = source.dataset.status;
            if (!state.data?.statuses?.[nextStatus] && nextStatus !== "all") return;
            state.status = nextStatus;
            loadData().catch(showError);
        } else if (action === "page-customers") {
            const total = state.data?.customers?.length || 0;
            const pageSize = state.customerPageSize || 50;
            const maxPage = Math.max(1, Math.ceil(total / pageSize));
            state.customerPage = Math.min(Math.max(1, Number(source.dataset.page || 1)), maxPage);
            render();
            document.querySelector(".view-heading")?.scrollIntoView({ behavior: prefersReducedMotion() ? "auto" : "smooth", block: "start" });
        } else if (action === "catalog-more") {
            state.catalogLimit = Math.min((state.catalogLimit || 60) + 60, filteredCatalogEntries().length);
            render();
        } else if (action === "new-appointment") openAppointmentModal();
        else if (action === "edit-appointment") {
            const appointment = findAppointmentById(id);
            if (requireRecord(appointment, "Запись")) openAppointmentModal(appointment);
        }
        else if (action === "new-customer") openCustomerModal();
        else if (action === "edit-customer") {
            const customer = findCustomerById(id);
            if (requireRecord(customer, "Клиент")) openCustomerModal(customer);
        }
        else if (action === "new-vehicle") openVehicleModal();
        else if (action === "edit-vehicle") {
            const vehicle = findVehicleById(id);
            if (requireRecord(vehicle, "Автомобиль")) openVehicleModal(vehicle);
        }
        else if (action === "open-catalog") setRoute("catalog");
        else if (action === "open-orders") setRoute("orders");
        else if (action === "open-appointments") setRoute("appointments");
        else if (action === "open-inventory") setRoute("inventory");
        else if (action === "open-reports") setRoute("reports");
        else if (action === "open-updates") setRoute("updates");
        else if (action === "open-action-plan") {
            const scrollActionCenter = () => document.querySelector(".action-center")?.scrollIntoView({ behavior: prefersReducedMotion() ? "auto" : "smooth", block: "start" });
            if (state.route !== "dashboard") {
                setRoute("dashboard");
                requestAnimationFrame(scrollActionCenter);
            } else {
                scrollActionCenter();
            }
        }
        else if (action === "new-inventory") openInventoryModal();
        else if (action === "edit-inventory") {
            const part = findInventoryById(id);
            if (requireRecord(part, "Складская позиция")) openInventoryModal(part);
        }
        else if (action === "new-order") openOrderModal();
        else if (action === "edit-order") openOrderModal(findOrderById(id));
        else if (action === "duplicate-order") {
            const order = findOrderById(id);
            if (requireRecord(order, "Заказ")) openOrderModal(orderDuplicateDraft(order));
        }
        else if (action === "print-order") openPrintOrder(id).catch(showError);
        else if (action === "check-update") checkForUpdates(true).catch(showError);
        else if (action === "install-update") installUpdate().catch(showError);
    };
    if (source.dataset.reloadBeforeAction === "1" && !state.offlineMode) {
        state.q = "";
        state.status = "all";
        const searchInput = $("#globalSearch");
        if (searchInput) searchInput.value = "";
        updateSearchClear();
        loadData().then(runAction).catch(showError);
    } else {
        runAction();
    }
}

async function openBellTarget(action, id, route = "") {
    const target = document.createElement("button");
    target.type = "button";
    target.dataset.action = action;
    target.dataset.id = id;
    target.dataset.routeTarget = route || "";
    target.dataset.reloadBeforeAction = "1";
    dispatchViewAction(target);
}

function bindViewActions(root) {
    root.querySelectorAll("[data-action]").forEach(button => {
        button.addEventListener("click", event => dispatchViewAction(event.currentTarget, event));
    });
}

function findById(list, id) {
    return Array.isArray(list) ? list.find(item => Number(item.id) === Number(id)) : null;
}

function findCustomerById(id) {
    return findById(state.data?.customers || [], id) || findById(state.data?.lookups?.customers || [], id) || null;
}

function findVehicleById(id) {
    return findById(state.data?.vehicles || [], id) || findById(state.data?.lookups?.vehicles || [], id) || null;
}

function findInventoryById(id) {
    return findById(state.data?.inventory || [], id) || findById(state.data?.lookups?.inventory || [], id) || null;
}

function findOrderById(id) {
    return findById(state.data?.orders || [], id) || findById(state.data?.lookups?.orders || [], id) || null;
}

function findAppointmentById(id) {
    return findById(state.data?.appointments || [], id) || findById(state.data?.lookups?.appointments || [], id) || null;
}


function orderDuplicateDraft(order = {}) {
    return {
        ...order,
        id: "",
        number: "",
        status: "new",
        paid: 0,
        closed_at: "",
        authorized_at: "",
        follow_up_at: "",
        items: (order.items || []).map(item => ({ ...item, id: "" }))
    };
}

let lastFocusedElement = null;
let appTabbableSnapshot = [];
let appInertDepth = 0;

function modalFocusableElements() {
    const modal = $("#modal");
    return $$('a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])', modal)
        .filter(element => !element.closest('[hidden], [aria-hidden="true"]') && (element.getClientRects().length > 0 || element === document.activeElement));
}

function shouldKeepModalForEscape(event) {
    if (event.defaultPrevented) return true;
    const target = event.target;
    if (!(target instanceof HTMLElement)) return false;
    if (target.isContentEditable) return true;
    if (target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement) return true;
    if (target instanceof HTMLInputElement) return false;
    return false;
}

function currentDocumentNonce() {
    const node = document.querySelector("script[nonce], style[nonce]");
    return node?.nonce || node?.getAttribute("nonce") || "";
}

function alignPrintHtmlNonce(htmlText) {
    const nonce = currentDocumentNonce();
    if (!nonce) return htmlText;
    const safeNonce = esc(nonce);
    return String(htmlText)
        .replace(/\bnonce="[^"]*"/g, `nonce="${safeNonce}"`)
        .replace(/'nonce-[^']*'/g, `'nonce-${safeNonce}'`);
}

function focusModalStart() {
    const controls = $$("input:not([type='hidden']):not([disabled]), select:not([disabled]), textarea:not([disabled])", $("#modalBody"))
        .filter(element => element instanceof HTMLElement && element.getClientRects().length > 0);
    const preferred = controls[0] || $("#modalFoot .btn.primary:not([disabled])") || $("#modalClose:not([disabled])") || $("#modal");
    preferred?.focus({ preventScroll: true });
}

function setAppInert(isInert) {
    const app = $(".app");
    if (!app) return;
    if (isInert) {
        appInertDepth += 1;
        if (appInertDepth > 1) return;
        if ("inert" in app) {
            app.removeAttribute("aria-hidden");
            app.inert = true;
            return;
        }
        app.setAttribute("aria-hidden", "true");
        appTabbableSnapshot = $$('a[href], button, textarea, input, select, [tabindex]', app).map(element => ({
            element,
            tabindex: element.getAttribute("tabindex")
        }));
        appTabbableSnapshot.forEach(({ element }) => element.setAttribute("tabindex", "-1"));
    } else {
        appInertDepth = Math.max(0, appInertDepth - 1);
        if (appInertDepth > 0) return;
        app.removeAttribute("aria-hidden");
        if ("inert" in app) app.inert = false;
        appTabbableSnapshot.forEach(({ element, tabindex }) => {
            if (!document.contains(element)) return;
            if (tabindex === null) element.removeAttribute("tabindex");
            else element.setAttribute("tabindex", tabindex);
        });
        appTabbableSnapshot = [];
    }
}

function openModal(title, body, foot, size = "") {
    const allowedSizes = new Set(["", "small", "wide"]);
    const modalSize = allowedSizes.has(size) ? size : "";
    const backdrop = $("#modalBackdrop");
    if (!backdrop) return;
    assertSafeModalMarkup(body);
    assertSafeModalMarkup(foot);
    if (backdrop.classList.contains("open")) closeModal(true, { restoreFocus: false });
    setMobileNavOpen(false, { restoreFocus: false });
    closeTransientPanels();
    lastFocusedElement = meaningfulActiveElement(null);
    $("#modalTitle").textContent = title;
    $("#modalBody").innerHTML = body;
    $("#modalFoot").innerHTML = foot;
    $("#modal").className = modalSize ? `modal ${modalSize}` : "modal";
    backdrop.hidden = false;
    $("#modalBackdrop").classList.add("open");
    state.modalDirty = false;
    setAppInert(true);
    bindModalSubmitHandlers();
    updateScrollHints($("#modal"));
    focusModalStart();
    requestAnimationFrame(focusModalStart);
}

function closeModal(force = false, options = {}) {
    if (state.saving && !force) return false;
    if (!force && state.modalDirty && !confirm("Закрыть окно без сохранения изменений?")) return false;
    const backdrop = $("#modalBackdrop");
    const wasOpen = backdrop?.classList.contains("open");
    backdrop?.classList.remove("open");
    if (backdrop) {
        backdrop.hidden = true;
    }
    if (wasOpen) setAppInert(false);
    $("#modalBody").innerHTML = "";
    $("#modalFoot").innerHTML = "";
    if (options.restoreFocus !== false && lastFocusedElement && document.contains(lastFocusedElement)) {
        lastFocusedElement.focus({ preventScroll: true });
    }
    lastFocusedElement = null;
    state.modalDirty = false;
    return true;
}

function commandPaletteFocusableElements() {
    const palette = $("#commandPalette");
    return palette ? $$("button, [href], input, select, textarea, [tabindex]:not([tabindex='-1'])", palette)
        .filter(element => !element.disabled && element.offsetParent !== null) : [];
}

function handleCommandPaletteTab(event) {
    const focusable = commandPaletteFocusableElements();
    const fallback = $("#commandSearch") || $("#commandPalette");
    if (!focusable.length) {
        event.preventDefault();
        fallback?.focus({ preventScroll: true });
        return;
    }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (!$("#commandPalette")?.contains(document.activeElement)) {
        event.preventDefault();
        first.focus({ preventScroll: true });
    } else if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus({ preventScroll: true });
    } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus({ preventScroll: true });
    }
}

function handleModalKeydown(event) {
    const commandPaletteOpen = $("#commandPalette")?.classList.contains("open");
    if ((event.ctrlKey || event.metaKey) && (event.code === "KeyK" || event.key.toLocaleLowerCase("ru-RU") === "k") && !commandPaletteOpen) {
        event.preventDefault();
        if (!$("#modalBackdrop")?.classList.contains("open")) openCommandPalette();
        return;
    }
    if (commandPaletteOpen) {
        if (event.key === "Escape") {
            event.preventDefault();
            closeCommandPalette();
        } else if (event.key === "Tab") {
            handleCommandPaletteTab(event);
        }
        return;
    }
    const backdrop = $("#modalBackdrop");
    if (!backdrop || !backdrop.classList.contains("open")) return;
    if (event.key === "Escape") {
        if (shouldKeepModalForEscape(event)) return;
        event.preventDefault();
        closeModal();
        return;
    }
    if (event.key !== "Tab") return;
    const modal = $("#modal");
    const focusable = modalFocusableElements();
    if (!focusable.length) {
        event.preventDefault();
        modal.focus();
        return;
    }
    if (!modal.contains(document.activeElement)) {
        event.preventDefault();
        focusable[0].focus();
        return;
    }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
    }
}

function bindModalSubmitHandlers() {
    const modal = $("#modal");
    $$("form", modal).forEach(form => {
        form.addEventListener("input", event => {
            markModalDirty();
            clearFormError(event.target);
        });
        form.addEventListener("change", event => {
            markModalDirty();
            clearFormError(event.target);
        });
        form.addEventListener("submit", event => {
            event.preventDefault();
            $("#modalFoot [data-save]:not([data-save='cancel']):not([data-save^='delete']):not([data-save='print-order'])")?.click();
        });
    });
}

async function openPrintOrder(id) {
    if (!requiresFreshCsrf("печать заказ-наряда")) return;
    const printButton = $(`#modalFoot [data-save="print-order"][data-id="${Number(id || 0)}"]`);
    const previousDisabled = printButton?.disabled || false;
    if (printButton) {
        printButton.disabled = true;
        printButton.setAttribute("aria-busy", "true");
    }
    const printWindow = window.open("about:blank", "_blank");
    if (!printWindow) {
        if (printButton) {
            printButton.disabled = previousDisabled;
            printButton.setAttribute("aria-busy", "false");
        }
        toast("Разрешите всплывающие окна, чтобы открыть печатную форму.", "error");
        return;
    }
    try { printWindow.opener = null; } catch { /* Some embedded browsers expose opener as readonly. */ }
    printWindow.document.write("<p>Загрузка печатной формы...</p>");
    try {
        const response = await fetch(`/print/order/${encodeURIComponent(id)}`, {
            headers: { "X-CSRF-Token": state.data.app.csrf_token },
            cache: "no-store"
        });
        const contentType = response.headers.get("Content-Type") || "";
        const bodyText = await response.text();
        if (!response.ok) {
            let message = bodyText || "Не удалось открыть печатную форму";
            if (contentType.includes("application/json")) {
                try {
                    const payload = JSON.parse(bodyText);
                    message = payload?.error || message;
                } catch { /* keep raw text if server returned malformed JSON */ }
            }
            throw new Error(message);
        }
        printWindow.document.open();
        printWindow.document.write(alignPrintHtmlNonce(bodyText));
        printWindow.document.close();
    } catch (error) {
        printWindow.close();
        throw error;
    } finally {
        if (printButton && document.contains(printButton)) {
            printButton.disabled = previousDisabled;
            printButton.setAttribute("aria-busy", "false");
        }
    }
}

function markModalDirty() {
    state.modalDirty = true;
}

function setSaveButtonsBusy(isBusy) {
    state.saving = isBusy;
    $("#modalBackdrop")?.classList.toggle("saving", isBusy);
    $$("#modalFoot [data-save], #modalClose").forEach(button => {
        if (isBusy) {
            button.dataset.wasDisabled = button.disabled ? "1" : "0";
            button.disabled = true;
            button.setAttribute("aria-busy", "true");
            return;
        }
        button.disabled = button.dataset.wasDisabled === "1";
        delete button.dataset.wasDisabled;
        button.setAttribute("aria-busy", "false");
    });
}

function collectForm(form) {
    const data = Object.fromEntries(new FormData(form).entries());
    $$('input[type="number"][name]', form).forEach(input => {
        if (data[input.name] !== undefined) data[input.name] = String(data[input.name]).replace(/\s+/g, "").replace(/,/g, ".");
    });
    $$('input[type="checkbox"][name]', form).forEach(input => {
        data[input.name] = input.checked ? (input.value || "1") : "0";
    });
    return data;
}

function reportFormValidity(form, excludeSelector = "") {
    if (!form) return true;
    if (!excludeSelector) return form.reportValidity();
    const controls = $$("input, select, textarea", form).filter(control => !control.matches(excludeSelector));
    for (const control of controls) {
        if (typeof control.reportValidity === "function" && !control.reportValidity()) return false;
    }
    return true;
}

function numericInputError(input, label) {
    if (input.validity?.badInput) return `${label}: введите число.`;
    const parsed = parseNumericInput(input.value, 0);
    if (!parsed.valid) return `${label}: введите число.`;
    const min = input.getAttribute("min");
    const max = input.getAttribute("max");
    if (min !== null && parsed.value < Number(min)) return `${label}: значение не может быть меньше ${min}.`;
    if (max !== null && parsed.value > Number(max)) return `${label}: значение не может быть больше ${max}.`;
    return "";
}

function validateLocalizedNumberInputs(form, { showError = true, excludeSelector = "" } = {}) {
    if (!form) return true;
    const inputs = $$('input[type="number"]', form).filter(input => !excludeSelector || !input.matches(excludeSelector));
    for (const input of inputs) {
        const label = input.closest(".field")?.querySelector("label")?.textContent?.trim() || input.getAttribute("aria-label") || input.name || "Поле";
        const message = numericInputError(input, label);
        input.setCustomValidity(message);
        if (message) {
            if (showError) applyFormError(new Error(message));
            return false;
        }
    }
    return true;
}

function customerOptions(selected = "") {
    const customers = state.data?.lookups?.customers || state.data?.customers || [];
    const placeholderText = customers.length ? "Выберите клиента" : "Нет клиентов";
    return `<option value="">${placeholderText}</option>` + customers.map(c => `<option value="${esc(c.id)}" ${Number(selected) === Number(c.id) ? "selected" : ""}>${esc(c.name)} · ${esc(c.phone)}</option>`).join("");
}

function vehicleOptions(customerId, selected, extraVehicles = []) {
    const normalizedCustomerId = Number(customerId || 0);
    const normalizedSelected = Number(selected || 0);
    const allVehicles = [...(state.data?.lookups?.vehicles || state.data?.vehicles || []), ...(extraVehicles || [])];
    const seen = new Set();
    const vehicles = allVehicles.filter(vehicle => {
        const vehicleId = Number(vehicle?.id || 0);
        if (!vehicleId) return false;
        if (seen.has(vehicleId)) return false;
        if (normalizedCustomerId) {
            if (Number(vehicle.customer_id) !== normalizedCustomerId) return false;
        } else if (vehicleId !== normalizedSelected) {
            return false;
        }
        seen.add(vehicleId);
        return true;
    });
    const placeholder = normalizedCustomerId || normalizedSelected ? "Не выбран" : "Сначала выберите клиента";
    return `<option value="">${placeholder}</option>` + vehicles.map(vehicle => {
        const unavailable = vehicle.deleted_at || vehicle.deleted_at === 1 || vehicle.vehicle_deleted;
        const selectedAttr = Number(selected) === Number(vehicle.id) ? "selected" : "";
        const disabledAttr = unavailable && !selectedAttr ? "disabled" : "";
        const rawLabel = `${vehicleName(vehicle) || `ID ${vehicle.id}`}${unavailable ? " · удалён" : ""}`;
        return `<option value="${esc(vehicle.id)}" ${selectedAttr} ${disabledAttr}>${esc(rawLabel)}</option>`;
    }).join("");
}

function catalogModels(make) {
    const models = state.data?.car_catalog?.models || {};
    if (models[make]) return models[make];
    const normalized = String(make || "").toLocaleLowerCase("ru-RU");
    const found = Object.keys(models).find(key => key.toLocaleLowerCase("ru-RU") === normalized);
    return found ? models[found] : [];
}

function datalistOptions(values, selected = "") {
    const unique = [];
    [...(values || []), selected].forEach(value => {
        const normalized = String(value || "").trim();
        if (normalized && !unique.includes(normalized)) unique.push(normalized);
    });
    return unique.map(value => `<option value="${esc(value)}"></option>`).join("");
}

function inventoryLookupList() {
    return state.data?.lookups?.inventory || state.data?.inventory || [];
}

function inventoryOptionLabel(part, { fallbackName = "", archived = false } = {}) {
    const name = part?.name || part?.inventory_name || fallbackName || `ID ${part?.id || part?.inventory_id || ""}`.trim();
    const unit = part?.unit || "шт";
    const hasQuantity = part?.quantity !== undefined && part?.quantity !== null && part?.quantity !== "";
    const hasPrice = part?.price !== undefined && part?.price !== null && part?.price !== "";
    const suffix = archived || part?.deleted_at || part?.inventory_deleted_at ? " · архивная/удалена" : "";
    const meta = hasQuantity || hasPrice
        ? ` · ${hasQuantity ? `${qty(part.quantity)} ${unit}` : "остаток неизвестен"}${hasPrice ? ` · ${money(part.price)}` : ""}`
        : " · нет в активном справочнике";
    return `${name}${meta}${suffix}`;
}

function currentOrderInventoryOption(item = {}, inventory = inventoryLookupList()) {
    const selected = Number(item.inventory_id || 0);
    if (!selected || findById(inventory, selected)) return null;
    return {
        id: selected,
        name: item.inventory_name || item.title || `ID ${selected}`,
        inventory_name: item.inventory_name,
        inventory_deleted_at: item.inventory_deleted_at || "missing",
        unit: item.unit || "шт"
    };
}

function partAvailability(partId, item = {}) {
    const part = findById(inventoryLookupList(), Number(partId));
    if (part) return `${qty(part.quantity)} ${esc(part.unit)}`;
    if (Number(item.inventory_id || 0) === Number(partId)) return "архивная позиция, остаток неизвестен";
    return "неизвестно";
}

function partSourceOptions(item = {}) {
    const inventory = inventoryLookupList();
    const selected = Number(item.inventory_id || 0);
    const outsideSelected = item.kind === "part" && !selected;
    const extraOption = currentOrderInventoryOption(item, inventory);
    const allInventory = extraOption ? [...inventory, extraOption] : inventory;
    return `<option value="" ${outsideSelected ? "selected" : ""}>Вне склада / заказная</option>` + allInventory.map(part => {
        const selectedAttr = selected === Number(part.id) ? "selected" : "";
        const archived = Boolean(part.inventory_deleted_at || part.deleted_at || (extraOption && Number(part.id) === Number(extraOption.id)));
        const disabledAttr = archived && !selectedAttr ? "disabled" : "";
        return `<option value="${esc(part.id)}" ${selectedAttr} ${disabledAttr}>${esc(inventoryOptionLabel(part, { fallbackName: item.title, archived }))}</option>`;
    }).join("");
}

function partSourceHint(item = {}) {
    if (item.kind !== "part") return "";
    if (item.inventory_id) return `<div class="source-note">Складская: спишется при закрытии. Доступно: ${partAvailability(item.inventory_id, item)}</div>`;
    return `<div class="source-note">Вне склада: не влияет на остатки, но попадает в сумму, печать и отчеты.</div>`;
}

function channelOptions(selected = "phone") {
    const channels = state.data?.preferred_channels || channelLabels;
    return Object.entries(channels)
        .map(([key, label]) => `<option value="${esc(key)}" ${(selected || "phone") === key ? "selected" : ""}>${esc(label)}</option>`)
        .join("");
}

function appointmentStatusOptions(selected = "scheduled") {
    const statuses = state.data?.appointment_statuses || appointmentStatusFallback;
    return Object.entries(statuses)
        .map(([key, label]) => `<option value="${esc(key)}" ${(selected || "scheduled") === key ? "selected" : ""}>${esc(label)}</option>`)
        .join("");
}



function itemApprovalOptions(selected = "approved") {
    const statuses = state.data?.item_approval_statuses || itemApprovalFallback;
    return Object.entries(statuses)
        .map(([key, label]) => `<option value="${esc(key)}" ${(selected || "approved") === key ? "selected" : ""}>${esc(label)}</option>`)
        .join("");
}

function orderStatusOptions(order = {}) {
    const statuses = state.data?.statuses || {};
    const current = order.status || "new";
    const allowed = new Set([current, ...(orderStatusTransitions[current] || [])]);
    return Object.entries(statuses)
        .filter(([key]) => !order.id || allowed.has(key))
        .map(([key, label]) => `<option value="${esc(key)}" ${current === key ? "selected" : ""}>${esc(label)}</option>`)
        .join("");
}

function isHistoricalOrder(order = {}) {
    return Boolean(order.id && (order.status === "cancelled" || order.closed_at));
}

function isClosedFinancialOrder(order = {}) {
    return Boolean(order.id && (order.status === "closed" || order.closed_at));
}

function appointmentConflictWarning(appointment = {}) {
    const activeStatuses = new Set(["scheduled", "confirmed", "arrived"]);
    const status = appointment.status || "scheduled";
    if (!activeStatuses.has(status)) return null;
    const scheduledAt = String(appointment.scheduled_at || "").trim();
    const start = new Date(scheduledAt.replace(" ", "T"));
    if (!scheduledAt || Number.isNaN(start.getTime())) return null;
    const duration = Math.max(15, num(appointment.duration_minutes, 60));
    const end = new Date(start.getTime() + duration * 60 * 1000);
    const conflict = (state.data?.lookups?.appointments || state.data?.appointments || []).find(existing => {
        if (Number(existing.id || 0) === Number(appointment.id || 0)) return false;
        if (!activeStatuses.has(existing.status || "scheduled")) return false;
        const existingStart = new Date(String(existing.scheduled_at || "").replace(" ", "T"));
        if (Number.isNaN(existingStart.getTime())) return false;
        const existingEnd = new Date(existingStart.getTime() + Math.max(15, num(existing.duration_minutes, 60)) * 60 * 1000);
        return existingStart < end && existingEnd > start;
    });
    if (!conflict) return null;
    return `В это время уже есть запись: ${conflict.customer_name || "клиент"} · ${dateShort(conflict.scheduled_at)}.`;
}

function updateAppointmentConflictNotice(showToast = false) {
    const form = $("#entityForm");
    const notice = $("#appointmentConflictNotice");
    if (!form || !notice) return true;
    const data = collectForm(form);
    data.id = form.dataset.recordId || data.id;
    const message = appointmentConflictWarning(data);
    notice.hidden = !message;
    notice.textContent = message || "";
    if (message && showToast) toast(message, "error");
    return !message;
}


function openAppointmentModal(appointment = {}) {
    if (!ensureBootstrapReady("создание записи")) return;
    const lookupCustomers = state.data?.lookups?.customers || state.data?.customers || [];
    if (!lookupCustomers.length) {
        openModal(
            "Новая запись",
            `<div class="notice">В базе нет клиентов для записи.</div>`,
            `<button class="btn" type="button" data-save="cancel">Закрыть</button>`,
            "small"
        );
        return;
    }
    const selectedCustomer = appointment.customer_id || "";
    openModal(
        appointment.id ? "Запись клиента" : "Новая запись",
        `<form id="entityForm" class="stack" data-record-id="${safeRecordId(appointment.id)}">
            <fieldset class="form-fieldset"><legend>Клиент и авто</legend>
                <div class="form-grid">
                    ${selectField("appointment", "customer_id", "Клиент", customerOptions(selectedCustomer), "required", "span-2")}
                    ${selectField("appointment", "vehicle_id", "Автомобиль", vehicleOptions(selectedCustomer, appointment.vehicle_id), "", "span-2")}
                </div>
            </fieldset>
            <fieldset class="form-fieldset"><legend>Время и статус</legend>
                <div class="form-grid">
                    ${inputField("appointment", "scheduled_at", "Дата и время", `type="datetime-local" value="${inputDateValue(appointment.scheduled_at)}" required`)}
                    ${inputField("appointment", "duration_minutes", "Длительность, мин", `type="number" min="15" max="480" value="${esc(appointment.duration_minutes || 60)}"`)}
                    ${selectField("appointment", "status", "Статус", appointmentStatusOptions(appointment.status))}
                    ${inputField("appointment", "advisor", "Мастер-приемщик", `value="${esc(appointment.advisor || "Администратор")}"`)}
                </div>
                <div class="notice warning" id="appointmentConflictNotice" role="alert" hidden></div>
            </fieldset>
            <fieldset class="form-fieldset"><legend>Подробности</legend>
                <div class="form-grid">
                    ${inputField("appointment", "reason", "Причина визита", `value="${esc(appointment.reason)}" placeholder="ТО, диагностика, замена шин"`, "span-2", "Коротко сформулируйте цель визита — текст увидит администратор в календаре.")}
                    ${textareaField("appointment", "notes", "Заметки", appointment.notes, `placeholder="Что уточнить при приемке"`, "span-2", "Внутренние детали: ожидания клиента, симптомы, важные договоренности.")}
                </div>
            </fieldset>
        </form>`,
        `${appointment.id ? `<button class="btn danger" type="button" data-save="delete-appointment" data-id="${safeRecordId(appointment.id)}">Удалить</button>` : ""}
         <button class="btn" type="button" data-save="cancel">Отмена</button>
         <button class="btn primary" type="button" data-save="appointment" data-id="${safeRecordId(appointment.id)}">Сохранить</button>`,
        "small"
    );
    $("#appointment_customer_id").addEventListener("change", event => {
        const vehicle = $("#appointment_vehicle_id");
        vehicle.innerHTML = vehicleOptions(event.target.value, "");
        vehicle.value = "";
        vehicle.dispatchEvent(new Event("change", { bubbles: true }));
    });
    ["scheduled_at", "duration_minutes", "status"].forEach(name => {
        const input = $(`#entityForm [name="${name}"]`);
        if (input) {
            input.addEventListener("input", () => updateAppointmentConflictNotice(false));
            input.addEventListener("change", () => updateAppointmentConflictNotice(false));
        }
    });
    updateAppointmentConflictNotice(false);
}


function openCustomerModal(customer = {}) {
    if (!ensureBootstrapReady("создание клиента")) return;
    openModal(
        customer.id ? "Клиент" : "Новый клиент",
        `<form id="entityForm" class="stack">
            <fieldset class="form-fieldset"><legend>Контактные данные</legend>
                <div class="form-grid">
                    ${inputField("customer", "name", "Имя", `value="${esc(customer.name)}" required`, "span-2", "ФИО клиента или название организации — будет видно в заказах, записях и отчётах.")}
                    ${inputField("customer", "phone", "Телефон", `type="tel" value="${esc(customer.phone)}" inputmode="tel" autocomplete="tel" placeholder="+7 900 000-00-00"`, "", "Основной номер для подтверждений, напоминаний и быстрых звонков.")}
                    ${inputField("customer", "email", "Email", `type="email" value="${esc(customer.email)}" inputmode="email" autocomplete="email"`, "", "Необязательно: удобно для счетов, актов и рассылок.")}
                </div>
            </fieldset>
            <fieldset class="form-fieldset"><legend>Коммуникации</legend>
                <div class="form-grid">
                    ${inputField("customer", "source", "Источник", `value="${esc(customer.source)}" placeholder="Рекомендация, сайт, 2ГИС"`, "", "Помогает оценивать эффективность каналов привлечения.")}
                    ${selectField("customer", "preferred_channel", "Канал связи", channelOptions(customer.preferred_channel), "", "", "Выберите канал, через который клиенту удобнее получать сообщения.")}
                    <label class="check-field span-2" for="customer_reminder_consent"><input id="customer_reminder_consent" type="checkbox" name="reminder_consent" value="1" ${Number(customer.reminder_consent ?? 1) ? "checked" : ""}> <span><strong>Сервисные напоминания</strong><small>Разрешить плановые follow-up и уведомления о ТО.</small></span></label>
                </div>
            </fieldset>
            <fieldset class="form-fieldset"><legend>Заметки</legend>
                <div class="form-grid">
                    ${textareaField("customer", "notes", "Заметки", customer.notes, `placeholder="Особенности общения, скидки, предпочтения"`, "span-2", "Внутренняя информация для администраторов и мастеров.")}
                </div>
            </fieldset>
        </form>`,
        `${customer.id ? `<button class="btn danger" type="button" data-save="delete-customer" data-id="${safeRecordId(customer.id)}">Удалить</button>` : ""}
         <button class="btn" type="button" data-save="cancel">Отмена</button>
         <button class="btn primary" type="button" data-save="customer" data-id="${safeRecordId(customer.id)}">Сохранить</button>`,
        "small"
    );
}

function openVehicleModal(vehicle = {}) {
    if (!ensureBootstrapReady("создание автомобиля")) return;
    const makes = state.data?.car_catalog?.makes || [];
    const customers = state.data?.lookups?.customers || state.data?.customers || [];
    const hasCustomers = customers.length > 0;
    const selectedCustomer = vehicle.customer_id || "";
    openModal(
        vehicle.id ? "Автомобиль" : "Новый автомобиль",
        `<form id="entityForm" class="stack">
            ${hasCustomers ? "" : `<div class="notice">В базе нет клиентов для привязки автомобиля.</div>`}
            <fieldset class="form-fieldset"><legend>Владелец и модель</legend>
                <div class="form-grid">
                    ${selectField("vehicle", "customer_id", "Клиент", customerOptions(selectedCustomer), "required", "span-2", "Автомобиль будет связан с выбранным клиентом и доступен в заказ-нарядах.")}
                    ${labeledField("vehicleMake", "Марка", `<input name="make" id="vehicleMake" list="vehicleMakeList" value="${esc(vehicle.make)}" placeholder="Toyota"><datalist id="vehicleMakeList">${datalistOptions(makes, vehicle.make)}</datalist>`, "", "Начните вводить марку — CRM подскажет значения из офлайн-каталога.")}
                    ${labeledField("vehicleModel", "Модель", `<input name="model" id="vehicleModel" list="vehicleModelList" value="${esc(vehicle.model)}" placeholder="Camry"><datalist id="vehicleModelList">${datalistOptions(catalogModels(vehicle.make), vehicle.model)}</datalist>`, "", "Список моделей обновляется после выбора марки.")}
                    ${inputField("vehicle", "year", "Год", `type="number" min="1900" max="${new Date().getFullYear() + 1}" value="${esc(vehicle.year || "")}"`, "", "Используется в карточках, поиске и печатной форме.")}
                </div>
            </fieldset>
            <fieldset class="form-fieldset"><legend>Идентификация</legend>
                <div class="form-grid">
                    ${inputField("vehicle", "plate", "Госномер", `value="${esc(vehicle.plate)}" autocomplete="off" maxlength="40" autocapitalize="characters" spellcheck="false" placeholder="A123AA"`, "", "Будет автоматически приведён к верхнему регистру.")}
                    ${inputField("vehicle", "vin", "VIN", `value="${esc(vehicle.vin)}" maxlength="17" minlength="17" pattern="[A-HJ-NPR-Za-hj-npr-z0-9]{17}" title="VIN должен содержать 17 символов без I, O и Q" autocomplete="off" autocapitalize="characters" spellcheck="false" placeholder="17 символов"`, "", "17 символов без I, O и Q; удобно для идентификации авто.")}
                </div>
            </fieldset>
            <fieldset class="form-fieldset"><legend>Пробег и сервис</legend>
                <div class="form-grid">
                    ${inputField("vehicle", "mileage", "Пробег, км", `type="number" inputmode="numeric" step="1" min="0" value="${esc(vehicle.mileage || "")}"`, "", "Актуальный пробег синхронизируется с заказ-нарядами.")}
                    ${inputField("vehicle", "next_service_at", "Следующий сервис", `type="date" value="${esc(String(vehicle.next_service_at || "").slice(0, 10))}"`, "", "Дата появится в плане смены как сервисное напоминание.")}
                    ${inputField("vehicle", "next_service_mileage", "Сервисный пробег", `type="number" inputmode="numeric" step="1" min="0" value="${esc(vehicle.next_service_mileage || "")}"`, "", "Порог пробега для следующего ТО.")}
                </div>
            </fieldset>
            <fieldset class="form-fieldset"><legend>Заметки</legend>
                <div class="form-grid">
                    ${textareaField("vehicle", "notes", "Заметки", vehicle.notes, `placeholder="Особенности авто, история, рекомендации"`, "span-2", "Внутренние заметки по автомобилю.")}
                </div>
            </fieldset>
        </form>`,
        `${vehicle.id ? `<button class="btn danger" type="button" data-save="delete-vehicle" data-id="${safeRecordId(vehicle.id)}">Удалить</button>` : ""}
         <button class="btn" type="button" data-save="cancel">Отмена</button>
         <button class="btn primary" type="button" data-save="vehicle" data-id="${safeRecordId(vehicle.id)}" ${hasCustomers ? "" : "disabled"}>Сохранить</button>`,
        "small"
    );
    bindVehicleCatalog();
}

function bindVehicleCatalog() {
    const makeInput = $("#vehicleMake");
    const modelInput = $("#vehicleModel");
    const modelList = $("#vehicleModelList");
    if (!makeInput || !modelInput || !modelList) return;
    const refreshModels = () => {
        modelList.innerHTML = datalistOptions(catalogModels(makeInput.value), modelInput.value);
    };
    makeInput.addEventListener("input", refreshModels);
    const uppercaseInput = event => { event.target.value = String(event.target.value || "").toUpperCase(); };
    $("#vehicle_vin")?.addEventListener("input", uppercaseInput);
    $("#vehicle_plate")?.addEventListener("input", uppercaseInput);
    refreshModels();
}

function openInventoryModal(part = {}) {
    if (!ensureBootstrapReady("создание складской позиции")) return;
    openModal(
        part.id ? "Складская позиция" : "Новая складская позиция",
        `<form id="entityForm" class="stack">
            <fieldset class="form-fieldset"><legend>Идентификация</legend>
                <div class="form-grid">
                    ${inputField("inventory", "name", "Название", `value="${esc(part.name)}" required`, "span-2")}
                    ${inputField("inventory", "sku", "Артикул", `value="${esc(part.sku)}"`)}
                    ${inputField("inventory", "brand", "Бренд", `value="${esc(part.brand)}"`)}
                    ${inputField("inventory", "unit", "Ед.", `value="${esc(part.unit || "шт")}"`)}
                </div>
            </fieldset>
            <fieldset class="form-fieldset"><legend>Остатки</legend>
                <div class="form-grid">
                    ${inputField("inventory", "quantity", "Остаток", `type="number" inputmode="decimal" step="0.01" min="0" value="${esc(part.quantity || 0)}"`)}
                    ${inputField("inventory", "min_quantity", "Минимум", `type="number" inputmode="decimal" step="0.01" min="0" value="${esc(part.min_quantity || 0)}"`)}
                </div>
            </fieldset>
            <fieldset class="form-fieldset"><legend>Цены</legend>
                <div class="form-grid">
                    ${inputField("inventory", "price", "Цена продажи", `type="number" inputmode="decimal" step="0.01" min="0" value="${esc(part.price || 0)}"`)}
                    ${inputField("inventory", "cost", "Себестоимость", `type="number" inputmode="decimal" step="0.01" min="0" value="${esc(part.cost || 0)}"`)}
                </div>
            </fieldset>
            <fieldset class="form-fieldset"><legend>Поставка и заметки</legend>
                <div class="form-grid">
                    ${inputField("inventory", "supplier", "Поставщик", `value="${esc(part.supplier)}"`, "span-2")}
                    ${textareaField("inventory", "notes", "Заметки", part.notes, "", "span-2")}
                </div>
            </fieldset>
        </form>`,
        `${part.id ? `<button class="btn danger" type="button" data-save="delete-inventory" data-id="${safeRecordId(part.id)}">Удалить</button>` : ""}
         <button class="btn" type="button" data-save="cancel">Отмена</button>
         <button class="btn primary" type="button" data-save="inventory" data-id="${safeRecordId(part.id)}">Сохранить</button>`,
        "small"
    );
}

function openOrderModal(order = {}) {
    if (!ensureBootstrapReady("создание заказ-наряда")) return;
    if (!order) {
        toast("Заказ не найден в текущей выборке. Очистите поиск или обновите данные.", "error");
        return;
    }
    const historicalOrder = isHistoricalOrder(order);
    const closedFinancialOrder = isClosedFinancialOrder(order);
    state.orderDraftReadOnly = historicalOrder;
    state.orderDraftItems = (order.items || [{ kind: "service", title: "", approval_status: "approved", quantity: 1, unit_price: 0, unit_cost: 0 }])
        .map(item => ({ approval_status: "approved", inventory_id: "", ...item }));
    const lookupCustomers = state.data?.lookups?.customers || state.data?.customers || [];
    if (!lookupCustomers.length) {
        openModal(
            "Новый заказ-наряд",
            `<div class="notice">В базе нет клиентов для оформления заказ-наряда.</div>`,
            `<button class="btn" type="button" data-save="cancel">Закрыть</button>`,
            "small"
        );
        return;
    }
    const selectedCustomer = order.customer_id || "";
    const orderVehicleOption = order.vehicle_id ? {
        id: order.vehicle_id,
        customer_id: selectedCustomer,
        make: order.vehicle_make,
        model: order.vehicle_model,
        year: order.vehicle_year,
        plate: order.vehicle_plate,
        deleted_at: order.vehicle_deleted
    } : null;
    const currentVehicleOptions = () => {
        const vehicle = orderVehicleOption;
        if (!vehicle?.id) return vehicleOptions(selectedCustomer, order.vehicle_id);
        if (vehicle.deleted_at || vehicle.deleted_at === 1 || vehicle.vehicle_deleted) {
            return vehicleOptions(selectedCustomer, order.vehicle_id, [vehicle]);
        }
        return vehicleOptions(selectedCustomer, order.vehicle_id, [vehicle]);
    };
    openModal(
        order.id ? `Заказ-наряд ${order.number}` : "Новый заказ-наряд",
        `<form id="orderForm" class="stack">
            ${closedFinancialOrder ? `<div class="notice warning"><strong>Финансовая история закрыта.</strong><p>Поля и позиции доступны только для просмотра. Закрытый заказ можно оставить закрытым или отменить без изменения суммы, списаний и позиций.</p></div>` : ""}
            ${order.status === "cancelled" && !closedFinancialOrder ? `<div class="notice warning"><strong>Заказ отменен.</strong><p>Отмененный заказ нельзя повторно открыть или изменить — создайте новый заказ-наряд.</p></div>` : ""}
            <fieldset class="form-fieldset"><legend>Клиент и авто</legend>
                <div class="form-grid three">
                    ${selectField("order", "customer_id", "Клиент", customerOptions(selectedCustomer), `required ${historicalOrder ? "disabled" : ""}`)}
                    ${selectField("order", "vehicle_id", "Автомобиль", currentVehicleOptions(), historicalOrder ? "disabled" : "")}
                    ${selectField("order", "status", "Статус", orderStatusOptions(order), order.status === "cancelled" ? "disabled" : "")}
                    ${selectField("order", "priority", "Приоритет", Object.entries(state.data.priorities || priorityLabels).map(([key, label]) => `<option value="${esc(key)}" ${(order.priority || "normal") === key ? "selected" : ""}>${esc(label)}</option>`).join(""), historicalOrder ? "disabled" : "")}
                    ${historicalOrder ? `${hiddenInput("customer_id", selectedCustomer)}${hiddenInput("vehicle_id", order.vehicle_id || "")}${hiddenInput("priority", order.priority || "normal")}` : ""}
                    ${order.status === "cancelled" ? hiddenInput("status", order.status) : ""}
                </div>
            </fieldset>
            <fieldset class="form-fieldset"><legend>Приём и сроки</legend>
                <div class="form-grid three">
                    ${historicalOrder ? readonlyField("Мастер-приемщик", readonlyValue(order.advisor || "Администратор")) : inputField("order", "advisor", "Мастер-приемщик", `value="${esc(order.advisor || "Администратор")}"`)}
                    ${historicalOrder ? readonlyField("Механик", readonlyValue(order.mechanic)) : inputField("order", "mechanic", "Механик", `value="${esc(order.mechanic)}"`)}
                    ${historicalOrder ? readonlyField("Срок", readonlyValue(inputDateValue(order.promised_at))) : inputField("order", "promised_at", "Срок", `type="datetime-local" value="${inputDateValue(order.promised_at)}"`)}
                    ${historicalOrder ? readonlyField("Пробег", readonlyValue(order.odometer || "")) : inputField("order", "odometer", "Пробег", `type="number" inputmode="numeric" step="1" min="0" value="${esc(order.odometer || "")}"`)}
                    ${historicalOrder ? `${hiddenInput("advisor", order.advisor || "Администратор")}${hiddenInput("mechanic", order.mechanic || "")}${hiddenInput("promised_at", inputDateValue(order.promised_at))}${hiddenInput("odometer", order.odometer || "")}` : ""}
                </div>
            </fieldset>
            <fieldset class="form-fieldset"><legend>Финансы</legend>
                <div class="form-grid three">
                    ${historicalOrder ? readonlyField("Оплачено", readonlyValue(money(order.paid || 0))) : inputField("order", "paid", "Оплачено", `type="number" inputmode="decimal" step="0.01" min="0" value="${esc(order.paid || 0)}"`)}
                    ${historicalOrder ? readonlyField("Скидка", readonlyValue(money(order.discount || 0))) : inputField("order", "discount", "Скидка", `type="number" inputmode="decimal" step="0.01" min="0" value="${esc(order.discount || 0)}"`)}
                    ${historicalOrder ? readonlyField("Налог, %", readonlyValue(order.tax_rate || 0)) : inputField("order", "tax_rate", "Налог, %", `type="number" inputmode="decimal" step="0.01" min="0" max="100" value="${esc(order.tax_rate || 0)}"`)}
                    ${historicalOrder ? readonlyField("Оплата", readonlyValue(order.payment_method)) : inputField("order", "payment_method", "Оплата", `value="${esc(order.payment_method)}"`)}
                    ${historicalOrder ? `${hiddenInput("paid", order.paid || 0)}${hiddenInput("discount", order.discount || 0)}${hiddenInput("tax_rate", order.tax_rate || 0)}${hiddenInput("payment_method", order.payment_method || "")}` : ""}
                </div>
            </fieldset>
            <fieldset class="form-fieldset"><legend>Согласование и контакт</legend>
                <div class="form-grid three">
                    ${historicalOrder ? readonlyField("Согласовал", readonlyValue(order.authorized_by)) : inputField("order", "authorized_by", "Согласовал", `value="${esc(order.authorized_by)}"`)}
                    ${historicalOrder ? readonlyField("Дата согласования", readonlyValue(inputDateValue(order.authorized_at))) : inputField("order", "authorized_at", "Дата согласования", `type="datetime-local" value="${inputDateValue(order.authorized_at)}"`)}
                    ${historicalOrder ? readonlyField("Follow-up", readonlyValue(inputDateValue(order.follow_up_at))) : inputField("order", "follow_up_at", "Follow-up", `type="datetime-local" value="${inputDateValue(order.follow_up_at)}"`)}
                    ${historicalOrder ? `${hiddenInput("authorized_by", order.authorized_by || "")}${hiddenInput("authorized_at", inputDateValue(order.authorized_at))}` : ""}
                    ${historicalOrder ? hiddenInput("follow_up_at", inputDateValue(order.follow_up_at)) : ""}
                </div>
            </fieldset>
            <fieldset class="form-fieldset"><legend>Обращение и рекомендации</legend>
                <div class="form-grid three">
                    ${historicalOrder ? readonlyField("Жалоба клиента", readonlyTextareaValue(order.complaint), "span-3") : textareaField("order", "complaint", "Жалоба клиента", order.complaint, "", "span-3")}
                    ${historicalOrder ? readonlyField("Диагностика", readonlyTextareaValue(order.diagnosis), "span-3") : textareaField("order", "diagnosis", "Диагностика", order.diagnosis, "", "span-3")}
                    ${historicalOrder ? readonlyField("Рекомендации", readonlyTextareaValue(order.recommendations), "span-3") : textareaField("order", "recommendations", "Рекомендации", order.recommendations, "", "span-3")}
                    ${historicalOrder ? `${hiddenInput("complaint", order.complaint || "")}${hiddenInput("diagnosis", order.diagnosis || "")}${hiddenInput("recommendations", order.recommendations || "")}` : ""}
                </div>
            </fieldset>
            <div class="toolbar">
                <div class="toolbar-left"><strong>Работы и запчасти</strong></div>
                <div class="toolbar-right">
                    <button class="btn" type="button" id="addService" ${historicalOrder ? "disabled" : ""}>+ Работа</button>
                    <button class="btn" type="button" id="addPart" ${historicalOrder ? "disabled" : ""}>+ Запчасть</button>
                </div>
            </div>
            <div class="business-hints" aria-label="Подсказки заказ-наряда">
                <strong>Подсказки:</strong>
                <span class="hint-chip" data-tone="ok"><span class="hint-dot ok" aria-hidden="true"></span>Согласовано — входит в сумму</span>
                <span class="hint-chip" data-tone="warn"><span class="hint-dot warning" aria-hidden="true"></span>Отложено/отказ — не списывает склад</span>
                <span class="hint-chip" data-tone="danger"><span class="hint-dot danger" aria-hidden="true"></span>К оплате пересчитывается сразу</span>
            </div>
            <div class="notice">Запчасть можно выбрать со склада или указать вручную как «вне склада» — такие позиции не списывают остатки, но учитываются в сумме заказ-наряда.</div>
            <div id="itemsHost"></div>
        </form>`,
        `${order.id && !closedFinancialOrder ? `<button class="btn danger" type="button" data-save="delete-order" data-id="${safeRecordId(order.id)}">Удалить</button>` : ""}
         ${order.id ? `<button class="btn ghost" type="button" data-save="print-order" data-id="${safeRecordId(order.id)}">Печать</button>` : ""}
         <button class="btn" type="button" data-save="cancel">Отмена</button>
         <button class="btn primary" type="button" data-save="order" data-id="${safeRecordId(order.id)}" ${order.status === "cancelled" ? "disabled" : ""}>Сохранить</button>`
    );
    renderOrderItems();
    $("#order_customer_id").addEventListener("change", event => {
        if (state.orderDraftReadOnly) return;
        const vehicle = $("#order_vehicle_id");
        vehicle.innerHTML = vehicleOptions(event.target.value, "");
        vehicle.value = "";
        vehicle.dispatchEvent(new Event("change", { bubbles: true }));
    });
    $("#addService").addEventListener("click", () => {
        if (state.orderDraftReadOnly) return;
        markModalDirty();
        state.orderDraftItems.push({ kind: "service", title: "", approval_status: "approved", quantity: 1, unit_price: 0, unit_cost: 0 });
        renderOrderItems();
    });
    $("#addPart").addEventListener("click", () => {
        if (state.orderDraftReadOnly) return;
        markModalDirty();
        state.orderDraftItems.push({ kind: "part", inventory_id: "", title: "", approval_status: "approved", quantity: 1, unit_price: 0, unit_cost: 0 });
        renderOrderItems();
    });
    ['discount', 'tax_rate', 'paid'].forEach(name => {
        const input = document.querySelector(`#orderForm [name="${name}"]`);
        if (input) input.addEventListener("input", () => {
            const totals = $("#orderTotals");
            if (totals) totals.outerHTML = orderTotalsHtml();
        });
    });
}

function renderOrderItems() {
    const host = $("#itemsHost");
    host.innerHTML = `<div class="items-table">
        <table aria-label="Позиции заказ-наряда">
            <thead>${tableHead(["Тип", "Источник запчасти", "Наименование", "Согласование", "Кол-во", "Цена", "Себест.", {text: "Сумма", className: "money"}, ""])}</thead>
            <tbody>
                ${state.orderDraftItems.map((item, index) => `
                    <tr data-index="${index}">
                        <td data-label="Тип"><select data-item="kind" aria-label="Тип позиции" ${state.orderDraftReadOnly ? "disabled" : ""}>
                            <option value="service" ${item.kind === "service" ? "selected" : ""}>Работа</option>
                            <option value="part" ${item.kind === "part" ? "selected" : ""}>Запчасть</option>
                        </select></td>
                        <td data-label="Источник"><select class="source-select" data-item="inventory_id" aria-label="Источник запчасти" ${item.kind !== "part" || state.orderDraftReadOnly ? "disabled" : ""}>${partSourceOptions(item)}</select>${partSourceHint(item)}</td>
                        <td data-label="Наименование"><input data-item="title" aria-label="Наименование позиции" value="${esc(item.title)}" required ${state.orderDraftReadOnly ? "disabled" : ""}></td>
                        <td data-label="Согласование"><select data-item="approval_status" aria-label="Статус согласования позиции" ${state.orderDraftReadOnly ? "disabled" : ""}>${itemApprovalOptions(item.approval_status)}</select><div class="cell-note">Согласовано — в сумму; отложено/отказ — без списания и оплаты.</div></td>
                        <td data-label="Кол-во"><input data-item="quantity" aria-label="Количество" type="number" inputmode="decimal" step="0.01" min="0.01" required value="${esc(item.quantity || 1)}" ${state.orderDraftReadOnly ? "disabled" : ""}></td>
                        <td data-label="Цена"><input data-item="unit_price" aria-label="Цена" type="number" inputmode="decimal" step="0.01" min="0" value="${esc(item.unit_price || 0)}" ${state.orderDraftReadOnly ? "disabled" : ""}></td>
                        <td data-label="Себест."><input data-item="unit_cost" aria-label="Себестоимость" type="number" inputmode="decimal" step="0.01" min="0" value="${esc(item.unit_cost || 0)}" ${state.orderDraftReadOnly ? "disabled" : ""}></td>
                        <td data-label="Сумма" class="money" data-row-total>${money((item.approval_status || "approved") === "approved" ? num(item.quantity) * num(item.unit_price) : 0)}</td>
                        <td data-label="Действия"><button class="btn icon" type="button" data-remove-item="${index}" title="Удалить" aria-label="Удалить позицию заказ-наряда" ${state.orderDraftReadOnly ? "disabled" : ""}>×</button></td>
                    </tr>`).join("")}
            </tbody>
        </table>
    </div>${orderTotalsHtml()}`;
    $$("[data-item]", host).forEach(input => {
        input.addEventListener("change", syncOrderItemsFromDom);
        input.addEventListener("input", syncOrderItemStateOnly);
    });
    $$("[data-remove-item]", host).forEach(button => {
        button.addEventListener("click", event => {
            markModalDirty();
            state.orderDraftItems.splice(Number(event.currentTarget.dataset.removeItem), 1);
            if (!state.orderDraftItems.length) state.orderDraftItems.push({ kind: "service", title: "", approval_status: "approved", quantity: 1, unit_price: 0, unit_cost: 0 });
            renderOrderItems();
        });
    });
    updateScrollHints(host);
}

function syncOrderItemsFromDom(event) {
    if (state.orderDraftReadOnly) return;
    const row = event.target.closest("tr[data-index]");
    if (!row) return;
    const index = Number(row.dataset.index);
    const item = state.orderDraftItems[index];
    $$("[data-item]", row).forEach(input => {
        item[input.dataset.item] = input.value;
    });
    clearFormError(event.target);
    const pairedInvalidField = event.target.dataset.item === "title" ? row.querySelector('[data-item="quantity"]') : row.querySelector('[data-item="title"]');
    if (pairedInvalidField) clearFormError(pairedInvalidField);
    if (event.target.dataset.item === "kind") {
        if (item.kind === "service") item.inventory_id = "";
        if (item.kind === "part") item.inventory_id = item.inventory_id || "";
    }
    if (event.target.dataset.item === "inventory_id") {
        if (item.inventory_id) {
            const inventory = state.data.lookups?.inventory || state.data.inventory;
            const part = findById(inventory, Number(item.inventory_id));
            if (part) {
                item.title = part.name;
                item.unit_price = part.price;
                item.unit_cost = part.cost;
            }
        } else if (item.kind === "part") {
            item.title = item.title || "";
            item.unit_price = num(item.unit_price, 0);
            item.unit_cost = num(item.unit_cost, 0);
        }
    }
    if (["kind", "inventory_id"].includes(event.target.dataset.item)) {
        renderOrderItems();
    } else {
        syncOrderItemStateOnly(event);
    }
}

function orderTotalsHtml() {
    const approved = state.orderDraftItems.filter(i => (i.approval_status || "approved") === "approved");
    const service = approved.filter(i => i.kind === "service").reduce((sum, i) => sum + num(i.quantity) * num(i.unit_price), 0);
    const parts = approved.filter(i => i.kind === "part").reduce((sum, i) => sum + num(i.quantity) * num(i.unit_price), 0);
    const deferred = state.orderDraftItems.filter(i => (i.approval_status || "approved") !== "approved")
        .reduce((sum, i) => sum + num(i.quantity) * num(i.unit_price), 0);
    const subtotal = service + parts;
    const discountPreview = Math.min(num(document.querySelector('#orderForm [name="discount"]')?.value, 0), subtotal);
    const taxPreview = Math.max(0, subtotal - discountPreview) * Math.min(Math.max(num(document.querySelector('#orderForm [name="tax_rate"]')?.value, 0), 0), 100) / 100;
    const paidPreview = Math.min(num(document.querySelector('#orderForm [name="paid"]')?.value, 0), Math.max(0, subtotal - discountPreview) + taxPreview);
    const duePreview = Math.max(0, subtotal - discountPreview + taxPreview - paidPreview);
    return `<div class="totals" id="orderTotals">
        <div><span>Работы</span><strong>${money(service)}</strong></div>
        <div><span>Запчасти</span><strong>${money(parts)}</strong></div>
        <div><span>Отложено/отказ</span><strong>${money(deferred)}</strong></div>
        <div><span>Скидка</span><strong>${money(discountPreview)}</strong></div>
        <div><span>Налог</span><strong>${money(taxPreview)}</strong></div>
        <div><span>Оплачено</span><strong>${money(paidPreview)}</strong></div>
        <div class="grand"><span>К оплате</span><strong>${money(duePreview)}</strong></div>
    </div>`;
}

async function refreshAfterMutation(successMessage) {
    toast(successMessage);
    try {
        await loadData();
    } catch (error) {
        if (error?.name === "AbortError") return;
        const message = error?.message ? `Операция выполнена, но не удалось обновить данные. Нажмите «Обновить». Причина: ${error.message}` : "Операция выполнена, но не удалось обновить данные. Нажмите «Обновить».";
        const refreshError = new Error(message);
        refreshError.status = error?.status;
        showError(refreshError);
    }
}

async function saveEntity(kind, id) {
    const form = $("#entityForm");
    if (!form) return;
    if (!validateLocalizedNumberInputs(form)) return;
    if (!reportFormValidity(form)) return;
    if (kind === "appointments" && !updateAppointmentConflictNotice(true)) return;
    const data = collectForm(form);
    const path = id ? `/api/${kind}/${id}` : `/api/${kind}`;
    const method = id ? "PUT" : "POST";
    setSaveButtonsBusy(true);
    try {
        await api(path, { method, body: JSON.stringify(data) });
        closeModal(true);
        await refreshAfterMutation("Сохранено");
    } catch (error) {
        showError(error);
    } finally {
        setSaveButtonsBusy(false);
    }
}

async function saveOrder(id) {
    const form = $("#orderForm");
    if (!validateLocalizedNumberInputs(form, { excludeSelector: "[data-item]" })) return;
    if (!validateOrderItemNumberInputs()) return;
    if (form && !reportFormValidity(form, "[data-item]")) return;
    const data = collectForm(form);
    syncAllOrderItems();
    const invalidItems = state.orderDraftItems.filter(item => !String(item.title || "").trim() || num(item.quantity, 0) <= 0);
    if (invalidItems.length) {
        const missingTitle = invalidItems.some(item => !String(item.title || "").trim());
        const missingQty = invalidItems.some(item => num(item.quantity, 0) <= 0);
        const parts = [];
        if (missingTitle) parts.push("укажите наименование позиции");
        if (missingQty) parts.push("количество должно быть больше нуля");
        markFirstInvalidOrderItem(missingTitle ? "title" : "quantity", `Проверьте позиции заказ-наряда: ${parts.join("; ")} (строк с ошибкой: ${invalidItems.length}).`);
        return;
    }
    data.items = state.orderDraftItems.map(item => ({
        kind: item.kind,
        inventory_id: item.kind === "part" && num(item.inventory_id, 0) > 0 ? num(item.inventory_id, 0) : null,
        title: item.title,
        approval_status: item.approval_status || "approved",
        quantity: num(item.quantity, 0),
        unit_price: num(item.unit_price, 0),
        unit_cost: num(item.unit_cost, 0)
    }));
    const stockMessage = insufficientStockMessage(data.status);
    if (stockMessage) {
        markFirstInvalidOrderItem("quantity", stockMessage);
        return;
    }
    const path = id ? `/api/orders/${id}` : "/api/orders";
    const method = id ? "PUT" : "POST";
    setSaveButtonsBusy(true);
    try {
        await api(path, { method, body: JSON.stringify(data) });
        closeModal(true);
        await refreshAfterMutation("Заказ-наряд сохранен");
    } catch (error) {
        showError(error);
    } finally {
        setSaveButtonsBusy(false);
    }
}


function syncAllOrderItems() {
    if (state.orderDraftReadOnly) return;
    $$("#itemsHost tr[data-index]").forEach(row => {
        const index = Number(row.dataset.index);
        const item = state.orderDraftItems[index];
        $$("[data-item]", row).forEach(input => {
            item[input.dataset.item] = input.value;
        });
    });
}

function insufficientStockMessage(status) {
    if (status !== "closed") return "";
    const stock = new Map(inventoryLookupList().map(part => [Number(part.id), part]));
    const required = new Map();
    state.orderDraftItems.forEach(item => {
        if (item.kind !== "part" || (item.approval_status || "approved") !== "approved") return;
        const id = Number(item.inventory_id || 0);
        if (!id) return;
        required.set(id, (required.get(id) || 0) + num(item.quantity, 0));
    });
    const shortages = [];
    required.forEach((need, id) => {
        const part = stock.get(id);
        if (!part) return;
        const available = num(part.quantity, 0);
        if (available + 0.000001 < need) shortages.push(`${part.name}: доступно ${qty(available)}, требуется ${qty(need)}`);
    });
    return shortages.length ? `Недостаточно на складе для закрытия заказа: ${shortages.join("; ")}.` : "";
}

function validateOrderItemNumberInputs() {
    const form = $("#orderForm");
    if (!form) return true;
    for (const input of $$('#itemsHost input[type="number"][data-item]', form)) {
        const message = numericInputError(input, input.getAttribute("aria-label") || "Поле позиции");
        input.setCustomValidity(message);
        if (message) {
            markFirstInvalidOrderItem(input.dataset.item === "quantity" ? "quantity" : input.dataset.item, message);
            return false;
        }
    }
    return true;
}


function syncOrderItemStateOnly(event) {
    if (state.orderDraftReadOnly) return;
    const row = event.target.closest("tr[data-index]");
    if (!row) return;
    const index = Number(row.dataset.index);
    const item = state.orderDraftItems[index];
    $$("[data-item]", row).forEach(input => {
        item[input.dataset.item] = input.value;
    });
    clearFormError(event.target);
    const totalCell = $("[data-row-total]", row);
    if (totalCell) totalCell.textContent = money((item.approval_status || "approved") === "approved" ? num(item.quantity) * num(item.unit_price) : 0);
    const totals = $("#orderTotals");
    if (totals) totals.outerHTML = orderTotalsHtml();
}

function markFirstInvalidOrderItem(preferredField, message) {
    const form = $("#orderForm");
    const fieldSelector = preferredField === "quantity"
        ? '[data-item="quantity"]'
        : '[data-item="title"]';
    const rows = $$("#itemsHost tr[data-index]");
    let target = null;
    for (const row of rows) {
        const title = row.querySelector('[data-item="title"]');
        const quantity = row.querySelector('[data-item="quantity"]');
        const invalidTitle = !String(title?.value || "").trim();
        const invalidQuantity = num(quantity?.value, 0) <= 0;
        if (preferredField === "quantity" && invalidQuantity) target = quantity;
        else if (invalidTitle) target = title;
        else if (invalidQuantity) target = quantity;
        if (target) break;
    }
    if (!target) target = $(fieldSelector, form || document);
    if (!target) {
        applyFormError(new Error(message));
        return;
    }
    clearAllFormErrors(form);
    target.classList.add("invalid");
    target.setAttribute("aria-invalid", "true");
    const id = `${target.dataset.item || target.name || target.id || "field"}-error`;
    const previous = (target.getAttribute("aria-describedby") || "").split(/\s+/).filter(Boolean).filter(token => token !== id);
    target.dataset.errorDescribedby = id;
    target.setAttribute("aria-describedby", [...previous, id].join(" "));
    const errorNode = document.createElement("div");
    errorNode.className = "field-error";
    errorNode.id = id;
    errorNode.textContent = message;
    (target.closest("td") || target.parentElement)?.append(errorNode);
    target.focus({ preventScroll: false });
}

async function deleteEntity(kind, id) {
    if (state.saving) return;
    if (!confirm("Удалить запись? Это действие скроет запись из активной базы CRM.")) return;
    setSaveButtonsBusy(true);
    try {
        await api(`/api/${kind}/${id}`, { method: "DELETE" });
        closeModal(true);
        await refreshAfterMutation("Удалено");
    } catch (error) {
        showError(error);
    } finally {
        setSaveButtonsBusy(false);
    }
}

function showError(error) {
    if (error?.name === "AbortError") return;
    const status = Number(error?.status || 0);
    if (!status) setOnlineState(false);
    const message = error.message || String(error);
    state.lastError = message;
    applyFormError(error);
    const modalOpen = $("#modalBackdrop")?.classList.contains("open");
    if (!state.data) {
        if (!restoreCachedBootstrap()) {
            const content = $("#content");
            if (content) {
                content.innerHTML = `${offlineBannerHtml(true)}<div class="notice" role="alert"><strong>Не удалось загрузить данные.</strong><p>${esc(message)}</p><button class="btn primary" type="button" data-action="retry-load">Повторить</button></div>`;
                bindViewActions(content);
            }
        }
    } else if (!modalOpen) {
        render();
    }
    toast(message, "error");
}

document.addEventListener("click", event => {
    const navButton = event.target.closest("#nav button[data-route]");
    if (navButton) {
        setRoute(navButton.dataset.route);
        setMobileNavOpen(false, { restoreFocus: false });
    }

    const saveButton = event.target.closest("[data-save]");
    if (!saveButton) return;
    const action = saveButton.dataset.save;
    const id = Number(saveButton.dataset.id || 0);
    if (state.saving) return;
    if (action === "cancel") closeModal();
    else if (action === "appointment") saveEntity("appointments", id).catch(showError);
    else if (action === "customer") saveEntity("customers", id).catch(showError);
    else if (action === "vehicle") saveEntity("vehicles", id).catch(showError);
    else if (action === "inventory") saveEntity("inventory", id).catch(showError);
    else if (action === "order") saveOrder(id).catch(showError);
    else if (action === "delete-customer") deleteEntity("customers", id).catch(showError);
    else if (action === "delete-vehicle") deleteEntity("vehicles", id).catch(showError);
    else if (action === "delete-inventory") deleteEntity("inventory", id).catch(showError);
    else if (action === "delete-appointment") deleteEntity("appointments", id).catch(showError);
    else if (action === "delete-order") deleteEntity("orders", id).catch(showError);
    else if (action === "print-order") openPrintOrder(id).catch(showError);
});

const modalCloseButton = $("#modalClose");
modalCloseButton?.addEventListener("click", () => closeModal());
document.addEventListener("keydown", handleModalKeydown);
$("#modalBackdrop")?.addEventListener("click", event => {
    if (event.target.id === "modalBackdrop") closeModal();
});
$("#globalSearch")?.addEventListener("input", event => {
    state.q = event.target.value;
    state.customerPage = 1;
    updateSearchClear();
    clearTimeout(state.searchTimer);
    state.searchTimer = setTimeout(() => loadData().catch(showError), 260);
});
$("#globalSearch")?.addEventListener("keydown", event => {
    if (event.key === "Escape" && state.q) {
        event.preventDefault();
        clearGlobalSearch();
    }
});
$("#clearSearch")?.addEventListener("click", clearGlobalSearch);
window.addEventListener("offline", () => {
    setOnlineState(false);
    announce("Браузер сообщает, что сеть недоступна. Работаем с последними загруженными данными.", true);
});
window.addEventListener("online", () => {
    loadData().then(() => toast("Соединение восстановлено")).catch(showError);
});
$("#refreshBtn")?.addEventListener("click", () => loadData().then(() => toast("Обновлено")).catch(showError));
$("#backupBtn")?.addEventListener("click", createBackupFromUi);
$("#statusBackup")?.addEventListener("click", createBackupFromUi);
$("#commandBtn")?.addEventListener("click", openCommandPalette);
$("#commandClose")?.addEventListener("click", closeCommandPalette);
$("#commandPalette")?.addEventListener("click", event => {
    if (event.target.id === "commandPalette") closeCommandPalette();
    const commandButton = event.target.closest("[data-command-index]");
    if (commandButton) runCommand(Number(commandButton.dataset.commandIndex || 0));
});
$("#commandSearch")?.addEventListener("input", renderCommandPalette);
$("#commandSearch")?.addEventListener("keydown", event => {
    const buttons = $$("[data-command-index]", $("#commandList"));
    const activeIndex = Math.max(0, buttons.findIndex(button => button.classList.contains("active")));
    if (event.key === "Escape") {
        event.preventDefault();
        closeCommandPalette();
    } else if (event.key === "Enter") {
        event.preventDefault();
        runCommand(activeIndex);
    } else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        if (!buttons.length) return;
        const nextIndex = event.key === "ArrowDown"
            ? (activeIndex + 1) % buttons.length
            : (activeIndex - 1 + buttons.length) % buttons.length;
        buttons.forEach((button, index) => {
            const active = index === nextIndex;
            button.classList.toggle("active", active);
            button.setAttribute("aria-selected", active ? "true" : "false");
        });
        updateCommandSearchAria(buttons[nextIndex].id || "");
        buttons[nextIndex].scrollIntoView({ block: "nearest" });
    }
});
function systemMenuItems() {
    return $$("#systemMenu [role='menuitem']:not([disabled])");
}

function focusSystemMenuItem(index = 0) {
    const items = systemMenuItems();
    if (!items.length) return;
    items[((index % items.length) + items.length) % items.length].focus();
}

function setSystemMenuOpen(isOpen, { focusFirst = false, restoreFocus = false } = {}) {
    const menu = $("#systemMenu");
    const button = $("#systemMenuBtn");
    if (!menu || !button) return;
    if (isOpen) closeTransientPanels("system");
    menu.hidden = !isOpen;
    button.setAttribute("aria-expanded", isOpen ? "true" : "false");
    if (isOpen) updateTopbarOffset();
    if (isOpen && focusFirst) focusSystemMenuItem(0);
    if (!isOpen && restoreFocus) button.focus({ preventScroll: true });
}

function closeSystemMenu(options = {}) {
    setSystemMenuOpen(false, options);
}

$("#systemMenuBtn")?.addEventListener("click", event => {
    event.stopPropagation();
    const isOpen = $("#systemMenuBtn")?.getAttribute("aria-expanded") === "true";
    setSystemMenuOpen(!isOpen, { focusFirst: !isOpen });
});
$("#systemMenuBtn")?.addEventListener("keydown", event => {
    if (!["ArrowDown", "Enter", " "].includes(event.key)) return;
    event.preventDefault();
    setSystemMenuOpen(true, { focusFirst: true });
});
$("#systemMenu")?.addEventListener("click", event => {
    const routeButton = event.target.closest("[data-system-route]");
    if (routeButton) setRoute(routeButton.dataset.systemRoute);
    if (event.target.closest("button")) closeSystemMenu({ restoreFocus: true });
});
$("#systemMenu")?.addEventListener("keydown", event => {
    const items = systemMenuItems();
    const activeIndex = items.findIndex(item => item === document.activeElement);
    if (event.key === "Escape") {
        event.preventDefault();
        closeSystemMenu({ restoreFocus: true });
    } else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        focusSystemMenuItem(activeIndex + (event.key === "ArrowDown" ? 1 : -1));
    } else if (event.key === "Home") {
        event.preventDefault();
        focusSystemMenuItem(0);
    } else if (event.key === "End") {
        event.preventDefault();
        focusSystemMenuItem(items.length - 1);
    }
});
document.addEventListener("click", event => {
    const root = $("#systemMenuRoot");
    if (root && !root.contains(event.target)) closeSystemMenu();
});
document.addEventListener("keydown", event => {
    if (event.key === "Escape") closeSystemMenu({ restoreFocus: $("#systemMenuBtn")?.getAttribute("aria-expanded") === "true" });
});

async function shutdownApp() {
    if (!requiresFreshCsrf("остановку CRM")) return;
    if (!confirm("Остановить локальное приложение СТО CRM? Окно можно будет закрыть, а для продолжения работы CRM нужно запустить снова.")) return;
    try {
        await api("/api/shutdown", { method: "POST", body: "{}" });
        clearCachedBootstrap();
        document.body.innerHTML = '<main class="shutdown-state"><section class="shutdown-card"><h1>СТО CRM остановлена</h1><p>Локальный сервер завершает работу. Окно можно закрыть.</p></section></main>';
    } catch (error) {
        toast(error.message || String(error), "error");
    }
}
$("#shutdownBtn")?.addEventListener("click", () => shutdownApp());

// init theme
function systemPrefersDark() {
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
}

function resolveTheme(theme) {
    return theme === "dark" || theme === "light" ? theme : (systemPrefersDark() ? "dark" : "light");
}

function applyTheme(theme) {
    const requested = theme === "dark" || theme === "light" ? theme : "auto";
    const resolved = resolveTheme(requested);
    const isDark = resolved === "dark";
    document.body.classList.toggle("dark", isDark);
    document.body.classList.toggle("light", !isDark);
    document.body.dataset.theme = requested;
    const themeButton = $("#themeToggle");
    if (themeButton) {
        const label = requested === "auto" ? `Тема: авто (${isDark ? "тёмная" : "светлая"})` : `Тема: ${isDark ? "тёмная" : "светлая"}`;
        const icon = requested === "auto" ? "◐" : (isDark ? "◑" : "☼");
        const iconNode = themeButton.querySelector("[data-menu-icon]");
        const labelNode = themeButton.querySelector("[data-menu-label]");
        if (iconNode && labelNode) {
            iconNode.textContent = icon;
            labelNode.textContent = label;
        } else {
            themeButton.textContent = icon;
        }
        themeButton.setAttribute("aria-pressed", requested === "auto" ? "false" : "true");
        themeButton.setAttribute("aria-label", `${label}. Нажмите, чтобы переключить.`);
        themeButton.title = `${label}. Цикл: авто → светлая → тёмная.`;
    }
}

function applyDensity(compact) {
    state.compactMode = Boolean(compact);
    document.body.classList.toggle("compact", state.compactMode);
    const densityButton = $("#densityToggle");
    if (densityButton) {
        const icon = state.compactMode ? "↧" : "↕";
        const label = state.compactMode ? "Плотность: компактная" : "Плотность: обычная";
        const iconNode = densityButton.querySelector("[data-menu-icon]");
        const labelNode = densityButton.querySelector("[data-menu-label]");
        if (iconNode && labelNode) {
            iconNode.textContent = icon;
            labelNode.textContent = label;
        } else {
            densityButton.textContent = icon;
        }
        densityButton.setAttribute("aria-pressed", state.compactMode ? "true" : "false");
        densityButton.setAttribute("aria-label", state.compactMode ? "Компактный режим включен. Нажмите для обычной плотности." : "Обычная плотность включена. Нажмите для компактного режима.");
        densityButton.title = state.compactMode ? "Компактный режим" : "Обычная плотность";
    }
}

function toggleDensity() {
    applyDensity(!state.compactMode);
    safeStorageSet("sto-crm-density", state.compactMode ? "compact" : "comfortable");
    toast(state.compactMode ? "Компактная плотность включена" : "Обычная плотность включена");
}

function safeStorageGet(key) {
    try { return window.localStorage ? localStorage.getItem(key) : null; }
    catch { return null; }
}

function safeStorageSet(key, value) {
    try {
        if (!window.localStorage) return;
        if (value === null || value === "") localStorage.removeItem(key);
        else localStorage.setItem(key, value);
    }
    catch { /* storage can be disabled in private or locked-down modes */ }
}

function nextThemePreference(current) {
    const normalized = current === "dark" || current === "light" ? current : "auto";
    if (normalized === "auto") return "light";
    if (normalized === "light") return "dark";
    return "auto";
}

applyTheme(safeStorageGet("sto-crm-theme") || "auto");
const savedDensity = safeStorageGet("sto-crm-density");
applyDensity(savedDensity ? savedDensity === "compact" : true);
const densityToggle = $("#densityToggle");
if (densityToggle) {
    densityToggle.addEventListener("click", toggleDensity);
}
const themeToggle = $("#themeToggle");
if (themeToggle) {
    themeToggle.addEventListener("click", () => {
        const currentTheme = safeStorageGet("sto-crm-theme") || "auto";
        const nextTheme = nextThemePreference(currentTheme);
        safeStorageSet("sto-crm-theme", nextTheme === "auto" ? null : nextTheme);
        applyTheme(nextTheme);
    });
}
if (window.matchMedia) {
    const colorSchemeQuery = window.matchMedia("(prefers-color-scheme: dark)");
    const onSystemThemeChange = () => {
        if (!safeStorageGet("sto-crm-theme")) applyTheme("auto");
    };
    if (colorSchemeQuery.addEventListener) colorSchemeQuery.addEventListener("change", onSystemThemeChange);
    else if (colorSchemeQuery.addListener) colorSchemeQuery.addListener(onSystemThemeChange);
}

initShell();
window.addEventListener("popstate", () => setRoute(routeFromLocation(), false));
window.addEventListener("hashchange", () => setRoute(routeFromLocation(), false));
setRoute(state.route, false);
loadData().catch(showError);
