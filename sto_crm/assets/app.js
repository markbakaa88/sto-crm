
const state = {
    route: "dashboard",
    q: "",
    status: "all",
    catalogQ: "",
    data: null,
    updateStatus: null,
    updateLoading: false,
    updateInstalling: false,
    loadSeq: 0,
    lastError: "",
    orderDraftItems: [],
    inspectionDraftItems: [],
    bootstrapAbortController: null,
    modalDirty: false,
    saving: false,
    loading: false,
    lastLoadedAt: "",
    compactMode: false
};

const routes = {
    dashboard: "Панель",
    appointments: "Запись",
    inspections: "Осмотры",
    orders: "Заказы",
    customers: "Клиенты",
    vehicles: "Автомобили",
    catalog: "Каталог авто",
    inventory: "Склад",
    reports: "Отчеты",
    updates: "Обновления"
};

const routeSubtitles = {
    dashboard: "Оперативная сводка автосервиса",
    appointments: "Календарь приемки, подтверждения и неявки",
    inspections: "Цифровые мульти-точечные осмотры и рекомендации",
    orders: "Заказ-наряды, сроки и оплаты",
    customers: "Клиентская база и история обращений",
    vehicles: "Автомобили клиентов, VIN и пробеги",
    catalog: "Полный справочник производителей и моделей",
    inventory: "Остатки, цены и себестоимость",
    reports: "Финансы, загрузка и складские риски",
    updates: "Безопасная проверка и установка релизов GitHub"
};

const requestedRoute = new URLSearchParams(location.search).get("route") || location.hash.replace("#", "");
if (requestedRoute && routes[requestedRoute]) {
    state.route = requestedRoute;
}

const priorityLabels = { low: "Низкий", normal: "Обычный", high: "Высокий", urgent: "Срочно" };
const channelLabels = { phone: "Телефон", sms: "SMS", email: "Email", messenger: "Мессенджер", none: "Не писать" };
function channelLabel(key) {
    return (state.data?.preferred_channels || channelLabels)[key] || channelLabels[key] || key;
}
const appointmentStatusFallback = { scheduled: "Запланирована", confirmed: "Подтверждена", arrived: "Клиент приехал", done: "Завершена", no_show: "Не приехал", cancelled: "Отменена" };
const itemApprovalFallback = { approved: "Согласовано", deferred: "Отложено", declined: "Отказ" };
const inspectionStatusFallback = { draft: "Черновик", ready: "Готов", sent: "Отправлен клиенту", archived: "Архив" };
const inspectionConditionFallback = { ok: "Норма", attention: "Внимание", critical: "Критично" };

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

function esc(value) {
    return String(value ?? "").replace(/[&<>"']/g, ch => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    }[ch]));
}

function money(value) {
    return new Intl.NumberFormat("ru-RU", { style: "currency", currency: "RUB", minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(Number(value || 0));
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
    const parsed = Number(String(value).replace(/\s+/g, "").replace(",", "."));
    return Number.isFinite(parsed) ? parsed : fallback;
}

function dateShort(value) {
    if (!value) return "";
    const parsed = new Date(String(value).replace(" ", "T"));
    if (Number.isNaN(parsed.getTime())) return String(value).slice(0, 16);
    return parsed.toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function inputDateValue(value) {
    if (!value) return "";
    return String(value).replace(" ", "T").slice(0, 16);
}

function vehicleName(vehicle) {
    if (!vehicle) return "";
    return [vehicle.make, vehicle.model, vehicle.year, vehicle.plate].filter(Boolean).join(" ");
}

function orderVehicle(order) {
    return [order.vehicle_make, order.vehicle_model, order.vehicle_year, order.vehicle_plate].filter(Boolean).join(" ");
}

function inspectionVehicle(inspection) {
    return [inspection.vehicle_make, inspection.vehicle_model, inspection.vehicle_year, inspection.vehicle_plate].filter(Boolean).join(" ");
}

function appointmentVehicle(appointment) {
    return [appointment.vehicle_make, appointment.vehicle_model, appointment.vehicle_year, appointment.vehicle_plate].filter(Boolean).join(" ");
}

function classToken(value) {
    return String(value ?? "").toLowerCase().replace(/[^a-z0-9_-]+/g, "-") || "unknown";
}

function formatClockTime(value) {
    const parsed = value ? new Date(value) : new Date();
    if (Number.isNaN(parsed.getTime())) return "—";
    return parsed.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
}

function contextPill(label, value, hint, tone = "") {
    const toneClass = tone ? ` ${classToken(tone)}` : "";
    return `<article class="context-pill${toneClass}" aria-label="${esc(`${label}: ${value}. ${hint}`)}"><div class="context-label"><span class="live-dot" aria-hidden="true"></span>${esc(label)}</div><strong>${esc(value)}</strong><span>${esc(hint)}</span></article>`;
}

function contextStripHtml() {
    if (!state.data) return "";
    const r = state.data.reports || {};
    const riskCount = Number(r.overdue_orders_count || 0) + Number(r.inspection_alerts_count || 0) + Number(r.low_stock_count || 0);
    const riskTone = riskCount > 0 ? (riskCount > 3 ? "danger" : "warning") : "success";
    return `<section class="context-strip" aria-label="Операционный статус CRM">
        ${contextPill("Смена", `${Math.max(0, Math.min(100, Number(r.business_health_score || 0)))}/100 · ${r.business_health_label || "Контроль"}`, "Индекс здоровья сервиса", riskTone)}
        ${contextPill("Воронка", money(r.pipeline_value || 0), `${r.active_orders || 0} активных заказов`, "info")}
        ${contextPill("К оплате", money(r.due_total || 0), "Дебиторская задолженность", Number(r.due_total || 0) > 0 ? "warning" : "success")}
        ${contextPill("Обновлено", formatClockTime(state.lastLoadedAt), `Онлайн · ${state.data.app?.version || ""}`, "success")}
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

function itemApprovalBadge(status) {
    const label = state.data?.item_approval_statuses?.[status] || itemApprovalFallback[status] || status;
    return `<span class="status item-${classToken(status)}">${esc(label)}</span>`;
}

function inspectionStatusBadge(status) {
    const label = state.data?.inspection_statuses?.[status] || inspectionStatusFallback[status] || status;
    return `<span class="status inspection-${classToken(status)}">${esc(label)}</span>`;
}

function inspectionConditionBadge(status) {
    const label = state.data?.inspection_conditions?.[status] || inspectionConditionFallback[status] || status;
    return `<span class="status condition-${classToken(status)}">${esc(label)}</span>`;
}

function announce(message, urgent = false) {
    const status = $("#appStatus");
    if (!status) return;
    status.setAttribute("aria-live", urgent ? "assertive" : "polite");
    status.textContent = "";
    requestAnimationFrame(() => { status.textContent = message; });
}

function toast(message, type = "info") {
    const node = $("#toast");
    const isError = type === "error";
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
    const form = $("#entityForm") || $("#orderForm") || $("#inspectionForm");
    if (!form) return;
    clearAllFormErrors(form);
    const message = error?.message || String(error || "");
    let target = null;
    let matchedName = "";
    const lower = message.toLocaleLowerCase("ru-RU");
    const hints = [
        ["email", ["email", "почт"]],
        ["vin", ["vin"]],
        ["year", ["год"]],
        ["scheduled_at", ["дата", "время", "запис"]],
        ["promised_at", ["срок"]],
        ["customer_id", ["клиент"]],
        ["vehicle_id", ["автомоб"]],
        ["inventory_id", ["склад", "позици"]],
        ["title", ["наименование", "запчаст"]],
        ["quantity", ["количество"]],
        ["unit_price", ["цена"]],
        ["name", ["имя", "название"]]
    ];
    for (const [name, tokens] of hints) {
        if (tokens.some(token => lower.includes(token))) {
            matchedName = name;
            target = form.elements[name] || form.querySelector(`[data-item="${name}"], [data-inspection-item="${name}"]`);
            break;
        }
    }
    if (window.RadioNodeList && target instanceof RadioNodeList) target = target[0];
    if (!(target instanceof HTMLElement) && matchedName) target = form.querySelector(`[data-item="${matchedName}"], [data-inspection-item="${matchedName}"]`);
    if (!(target instanceof HTMLElement)) target = form.querySelector("input, select, textarea");
    if (!target) return;
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
    target.classList.remove("invalid");
    target.removeAttribute("aria-invalid");
    const errorId = target.dataset.errorDescribedby;
    if (errorId) document.getElementById(errorId)?.remove();
    const describedBy = (target.getAttribute("aria-describedby") || "").split(/\s+/).filter(Boolean).filter(token => token !== errorId);
    if (describedBy.length) target.setAttribute("aria-describedby", describedBy.join(" "));
    else target.removeAttribute("aria-describedby");
    delete target.dataset.errorDescribedby;
}

async function api(path, options = {}, retries = null) {
    const method = String(options.method || "GET").toUpperCase();
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
                const error = new Error(data?.error || data || "Ошибка запроса");
                error.status = response.status;
                error.retryable = response.status >= 500;
                throw error;
            }
            return data;
        } catch (error) {
            if (error?.name === "AbortError") throw error;
            const retryable = error?.retryable === true || !Number(error?.status || 0);
            if (attempt === maxRetries || !retryable) throw error;
            await new Promise(r => setTimeout(r, 400 * (attempt + 1)));
        }
    }
}

function cacheBootstrap(data) {
    try {
        if (window.sessionStorage) sessionStorage.setItem("sto-crm-bootstrap", JSON.stringify(data));
    } catch (_error) { /* sessionStorage can be unavailable in locked-down browsers */ }
}

function restoreCachedBootstrap() {
    try {
        if (!window.sessionStorage) return false;
        const cached = sessionStorage.getItem("sto-crm-bootstrap");
        if (!cached) return false;
        const data = JSON.parse(cached);
        if (!data || typeof data !== "object" || !data.app) return false;
        state.data = data;
        state.lastLoadedAt = state.lastLoadedAt || new Date().toISOString();
        const dbPath = $("#dbPath");
        if (dbPath) {
            dbPath.textContent = `База: ${state.data.app.db_path}`;
            dbPath.title = state.data.app.db_directory ? `Папка базы: ${state.data.app.db_directory}` : "";
        }
        render();
        updateSearchClear();
        announce("Показаны последние сохраненные данные. Сервер CRM недоступен.", true);
        return true;
    } catch (_error) {
        return false;
    }
}

function setLoadingState(isLoading) {
    state.loading = isLoading;
    const content = $("#content");
    if (content) content.setAttribute("aria-busy", String(isLoading));
    $("#refreshBtn")?.toggleAttribute("disabled", isLoading);
}

async function loadData() {
    const seq = ++state.loadSeq;
    if (state.bootstrapAbortController) state.bootstrapAbortController.abort();
    const controller = new AbortController();
    state.bootstrapAbortController = controller;
    setLoadingState(true);
    const params = new URLSearchParams({ q: state.q, status: state.status });
    try {
        const data = await api(`/api/bootstrap?${params}`, { signal: controller.signal });
        if (seq !== state.loadSeq) return;
        state.data = data;
        cacheBootstrap(data);
        state.lastLoadedAt = new Date().toISOString();
        state.lastError = "";
        setOnlineState(true);
        $("#dbPath").textContent = `База: ${state.data.app.db_path}`;
        $("#dbPath").title = state.data.app.db_directory ? `Папка базы: ${state.data.app.db_directory}` : "";
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
    const previousRoute = state.route;
    state.route = route;
    if (route === "updates" && !state.updateStatus && !state.updateLoading) {
        window.setTimeout(() => checkForUpdates(false).catch(showError), 0);
    }
    if (updateUrl) {
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
    render();
    if (previousRoute !== route) {
        $("#content")?.scrollIntoView({ behavior: prefersReducedMotion() ? "auto" : "smooth", block: "start" });
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
    const renderers = {
        dashboard: renderDashboard,
        appointments: renderAppointments,
        inspections: renderInspections,
        orders: renderOrders,
        customers: renderCustomers,
        vehicles: renderVehicles,
        catalog: renderCatalog,
        inventory: renderInventory,
        reports: renderReports,
        updates: renderUpdates
    };
    const busy = content.getAttribute("aria-busy") || "false";
    content.innerHTML = `${offlineBannerHtml()}${errorBannerHtml()}${contextStripHtml()}${renderers[state.route]()}`;
    content.setAttribute("aria-busy", busy);
    bindViewActions(content);
    bindCatalogFilter(content);
    updateScrollHints(content);
    updateNavigationBadges();
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

function offlineBannerHtml() {
    return `<div class="offline-banner" role="alert">Нет связи с локальным сервером. Проверьте, что СТО CRM запущена, или нажмите «Обновить». Доступные данные могут быть устаревшими.</div>`;
}

function errorBannerHtml() {
    if (!state.lastError) return "";
    return `<div class="error-banner" role="alert"><strong>Последнее действие не выполнено.</strong><span>${esc(state.lastError)}</span><button class="btn ghost" type="button" data-action="dismiss-error">Скрыть</button></div>`;
}

function setOnlineState(isOnline) {
    const app = $(".app");
    if (app) app.classList.toggle("offline", !isOnline);
}

function updateNavigationBadges() {
    const r = state.data?.reports || {};
    const badgeValues = {
        dashboard: r.action_plan_total || 0,
        appointments: r.appointments_today_count || 0,
        inspections: r.inspection_alerts_count || 0,
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
}

function updateSearchClear() {
    const clearButton = $("#clearSearch");
    if (clearButton) clearButton.hidden = !state.q;
}

function clearGlobalSearch() {
    const input = $("#globalSearch");
    state.q = "";
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
        { icon: "⌂", title: "Панель управления", hint: "Executive cockpit и риски", keys: "G P", run: () => setRoute("dashboard") },
        { icon: "📅", title: "Новая запись", hint: "Поставить клиента в календарь", keys: "N A", run: () => openAppointmentModal() },
        { icon: "✓", title: "Новый осмотр DVI", hint: "Цифровой мульти-точечный осмотр", keys: "N D", run: () => openInspectionModal() },
        { icon: "№", title: "Новый заказ-наряд", hint: "Работы, запчасти и оплаты", keys: "N O", run: () => openOrderModal() },
        { icon: "👤", title: "Новый клиент", hint: "Добавить клиента в CRM", keys: "N C", run: () => openCustomerModal() },
        { icon: "🚘", title: "Новый автомобиль", hint: "Карточка авто и сервисный план", keys: "N V", run: () => openVehicleModal() },
        { icon: "▦", title: "Новая позиция склада", hint: "Остатки, цена и себестоимость", keys: "N S", run: () => openInventoryModal() },
        { icon: "↗", title: "Отчеты", hint: "Финансы, маржа и закупки", keys: "G R", run: () => setRoute("reports") },
        { icon: "◎", title: "Каталог авто", hint: "Марки и модели", keys: "G C", run: () => setRoute("catalog") },
        { icon: "↻", title: "Обновить данные", hint: "Перезагрузить bootstrap", keys: "R", run: () => loadData().then(() => toast("Обновлено")).catch(showError) },
        { icon: "↕", title: "Плотность интерфейса", hint: "Компактный или комфортный режим", keys: "D", run: () => toggleDensity() },
        { icon: "⇩", title: "Резервная копия", hint: "Создать консистентный backup SQLite", keys: "B", run: () => createBackupFromUi() },
        { icon: "⬢", title: "Проверить обновления", hint: "GitHub release-only", keys: "U", run: () => { setRoute("updates"); checkForUpdates(true).catch(showError); } }
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
        <button id="${optionId}" class="command-item ${index === 0 ? "active" : ""}" type="button" role="option" data-command-index="${index}" aria-selected="${index === 0 ? "true" : "false"}">
            <span aria-hidden="true">${esc(item.icon)}</span>
            <span><strong>${esc(item.title)}</strong><div class="muted">${esc(item.hint)}</div></span>
            <kbd>${esc(item.keys)}</kbd>
        </button>`;
    }).join("") || `<div class="empty"><strong>Команда не найдена</strong><span>Попробуйте другой запрос.</span></div>`;
    updateCommandSearchAria(items.length ? "commandOption0" : "");
}

function openCommandPalette() {
    if (!state.data) return;
    lastFocusedElement = document.activeElement instanceof HTMLElement ? document.activeElement : null;
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
    const wasOpen = $("#commandPalette")?.classList.contains("open");
    $("#commandPalette")?.classList.remove("open");
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

async function createBackupFromUi() {
    try {
        const result = await api("/api/backup", { method: "POST", body: "{}" });
        toast(`Резервная копия: ${result.path}`);
    } catch (error) {
        showError(error);
    }
}

function sectionIntro(title, text, options = {}) {
    const className = options.hero ? "section-card hero-card" : "section-card";
    const eyebrow = options.eyebrow ? `<div class="hero-eyebrow">${esc(options.eyebrow)}</div>` : "";
    const actions = (options.actions || []).length
        ? `<div class="hero-actions">${options.actions.map(action => action.action === "export-csv"
            ? `<button class="btn ghost" type="button" data-action="export-csv" data-export="${esc(action.export || "")}">${esc(action.label || "CSV")}</button>`
            : `<button class="btn ${esc(action.className || "")}" type="button" data-action="${esc(action.action || "")}">${esc(action.label || "Открыть")}</button>`).join("")}</div>`
        : "";
    const stats = (options.stats || []).length
        ? `<div class="hero-stat-stack">${options.stats.map(item => `<div class="hero-stat"><strong>${esc(item.value)}</strong><span>${esc(item.label)}</span></div>`).join("")}</div>`
        : "";
    if (options.hero) {
        return `<section class="${className}"><div class="hero-layout"><div>${eyebrow}<h3>${esc(title)}</h3><p>${esc(text)}</p>${actions}</div>${stats}</div></section>`;
    }
    return `<section class="${className}"><h3>${esc(title)}</h3><p>${esc(text)}</p></section>`;
}

function emptyState(title, text, action = "") {
    return `<div class="empty"><strong>${esc(title)}</strong><span>${esc(text)}</span>${action}</div>`;
}

function insightCard(label, value, hint, options = {}) {
    const icon = options.icon || String(label || "").trim().slice(0, 1).toLocaleUpperCase("ru-RU") || "•";
    return `<article class="insight-card" aria-label="${esc(`${label}: ${value}`)}"><div class="insight-head"><small>${esc(label)}</small><span class="insight-icon" aria-hidden="true">${esc(icon)}</span></div><strong>${esc(value)}</strong><span class="muted">${esc(hint)}</span></article>`;
}

function viewHeading(title, text, meta = [], actions = []) {
    const metaHtml = meta.length ? `<div class="view-meta">${meta.map(item => `<span class="count-pill">${esc(item)}</span>`).join("")}</div>` : "";
    const actionsHtml = actions.length ? `<div class="view-heading-actions">${actions.map(action => action.action === "export-csv"
        ? `<button class="btn ghost" type="button" data-action="export-csv" data-export="${esc(action.export || "")}">${esc(action.label || "CSV")}</button>`
        : `<button class="btn ${esc(action.className || "")}" type="button" data-action="${esc(action.action || "")}"${action.export ? ` data-export="${esc(action.export)}"` : ""}>${esc(action.label || "Открыть")}</button>`).join("")}</div>` : "";
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

function labeledField(id, label, controlHtml, span = "") {
    return `<div class="field ${esc(span)}"><label for="${esc(id)}">${esc(label)}</label>${controlHtml}</div>`;
}

function fieldId(formScope, name) {
    return `${formScope}_${name}`.replace(/[^a-zA-Z0-9_-]/g, "_");
}

function inputField(formScope, name, label, attributes = "", span = "") {
    const id = fieldId(formScope, name);
    return labeledField(id, label, `<input id="${id}" name="${esc(name)}" ${attributes}>`, span);
}

function selectField(formScope, name, label, optionsHtml, attributes = "", span = "") {
    const id = fieldId(formScope, name);
    return labeledField(id, label, `<select id="${id}" name="${esc(name)}" ${attributes}>${optionsHtml}</select>`, span);
}

function textareaField(formScope, name, label, value = "", attributes = "", span = "") {
    const id = fieldId(formScope, name);
    return labeledField(id, label, `<textarea id="${id}" name="${esc(name)}" ${attributes}>${esc(value)}</textarea>`, span);
}

function renderDashboard() {
    const r = state.data.reports;
    const recent = [...state.data.orders].slice(0, 6);
    const catalog = state.data.car_catalog?.stats || { makes: 0, models: 0 };
    return `
        ${sectionIntro("Управляйте сменой автосервиса без хаоса", "Executive cockpit объединяет деньги, загрузку, DVI-риски, склад и приоритетный план действий мастера-приемщика.", {
            hero: true,
            eyebrow: "Premium workspace",
            actions: [
                { label: "Новый заказ", action: "new-order", className: "primary" },
                { label: "Записать клиента", action: "new-appointment", className: "ghost" },
                { label: "План смены", action: "open-action-plan", className: "ghost" } // data-action="open-action-plan"
            ],
            stats: [
                { label: "Индекс смены", value: `${Math.max(0, Math.min(100, Number(r.business_health_score || 0)))}/100` },
                { label: "Активная воронка", value: money(r.pipeline_value || 0) },
                { label: "Записей сегодня", value: r.appointments_today_count || 0 },
                { label: "Задач в плане", value: r.action_plan_total || 0 }
            ]
        })}
        <section class="kpi-grid">
            ${healthMetric(r)}
            ${metric("Открытые заказ-наряды", r.active_orders, `${money(r.pipeline_value || 0)} в активной воронке`)}
            ${metric("Выручка месяца", money(r.revenue_month), "По закрытым заказам")}
            ${metric("CRM задачи", r.crm_tasks_count, `${r.overdue_orders_count || 0} просрочено · ${r.inspection_alerts_count || 0} DVI рисков`)}
        </section>
        <section class="insight-grid">
            ${insightCard("К оплате", money(r.due_total), "Дебиторская задолженность")}
            ${insightCard("Маржа месяца", money(r.gross_margin_month || 0), `${num(r.margin_percent_month).toFixed(1)}% валовой маржи`)}
            ${insightCard("Конверсия смет", `${num(r.conversion_rate).toFixed(1)}%`, "Согласование → работа")}
            ${insightCard("Активная воронка", money(r.pipeline_value || 0), `${money(r.pipeline_due || 0)} ожидает оплаты`)}
            ${insightCard("Стоимость склада", money(r.inventory_value || 0), "По себестоимости активных остатков")}
            ${insightCard("Закупка", money((r.procurement_plan || []).reduce((sum, item) => sum + num(item.budget), 0)), `${(r.procurement_plan || []).length} позиций к заказу`)}
        </section>
        <section class="workspace-grid">
            <div class="dashboard-rail">
                <div class="panel lifted action-center">
                    <div class="panel-head"><h2>План смены</h2><span class="count-pill">${r.action_plan_total || 0}</span></div>
                    <div class="panel-body">${actionPlanList(r.action_plan || [])}</div>
                </div>
                <div class="executive-grid">
                    <div class="panel">
                        <div class="panel-head"><h2>Радар рисков</h2><span class="count-pill">${r.risk_total || 0}</span></div>
                        <div class="panel-body">${riskRadar(r)}</div>
                    </div>
                    <div class="panel">
                        <div class="panel-head"><h2>Быстрые действия</h2><button class="btn ghost" type="button" data-action="open-action-plan">К плану</button></div>
                        <div class="panel-body">${quickActions()}</div>
                    </div>
                </div>
                <div class="panel lifted">
                    <div class="panel-head"><h2>Воронка заказ-нарядов</h2><button class="btn" type="button" data-action="open-orders">Все заказы</button></div>
                    <div class="panel-body">${pipelineBoard(r.pipeline_by_status || [])}</div>
                </div>
                <div class="panel">
                    <div class="panel-head"><h2>Последние заказ-наряды</h2><button class="btn primary" type="button" data-action="new-order">Новый заказ</button></div>
                    ${ordersTable(recent, true)}
                </div>
            </div>
            <aside class="dashboard-rail" aria-label="Операционный сайдбар">
                <div class="panel lifted">
                    <div class="panel-head"><h2>Состояние бизнеса</h2></div>
                    <div class="panel-body">
                        ${miniLedger(r)}
                    </div>
                </div>
                <div class="panel">
                    <div class="panel-head"><h2>Загрузка на 7 дней</h2><button class="btn" type="button" data-action="open-appointments">Календарь</button></div>
                    <div class="panel-body">${appointmentTimeline(r.appointment_load_7_days || [])}</div>
                </div>
                <div class="panel">
                    <div class="panel-head"><h2>Просроченные сроки</h2><button class="btn" type="button" data-action="open-orders">Открыть</button></div>
                    <div class="panel-body">${overdueOrderList(r.overdue_orders || [])}</div>
                </div>
                <div class="panel">
                    <div class="panel-head"><h2>Осмотры DVI</h2><button class="btn" type="button" data-action="new-inspection">Новый</button></div>
                    <div class="panel-body">${inspectionAlertList(r.inspection_alerts)}</div>
                </div>
                <div class="panel">
                    <div class="panel-head"><h2>План закупки</h2><button class="btn" type="button" data-action="open-inventory">Склад</button></div>
                    <div class="panel-body">${procurementList(r.procurement_plan || [])}</div>
                </div>
                <div class="panel">
                    <div class="panel-head"><h2>CRM задачи</h2></div>
                    <div class="panel-body">${crmTaskList(r)}</div>
                </div>
                <div class="panel">
                    <div class="panel-head"><h2>VIP и удержание</h2></div>
                    <div class="panel-body">${vipCustomerList(r.vip_customers)}</div>
                </div>
                <div class="panel">
                    <div class="panel-head"><h2>Загрузка мастеров</h2></div>
                    <div class="panel-body">${workloadList(r.workload_by_responsible || [])}</div>
                </div>
            </aside>
        </section>
    `;
}

function metric(label, value, hint, options = {}) {
    const toneClass = options.tone ? ` tone-${classToken(options.tone)}` : "";
    const icon = options.icon || String(label || "").trim().slice(0, 1).toLocaleUpperCase("ru-RU") || "•";
    return `<article class="metric${toneClass}" aria-label="${esc(`${label}: ${value}`)}"><div class="metric-top"><small>${esc(label)}</small><span class="metric-icon" aria-hidden="true">${esc(icon)}</span></div><strong>${esc(value)}</strong><div class="trend">${esc(hint)}</div></article>`;
}

function miniLedger(report) {
    const cells = [
        ["Заказов", report.orders_total || 0],
        ["Закрыто", report.closed_orders_count || 0],
        ["Клиентов", state.data.lookups.customers.length],
        ["Авто", state.data.lookups.vehicles.length]
    ];
    return `<div class="mini-ledger">${cells.map(([label, value]) => `<div class="mini-ledger-card"><small>${esc(label)}</small><strong>${esc(value)}</strong></div>`).join("")}</div>`;
}

function riskRadar(report) {
    const rows = [
        { label: "Просрочки", value: report.overdue_orders_count || 0, max: 8, tone: "danger" },
        { label: "DVI риски", value: report.inspection_alerts_count || 0, max: 8, tone: "warning" },
        { label: "Склад", value: report.low_stock_count || 0, max: 8, tone: "info" },
        { label: "Сметы", value: (report.authorizations_pending || []).length, max: 8, tone: "warning" }
    ];
    return `<div class="signal-grid">${rows.map(row => {
        const width = Math.min(100, Math.round(Number(row.value || 0) / Math.max(1, row.max) * 100));
        return `<div class="signal-row"><div class="signal-row-head"><strong>${esc(row.label)}</strong><span>${esc(row.value)}</span></div><div class="signal-track" role="img" aria-label="${esc(row.label)}: ${esc(row.value)}"><div class="signal-fill ${esc(row.tone)}" style="--value:${width}%"></div></div></div>`;
    }).join("")}</div>`;
}

function quickActions() {
    const actions = [
        ["new-appointment", "📅", "Запись", "Поставить клиента в календарь"],
        ["new-inspection", "✓", "DVI", "Создать цифровой осмотр"],
        ["new-order", "№", "Заказ", "Оформить заказ-наряд"],
        ["new-customer", "👤", "Клиент", "Добавить контакт и канал связи"]
    ];
    return `<div class="quick-grid">${actions.map(([action, icon, title, hint]) => `<button class="quick-tile" type="button" data-action="${esc(action)}"><span class="quick-icon" aria-hidden="true">${esc(icon)}</span><strong>${esc(title)}</strong><span>${esc(hint)}</span></button>`).join("")}</div>`;
}

function healthMetric(report) {
    const score = Math.max(0, Math.min(100, Number(report.business_health_score || 0)));
    return `<article class="metric health-card" aria-label="Индекс смены: ${score} из 100"><div class="metric-top"><small>Индекс смены</small><span class="metric-icon" aria-hidden="true">↗</span></div><strong><span class="health-score">${score}</span><span>/100</span></strong><div class="trend">${esc(report.business_health_label || "Контроль")} · просрочки, склад и DVI</div></article>`;
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
                        <button class="btn ghost" type="button" data-action="edit-order" data-id="${order.id}">Открыть</button>
                    </div>`;
                }).join("") || `<div class="muted">Нет заказов в статусе.</div>`}
            </div>
        </article>`).join("")}</div>`;
}

function appointmentTimeline(days = []) {
    if (!days.length) return `<div class="muted">Нет данных календаря.</div>`;
    const todayKey = new Date().toISOString().slice(0, 10);
    const maxCount = Math.max(...days.map(day => Number(day.count || 0)), 1);
    return `<div class="timeline">${days.map(day => {
        const width = Number(day.count || 0) ? Math.max(8, Math.round(Number(day.count || 0) / maxCount * 100)) : 0;
        return `
        <article class="timeline-day ${day.date === todayKey ? "today" : ""}">
            <strong><span>${esc(day.label)}</span><span class="count-pill">${day.count}</span></strong>
            <div class="bar-track" aria-label="Загрузка ${esc(day.label)}: ${day.count}"><div class="bar-fill" style="width:${width}%"></div></div>
            <div class="timeline-list">${(day.appointments || []).slice(0, 2).map(item => `<span>${dateShort(item.scheduled_at)} · ${esc(item.customer_name || "")}</span>`).join("") || `<span class="muted">Свободно</span>`}</div>
        </article>`;
    }).join("")}</div>`;
}

function overdueOrderList(orders = []) {
    if (!orders.length) return `<div class="muted">Просроченных заказ-нарядов нет.</div>`;
    return `<div class="stack">${orders.map(order => `
        <div class="deal-card overdue">
            <strong>${esc(order.number)} · ${money(order.total)}</strong>
            <div class="muted">${esc(order.customer_name || "")} · ${esc(order.vehicle || "")} · срок ${dateShort(order.promised_at)}</div>
            <button class="btn ghost" type="button" data-action="edit-order" data-id="${order.id}">Открыть</button>
        </div>`).join("")}</div>`;
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
        return `<div class="empty"><strong>План смены чист</strong><span>Нет просрочек, критичных DVI, срочных закупок и задач follow-up.</span></div>`;
    }
    return `<div class="action-stream">${items.map(item => {
        const meta = [
            item.customer_name,
            item.customer_phone,
            item.vehicle,
            item.due_at ? dateShort(item.due_at) : "",
            Number(item.amount || 0) ? money(item.amount) : ""
        ].filter(Boolean);
        return `<article class="action-card ${esc(classToken(item.tone || "info"))}">
            <div>
                <strong>${esc(item.title)}</strong>
                <p>${esc(item.detail || "")}</p>
                <div class="action-meta">
                    <span class="action-priority">${esc(item.priority_label || "Планово")}</span>
                    ${meta.map(value => `<span class="count-pill">${esc(value)}</span>`).join("")}
                </div>
            </div>
            <div class="action-side">
                <span class="action-score">${Number(item.priority || 0)}/100</span>
                <button class="btn primary" type="button" data-action="${esc(item.action || "")}" data-id="${esc(item.record_id || "")}" data-route-target="${esc(item.route || "dashboard")}">${esc(item.cta || "Открыть")}</button>
            </div>
        </article>`;
    }).join("")}</div>`;
}

function renderAppointments() {
    const rows = state.data.appointments || [];
    const upcoming = state.data.reports?.appointments_upcoming || [];
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
        <div class="table-wrap">
            <table aria-label="Таблица записей клиентов">
                <thead>${tableHead(["Дата и время", "Клиент и авто", "Статус", "Длительность", "Мастер", "Причина", ""])}</thead>
                <tbody>
                    ${rows.map(appointment => `
                        <tr>
                            <td class="nowrap">${dateShort(appointment.scheduled_at)}</td>
                            <td><div class="cell-title"><strong>${esc(appointment.customer_name)}</strong><div class="muted">${esc(appointment.customer_phone)} · ${esc(appointmentVehicle(appointment) || "Авто не выбрано")}</div></div></td>
                            <td>${appointmentStatusBadge(appointment.status)}</td>
                            <td>${Number(appointment.duration_minutes || 0)} мин</td>
                            <td>${esc(appointment.advisor || "")}</td>
                            <td><div class="cell-title"><strong>${esc(appointment.reason || "")}</strong><div class="muted">${esc(appointment.notes || "")}</div></div></td>
                            <td><div class="row-actions"><button class="btn" type="button" data-action="edit-appointment" data-id="${appointment.id}">Открыть</button></div></td>
                        </tr>`).join("") || `<tr><td colspan="7" class="empty"><strong>Записей не найдено</strong><span>Создайте запись клиента в календаре.</span></td></tr>`}
                </tbody>
            </table>
        </div>
    `;
}

function renderInspections() {
    const rows = state.data.inspections || [];
    return `
        ${viewHeading("Digital Vehicle Inspection", "Фиксируйте состояние автомобиля, критичные пункты, рекомендации и согласования клиента в профессиональном DVI-процессе.", [
            `${rows.length} осмотров`,
            `${state.data.reports.inspection_alerts_count || 0} рисков DVI`,
            `${state.data.reports.crm_tasks_count || 0} CRM задач`
        ], [
            { label: "CSV", action: "export-csv", export: "inspections", className: "ghost" },
            { label: "Новый осмотр", action: "new-inspection", className: "primary" }
        ])}
        <section class="kpi-grid">
            ${metric("Осмотров", state.data.reports.inspections_count || 0, "История DVI по клиентам и авто")}
            ${metric("Риски DVI", state.data.reports.inspection_alerts_count || 0, "Требуют согласования и follow-up")}
            ${metric("Каталог авто", state.data.car_catalog?.stats?.models || 0, "Моделей для точной карточки авто")}
            ${metric("CRM задачи", state.data.reports.crm_tasks_count, "Осмотры, follow-up и сервисные напоминания")}
        </section>
        <div class="table-wrap">
            <table aria-label="Таблица цифровых осмотров">
                <thead>${tableHead(["Дата", "Клиент и авто", "Статус", "Пункты", "Риски", {text: "Рекомендации", className: "money"}, ""])}</thead>
                <tbody>
                    ${rows.map(inspection => `
                        <tr>
                            <td class="nowrap">${dateShort(inspection.inspected_at)}</td>
                            <td><div class="cell-title"><strong>${esc(inspection.customer_name)}</strong><div class="muted">${esc(inspectionVehicle(inspection) || "Авто не выбрано")} ${inspection.order_number ? `· ${esc(inspection.order_number)}` : ""}</div></div></td>
                            <td>${inspectionStatusBadge(inspection.status)}</td>
                            <td>${Number(inspection.items_count || 0)}</td>
                            <td><div class="cell-title"><strong>${Number(inspection.critical_count || 0)} крит.</strong><div class="muted">${Number(inspection.attention_count || 0)} требует внимания</div></div></td>
                            <td class="money">${money(inspection.recommended_total)}</td>
                            <td><div class="row-actions"><button class="btn" type="button" data-action="edit-inspection" data-id="${inspection.id}">Открыть</button></div></td>
                        </tr>`).join("") || `<tr><td colspan="7" class="empty"><strong>Осмотров не найдено</strong><span>Создайте цифровой осмотр DVI.</span></td></tr>`}
                </tbody>
            </table>
        </div>
    `;
}

function smallOrderList(orders) {
    if (!orders.length) return `<div class="muted">Нет запланированных выдач.</div>`;
    return `<div class="stack">${orders.map(order => `
        <div>
            <strong>${esc(order.number)}</strong> · ${statusBadge(order.status)}
            <div class="muted">${esc(order.customer_name)} · ${esc(orderVehicle(order))} · ${dateShort(order.promised_at)}</div>
        </div>`).join("")}</div>`;
}

function appointmentList(appointments) {
    if (!appointments?.length) return `<div class="muted">Записей на сегодня нет.</div>`;
    return `<div class="stack">${appointments.map(appointment => `
        <div>
            <strong>${dateShort(appointment.scheduled_at)} · ${esc(appointment.customer_name)}</strong> ${appointmentStatusBadge(appointment.status)}
            <div class="muted">${esc(appointmentVehicle(appointment) || "Авто не выбрано")} · ${esc(appointment.reason || "")}</div>
        </div>`).join("")}</div>`;
}

function inspectionAlertList(items) {
    if (!items?.length) return `<div class="muted">Критичных пунктов осмотра нет.</div>`;
    return `<div class="stack">${items.map(item => `
        <div>
            <strong>${esc(item.title)}</strong> ${inspectionConditionBadge(item.condition_status)}
            <div class="muted">${esc(item.customer_name)} · ${esc(item.vehicle || "")} · ${money(item.estimate)}</div>
        </div>`).join("")}</div>`;
}

function lowStockList(parts) {
    if (!parts.length) return `<div class="muted">Критичных остатков нет.</div>`;
    return `<div class="stack">${parts.map(part => `
        <div>
            <strong>${esc(part.name)}</strong>
            <div class="muted">${esc(part.sku)} · остаток ${qty(part.quantity)} ${esc(part.unit)} · минимум ${qty(part.min_quantity)}</div>
        </div>`).join("")}</div>`;
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
        <div class="toolbar">
            <div class="toolbar-left">
                <div class="segmented" role="group" aria-label="Фильтр заказов по статусу">
                    ${["all", "new", "diagnostics", "estimate", "approved", "in_progress", "done", "closed"].map(status => `
                        <button type="button" data-action="filter-status" data-status="${status}" class="${state.status === status ? "active" : ""}" aria-pressed="${state.status === status ? "true" : "false"}">
                            ${status === "all" ? "Все" : esc(state.data.statuses[status])}
                        </button>`).join("")}
                </div>
            </div>
        </div>
        ${ordersTable(state.data.orders, false)}
    `;
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
                            <td><div class="cell-title"><strong>${esc(order.number)}</strong><div class="priority ${esc(order.priority)}">${esc(priorityLabels[order.priority] || order.priority)}</div></div></td>
                            <td><div class="cell-title"><strong>${esc(order.customer_name)}</strong><div class="muted">${esc(orderVehicle(order) || "Авто не выбрано")}</div></div></td>
                            <td>${statusBadge(order.status)}</td>
                            <td class="money">${money(order.total)}</td>
                            <td>
                                <div class="row-actions">
                                    <button class="btn icon" type="button" title="Печать" aria-label="Печать заказ-наряда ${esc(order.number)}" data-action="print-order" data-id="${order.id}"><span aria-hidden="true">⎙</span></button>
                                    <button class="btn" type="button" data-action="edit-order" data-id="${order.id}">Открыть</button>
                                    <button class="btn ghost" type="button" data-action="duplicate-order" data-id="${order.id}" title="Создать новый заказ на основе текущего">Повторить</button>
                                </div>
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
                        <td><div class="cell-title"><strong>${esc(order.number)}</strong><div class="priority ${esc(order.priority)}">${esc(priorityLabels[order.priority] || order.priority)}</div></div></td>
                        <td><div class="cell-title"><strong>${esc(order.customer_name)}</strong><div class="muted">${esc(orderVehicle(order) || "Авто не выбрано")}</div></div></td>
                        <td>${statusBadge(order.status)}</td>
                        <td class="nowrap">${dateShort(order.promised_at)}</td>
                        <td>${esc(order.mechanic || order.advisor || "")}</td>
                        <td class="money">${money(order.total)}</td>
                        <td class="money">${money(order.due)}</td>
                        <td>
                            <div class="row-actions">
                                <button class="btn icon" type="button" title="Печать" aria-label="Печать заказ-наряда ${esc(order.number)}" data-action="print-order" data-id="${order.id}"><span aria-hidden="true">⎙</span></button>
                                <button class="btn" type="button" data-action="edit-order" data-id="${order.id}">Открыть</button>
                                <button class="btn ghost" type="button" data-action="duplicate-order" data-id="${order.id}" title="Создать новый заказ на основе текущего">Повторить</button>
                            </div>
                        </td>
                    </tr>
                `).join("")}
            </tbody>
        </table>
    </div>`;
}

function renderCustomers() {
    const rows = state.data.customers;
    return `
        ${viewHeading("Клиенты", "Единая клиентская база с каналами связи, согласием на напоминания, автомобилями и историей заказов.", [
            `${rows.length} найдено`,
            `${state.data.lookups.customers.length} всего`,
            `${state.data.reports.vip_customers?.length || 0} VIP`
        ], [
            { label: "CSV", action: "export-csv", export: "customers", className: "ghost" },
            { label: "Новый клиент", action: "new-customer", className: "primary" }
        ])}
        <div class="table-wrap">
            <table aria-label="Таблица клиентов">
                <thead>${tableHead(["Клиент", "Телефон", "Email", "Канал", "Источник", "Авто", "Заказы", ""])}</thead>
                <tbody>
                    ${rows.map(c => `
                        <tr>
                            <td><div class="cell-title"><strong>${esc(c.name)}</strong><div class="muted">${esc(c.notes)}</div></div></td>
                            <td>${esc(c.phone)}</td>
                            <td>${esc(c.email)}</td>
                            <td>${esc(channelLabel(c.preferred_channel))}${Number(c.reminder_consent) ? "" : `<div class="danger-text">без напоминаний</div>`}</td>
                            <td>${esc(c.source)}</td>
                            <td>${c.vehicles_count}</td>
                            <td><div class="cell-title"><strong>${c.orders_count}</strong><div class="muted">${c.last_order_at ? `посл. ${dateShort(c.last_order_at)}` : "нет заказов"}</div></div></td>
                            <td><div class="row-actions"><button class="btn" type="button" data-action="edit-customer" data-id="${c.id}">Открыть</button></div></td>
                        </tr>`).join("") || `<tr><td colspan="8" class="empty"><strong>Клиентов не найдено</strong><span>Добавьте клиента или измените поиск.</span></td></tr>`}
                </tbody>
            </table>
        </div>
    `;
}

function renderVehicles() {
    const rows = state.data.vehicles;
    const catalog = state.data.car_catalog?.stats || { makes: 0, models: 0 };
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
        <div class="table-wrap">
            <table aria-label="Таблица автомобилей">
                <thead>${tableHead(["Автомобиль", "Госномер", "VIN", "Клиент", "Пробег", "Следующий сервис", ""])}</thead>
                <tbody>
                    ${rows.map(v => `
                        <tr>
                            <td><div class="cell-title"><strong>${esc(vehicleName(v))}</strong><div class="muted">${esc(v.notes)}</div></div></td>
                            <td>${v.plate ? `<span class="plate">${esc(v.plate)}</span>` : ""}</td>
                            <td>${esc(v.vin)}</td>
                            <td><div class="cell-title">${esc(v.customer_name)}<div class="muted">${esc(v.customer_phone)}</div></div></td>
                            <td>${Number(v.mileage || 0).toLocaleString("ru-RU")} км</td>
                            <td><div class="cell-title">${esc(v.next_service_at || "")}<div class="muted">${v.next_service_mileage ? `${Number(v.next_service_mileage).toLocaleString("ru-RU")} км` : ""}</div></div></td>
                            <td><div class="row-actions"><button class="btn" type="button" data-action="edit-vehicle" data-id="${v.id}">Открыть</button></div></td>
                        </tr>`).join("") || `<tr><td colspan="7" class="empty"><strong>Автомобилей не найдено</strong><span>Добавьте автомобиль клиента.</span></td></tr>`}
                </tbody>
            </table>
        </div>
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
    if (report.inspection_alerts?.length) {
        blocks.push(...report.inspection_alerts.map(item => `
            <div>
                <strong>DVI: ${esc(item.title)}</strong>
                <div class="muted">${esc(item.customer_name)} · ${esc(item.vehicle || "")} · ${esc(inspectionConditionFallback[item.condition_status] || item.condition_status)} · ${money(item.estimate)}</div>
            </div>`));
    }
    return blocks.length ? `<div class="stack">${blocks.slice(0, 8).join("")}</div>` : `<div class="muted">Нет срочных CRM задач.</div>`;
}

function renderCatalog() {
    const catalog = state.data.car_catalog || { makes: [], models: {}, stats: { makes: 0, models: 0, empty_makes: 0 } };
    const stats = catalog.stats || { makes: 0, models: 0, empty_makes: 0 };
    const entries = filteredCatalogEntries();
    return `
        ${viewHeading("Каталог автомобилей", "Офлайн-справочник производителей и моделей помогает быстро и единообразно заполнять карточки автомобилей.", [
            `${stats.makes} производителей`,
            `${stats.models} моделей`,
            `${entries.length} в подборке`
        ], [
            { label: "CSV каталога", action: "export-csv", export: "catalog", className: "ghost" },
            { label: "Новый автомобиль", action: "new-vehicle", className: "primary" }
        ])}
        <section class="catalog-summary">
            <article class="metric"><small>Производители</small><strong>${stats.makes}</strong><div class="trend">Полный офлайн-справочник марок</div></article>
            <article class="metric"><small>Модели</small><strong>${stats.models}</strong><div class="trend">Доступны в карточке авто</div></article>
            <article class="metric"><small>Без моделей</small><strong>${stats.empty_makes || 0}</strong><div class="trend">Редкие производители из официального списка</div></article>
            <article class="metric"><small>В подборке</small><strong>${entries.length}</strong><div class="trend">Найдено по фильтру</div></article>
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
            ${entries.map(entry => catalogMakeHtml(entry.make, entry.models)).join("") || `<div class="empty">В каталоге ничего не найдено.</div>`}
        </section>
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
        <div class="table-wrap">
            <table aria-label="Таблица складских позиций">
                <thead>${tableHead(["Позиция", "Артикул", "Бренд", "Остаток", {text: "Цена", className: "money"}, {text: "Себестоимость", className: "money"}, "Поставщик", ""])}</thead>
                <tbody>
                    ${rows.map(p => `
                        <tr>
                            <td><div class="cell-title"><strong>${esc(p.name)}</strong>${Number(p.is_low) ? `<div class="danger-text">Ниже минимума</div>` : ""}</div></td>
                            <td>${esc(p.sku)}</td>
                            <td>${esc(p.brand)}</td>
                            <td>${qty(p.quantity)} ${esc(p.unit)}<div class="muted">мин. ${qty(p.min_quantity)}</div></td>
                            <td class="money">${money(p.price)}</td>
                            <td class="money">${money(p.cost)}</td>
                            <td>${esc(p.supplier)}</td>
                            <td><div class="row-actions"><button class="btn" type="button" data-action="edit-inventory" data-id="${p.id}">Открыть</button></div></td>
                        </tr>`).join("") || `<tr><td colspan="8" class="empty"><strong>Складских позиций не найдено</strong><span>Добавьте первую позицию склада.</span></td></tr>`}
                </tbody>
            </table>
        </div>
    `;
}

function renderReports() {
    const r = state.data.reports;
    const maxStatus = Math.max(...Object.values(r.status_counts), 1);
    const maxService = Math.max(...r.top_services.map(x => x.total), 1);
    return `
        ${viewHeading("Отчеты и аналитика", "Финансы, маржа, загрузка, закупки и удержание клиентов для управленческих решений.", [
            `${money(r.revenue_month)} выручка`,
            `${num(r.margin_percent_month).toFixed(1)}% маржа`,
            `${r.low_stock_count || 0} складских рисков`
        ], [
            { label: "Открыть заказы", action: "open-orders", className: "ghost" },
            { label: "Склад", action: "open-inventory", className: "ghost" }
        ])}
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
        <section class="grid-2">
            <div class="panel">
                <div class="panel-head"><h2>Статусы заказов</h2></div>
                <div class="panel-body bars">
                    ${Object.entries(state.data.statuses).map(([key, label]) => `
                        <div class="bar">
                            <span>${esc(label)}</span>
                            <div class="bar-track" role="img" aria-label="${esc(label)}: ${r.status_counts[key] || 0}"><div class="bar-fill" style="width:${Math.round((r.status_counts[key] || 0) / maxStatus * 100)}%"></div></div>
                            <strong>${r.status_counts[key] || 0}</strong>
                        </div>`).join("")}
                </div>
            </div>
            <div class="panel">
                <div class="panel-head"><h2>Топ работ</h2></div>
                <div class="panel-body bars">
                    ${r.top_services.map(item => `
                        <div class="bar">
                            <span>${esc(item.title)}</span>
                            <div class="bar-track" role="img" aria-label="${esc(item.title)}: ${money(item.total)}"><div class="bar-fill" style="width:${Math.round(item.total / maxService * 100)}%"></div></div>
                            <strong>${money(item.total)}</strong>
                        </div>`).join("") || `<div class="muted">Нет данных по работам.</div>`}
                </div>
            </div>
        </section>
        <section class="grid-2">
            <div class="panel">
                <div class="panel-head"><h2>План закупки</h2><button class="btn" type="button" data-action="open-inventory">Склад</button></div>
                <div class="panel-body">${procurementList(r.procurement_plan || [])}</div>
            </div>
            <div class="panel">
                <div class="panel-head"><h2>Загрузка ответственных</h2></div>
                <div class="panel-body">${workloadList(r.workload_by_responsible || [])}</div>
            </div>
        </section>
        <section class="panel">
            <div class="panel-head"><h2>VIP и удержание клиентов</h2></div>
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
            <div class="row-actions" style="justify-content:flex-start">
                <a class="btn ghost" href="${esc(release.release_url || status.releases_url)}" target="_blank" rel="noopener noreferrer">Открыть релиз</a>
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
        <section class="update-card">
            <div class="toolbar">
                <div class="toolbar-left">
                    <h3>Обновление с GitHub</h3>
                    ${updateStatusBadge(status)}
                </div>
                <div class="toolbar-right">
                    <button class="btn ghost" type="button" data-action="check-update" ${state.updateLoading ? "disabled" : ""}>${state.updateLoading ? "Проверяем..." : "Проверить обновления"}</button>
                    <button class="btn primary" type="button" data-action="install-update" title="${esc(installTitle)}" ${installDisabled ? "disabled" : ""}>${state.updateInstalling ? "Устанавливаем..." : "Установить"}</button>
                </div>
            </div>
            <p>CRM проверяет release-only репозиторий: в GitHub хранится только готовый <strong>STO_CRM.exe</strong>, checksum и <strong>latest.json</strong>. Исходный код туда не загружается. Обновление скачивается с контролем размера и SHA-256, делает резерв текущего exe и перезапускает приложение.</p>
            <div class="update-meta">
                <span class="count-pill">Текущая версия: ${esc(app.version)}</span>
                <a class="count-pill" href="${esc(app.repository_url)}" target="_blank" rel="noopener noreferrer">${esc(app.repository)}</a>
                <span class="count-pill">База не переносится: ${esc(app.db_path)}</span>
            </div>
            ${app.can_install_update ? "" : `<div class="notice"><strong>Вы запустили исходник Python.</strong><p>Автоустановка включается в Windows-сборке STO_CRM.exe. Для исходников обновляйте проект командой <code>git pull --ff-only</code> и перезапускайте Python.</p></div>`}
            ${updateReleaseHtml(status)}
        </section>
    `;
}

async function checkForUpdates(showToast = true) {
    state.updateLoading = true;
    render();
    try {
        state.updateStatus = await api("/api/update/status", {}, 0);
        if (showToast) {
            if (state.updateStatus.ok && state.updateStatus.release?.is_newer) toast(`Доступна версия ${state.updateStatus.release.version || state.updateStatus.release.tag}`);
            else if (state.updateStatus.ok) toast("Установлена актуальная версия");
            else toast(state.updateStatus.error || "Не удалось проверить обновления", "error");
        }
    } finally {
        state.updateLoading = false;
        render();
    }
}

async function installUpdate() {
    if (!state.updateStatus?.release?.is_newer) {
        toast("Новых обновлений нет");
        return;
    }
    if (!confirm("Скачать обновление, закрыть CRM и перезапустить новую версию? Перед установкой будет создана резервная копия текущего exe.")) return;
    state.updateInstalling = true;
    render();
    try {
        const result = await api("/api/update/install", { method: "POST", body: "{}" }, 0);
        toast(result.message || "Обновление запущено");
        document.body.innerHTML = '<main class="shutdown-state"><section class="shutdown-card"><h1>СТО CRM обновляется</h1><p>Приложение закроется, заменит exe и запустится снова. Базу данных обновление не трогает.</p></section></main>';
    } catch (error) {
        state.updateInstalling = false;
        render();
        throw error;
    }
}

function bindViewActions(root) {
    root.querySelectorAll("[data-action]").forEach(button => {
        button.addEventListener("click", event => {
            const action = event.currentTarget.dataset.action;
            const id = Number(event.currentTarget.dataset.id || 0);
            const routeTarget = event.currentTarget.dataset.routeTarget;
            if (routeTarget && routes[routeTarget] && routeTarget !== state.route) {
                setRoute(routeTarget);
            }
            if (action === "retry-load") loadData().catch(showError);
            else if (action === "dismiss-error") {
                state.lastError = "";
                render();
            }
            else if (action === "export-csv") {
                event.preventDefault();
                downloadCsv(event.currentTarget.dataset.export).catch(showError);
            }
            else if (action === "filter-status") {
                state.status = event.currentTarget.dataset.status;
                loadData().catch(showError);
            } else if (action === "new-appointment") openAppointmentModal();
            else if (action === "edit-appointment") openAppointmentModal(findAppointmentById(id));
            else if (action === "new-inspection") openInspectionModal();
            else if (action === "edit-inspection") openInspectionModal(findInspectionById(id));
            else if (action === "new-customer") openCustomerModal();
            else if (action === "edit-customer") openCustomerModal(findCustomerById(id));
            else if (action === "new-vehicle") openVehicleModal();
            else if (action === "edit-vehicle") openVehicleModal(findVehicleById(id));
            else if (action === "open-catalog") setRoute("catalog");
            else if (action === "open-orders") setRoute("orders");
            else if (action === "open-appointments") setRoute("appointments");
            else if (action === "open-inventory") setRoute("inventory");
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
            else if (action === "edit-inventory") openInventoryModal(findInventoryById(id));
            else if (action === "new-order") openOrderModal();
            else if (action === "edit-order") openOrderModal(findOrderById(id));
            else if (action === "duplicate-order") openOrderModal(orderDuplicateDraft(findOrderById(id)));
            else if (action === "print-order") openPrintOrder(id).catch(showError);
            else if (action === "check-update") checkForUpdates(true).catch(showError);
            else if (action === "install-update") installUpdate().catch(showError);
        });
    });
}

function findById(list, id) {
    return list.find(item => Number(item.id) === Number(id));
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

function findInspectionById(id) {
    return findById(state.data?.inspections || [], id) || findById(state.data?.lookups?.inspections || [], id) || null;
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
    if (target instanceof HTMLInputElement) return Boolean(target.getAttribute("list"));
    return false;
}

function focusModalStart() {
    const preferred = $("#modalBody input:not([type='hidden']), #modalBody select, #modalBody textarea, #modalFoot .btn.primary, #modalClose");
    if (preferred instanceof HTMLElement) preferred.focus({ preventScroll: true });
    else $("#modal")?.focus({ preventScroll: true });
}

function setAppInert(isInert) {
    const app = $(".app");
    if (!app) return;
    if (isInert) {
        app.setAttribute("aria-hidden", "true");
        if ("inert" in app) {
            app.inert = true;
            return;
        }
        appTabbableSnapshot = $$('a[href], button, textarea, input, select, [tabindex]', app).map(element => ({
            element,
            tabindex: element.getAttribute("tabindex")
        }));
        appTabbableSnapshot.forEach(({ element }) => element.setAttribute("tabindex", "-1"));
    } else {
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
    lastFocusedElement = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const allowedSizes = new Set(["", "small", "wide"]);
    const modalSize = allowedSizes.has(size) ? size : "";
    $("#modalTitle").textContent = title;
    $("#modalBody").innerHTML = body;
    $("#modalFoot").innerHTML = foot;
    $("#modal").className = modalSize ? `modal ${modalSize}` : "modal";
    $("#modalBackdrop").classList.add("open");
    state.modalDirty = false;
    setAppInert(true);
    bindModalSubmitHandlers();
    requestAnimationFrame(focusModalStart);
}

function closeModal(force = false) {
    if (state.saving && !force) return false;
    if (!force && state.modalDirty && !confirm("Закрыть окно без сохранения изменений?")) return false;
    $("#modalBackdrop").classList.remove("open");
    setAppInert(false);
    $("#modalBody").innerHTML = "";
    $("#modalFoot").innerHTML = "";
    if (lastFocusedElement && document.contains(lastFocusedElement)) {
        lastFocusedElement.focus();
    }
    lastFocusedElement = null;
    state.modalDirty = false;
    return true;
}

function handleModalKeydown(event) {
    const commandPaletteOpen = $("#commandPalette")?.classList.contains("open");
    if ((event.ctrlKey || event.metaKey) && event.key.toLocaleLowerCase("ru-RU") === "k" && !commandPaletteOpen) {
        event.preventDefault();
        if (!$("#modalBackdrop")?.classList.contains("open")) openCommandPalette();
        return;
    }
    if (commandPaletteOpen) {
        if (event.key === "Escape") {
            event.preventDefault();
            closeCommandPalette();
        }
        return;
    }
    const backdrop = $("#modalBackdrop");
    if (!backdrop.classList.contains("open")) return;
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
    const printWindow = window.open("", "_blank");
    if (!printWindow) {
        toast("Разрешите всплывающие окна, чтобы открыть печатную форму.", "error");
        return;
    }
    printWindow.opener = null;
    printWindow.document.write("<p>Загрузка печатной формы...</p>");
    try {
        const response = await fetch(`/print/order/${encodeURIComponent(id)}`, {
            headers: state.data?.app?.csrf_token ? { "X-CSRF-Token": state.data.app.csrf_token } : {},
            cache: "no-store"
        });
        const html = await response.text();
        if (!response.ok) throw new Error(html || "Не удалось открыть печатную форму");
        printWindow.document.open();
        printWindow.document.write(html);
        printWindow.document.close();
    } catch (error) {
        printWindow.close();
        throw error;
    }
}

function markModalDirty() {
    state.modalDirty = true;
}

function setSaveButtonsBusy(isBusy) {
    state.saving = isBusy;
    $("#modalBackdrop")?.classList.toggle("saving", isBusy);
    $$("[data-save]").forEach(button => {
        button.disabled = isBusy;
        button.setAttribute("aria-busy", String(isBusy));
    });
    $("#modalClose")?.toggleAttribute("disabled", isBusy);
}

function collectForm(form) {
    const data = Object.fromEntries(new FormData(form).entries());
    $$('input[type="checkbox"][name]', form).forEach(input => {
        data[input.name] = input.checked ? (input.value || "1") : "0";
    });
    return data;
}

function customerOptions(selected) {
    const customers = state.data.lookups?.customers || state.data.customers;
    const placeholder = customers.length ? "" : `<option value="">Нет клиентов</option>`;
    return placeholder + customers.map(c => `<option value="${esc(c.id)}" ${Number(selected) === Number(c.id) ? "selected" : ""}>${esc(c.name)} · ${esc(c.phone)}</option>`).join("");
}

function vehicleOptions(customerId, selected) {
    const allVehicles = state.data.lookups?.vehicles || state.data.vehicles;
    const vehicles = allVehicles.filter(v => !customerId || Number(v.customer_id) === Number(customerId));
    return `<option value="">Не выбран</option>` + vehicles.map(v => `<option value="${esc(v.id)}" ${Number(selected) === Number(v.id) ? "selected" : ""}>${esc(vehicleName(v))}</option>`).join("");
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

function partAvailability(partId) {
    const inventory = state.data.lookups?.inventory || state.data.inventory;
    const part = findById(inventory, Number(partId));
    return part ? `${qty(part.quantity)} ${esc(part.unit)}` : "неизвестно";
}

function partSourceOptions(item = {}) {
    const inventory = state.data.lookups?.inventory || state.data.inventory;
    const selected = Number(item.inventory_id || 0);
    const outsideSelected = item.kind === "part" && !selected;
    return `<option value="" ${outsideSelected ? "selected" : ""}>Вне склада / заказная</option>` + inventory.map(part => {
        const selectedAttr = selected === Number(part.id) ? "selected" : "";
        return `<option value="${esc(part.id)}" ${selectedAttr}>${esc(part.name)} · ${qty(part.quantity)} ${esc(part.unit)} · ${money(part.price)}</option>`;
    }).join("");
}

function partSourceHint(item = {}) {
    if (item.kind !== "part") return "";
    if (item.inventory_id) return `<div class="source-note">Складская: спишется при закрытии. Доступно: ${partAvailability(item.inventory_id)}</div>`;
    return `<div class="source-note">Вне склада: не влияет на остатки, но попадает в сумму, печать и отчеты.</div>`;
}

function channelOptions(selected = "phone") {
    return Object.entries(channelLabels)
        .map(([key, label]) => `<option value="${esc(key)}" ${(selected || "phone") === key ? "selected" : ""}>${esc(label)}</option>`)
        .join("");
}

function appointmentStatusOptions(selected = "scheduled") {
    const statuses = state.data?.appointment_statuses || appointmentStatusFallback;
    return Object.entries(statuses)
        .map(([key, label]) => `<option value="${esc(key)}" ${(selected || "scheduled") === key ? "selected" : ""}>${esc(label)}</option>`)
        .join("");
}

function inspectionStatusOptions(selected = "draft") {
    const statuses = state.data?.inspection_statuses || inspectionStatusFallback;
    return Object.entries(statuses)
        .map(([key, label]) => `<option value="${esc(key)}" ${(selected || "draft") === key ? "selected" : ""}>${esc(label)}</option>`)
        .join("");
}

function inspectionConditionOptions(selected = "ok") {
    const statuses = state.data?.inspection_conditions || inspectionConditionFallback;
    return Object.entries(statuses)
        .map(([key, label]) => `<option value="${esc(key)}" ${(selected || "ok") === key ? "selected" : ""}>${esc(label)}</option>`)
        .join("");
}

function itemApprovalOptions(selected = "approved") {
    const statuses = state.data?.item_approval_statuses || itemApprovalFallback;
    return Object.entries(statuses)
        .map(([key, label]) => `<option value="${esc(key)}" ${(selected || "approved") === key ? "selected" : ""}>${esc(label)}</option>`)
        .join("");
}

function orderOptions(customerId, vehicleId, selected) {
    const allOrders = state.data.lookups?.orders || state.data.orders || [];
    const orders = allOrders.filter(order => {
        if (customerId && Number(order.customer_id) !== Number(customerId)) return false;
        if (vehicleId && order.vehicle_id && Number(order.vehicle_id) !== Number(vehicleId)) return false;
        return true;
    });
    return `<option value="">Не выбран</option>` + orders.map(order => `<option value="${esc(order.id)}" ${Number(selected) === Number(order.id) ? "selected" : ""}>${esc(order.number)} · ${esc(orderVehicle(order) || order.customer_name)}</option>`).join("");
}

function openAppointmentModal(appointment = {}) {
    const lookupCustomers = state.data.lookups?.customers || state.data.customers;
    if (!lookupCustomers.length) {
        openModal(
            "Новая запись",
            `<div class="notice">В базе нет клиентов для записи.</div>`,
            `<button class="btn" type="button" data-save="cancel">Закрыть</button>`,
            "small"
        );
        return;
    }
    const selectedCustomer = appointment.customer_id || lookupCustomers[0]?.id || "";
    openModal(
        appointment.id ? "Запись клиента" : "Новая запись",
        `<form id="entityForm" class="form-grid">
            ${selectField("appointment", "customer_id", "Клиент", customerOptions(selectedCustomer), "required", "span-2")}
            ${selectField("appointment", "vehicle_id", "Автомобиль", vehicleOptions(selectedCustomer, appointment.vehicle_id), "", "span-2")}
            ${inputField("appointment", "scheduled_at", "Дата и время", `type="datetime-local" value="${inputDateValue(appointment.scheduled_at)}" required`)}
            ${inputField("appointment", "duration_minutes", "Длительность, мин", `type="number" min="15" step="15" value="${esc(appointment.duration_minutes || 60)}"`)}
            ${selectField("appointment", "status", "Статус", appointmentStatusOptions(appointment.status))}
            ${inputField("appointment", "advisor", "Мастер-приемщик", `value="${esc(appointment.advisor || "Администратор")}"`)}
            ${inputField("appointment", "reason", "Причина визита", `value="${esc(appointment.reason)}" placeholder="ТО, диагностика, замена шин"`, "span-2")}
            ${textareaField("appointment", "notes", "Заметки", appointment.notes, "", "span-2")}
        </form>`,
        `${appointment.id ? `<button class="btn danger" type="button" data-save="delete-appointment" data-id="${appointment.id}">Удалить</button>` : ""}
         <button class="btn" type="button" data-save="cancel">Отмена</button>
         <button class="btn primary" type="button" data-save="appointment" data-id="${appointment.id || ""}">Сохранить</button>`,
        "small"
    );
    $("#appointment_customer_id").addEventListener("change", event => {
        $("#appointment_vehicle_id").innerHTML = vehicleOptions(event.target.value, "");
    });
}

const standardInspectionTemplate = [
    { area: "Тормоза", title: "Тормозные колодки и диски", condition_status: "ok", approval_status: "approved", recommendation: "", estimate: 0 },
    { area: "Шины", title: "Протектор и давление шин", condition_status: "ok", approval_status: "approved", recommendation: "", estimate: 0 },
    { area: "Жидкости", title: "Моторное масло, ОЖ, тормозная жидкость", condition_status: "ok", approval_status: "approved", recommendation: "", estimate: 0 },
    { area: "Подвеска", title: "Люфты, сайлентблоки, амортизаторы", condition_status: "ok", approval_status: "approved", recommendation: "", estimate: 0 },
    { area: "Свет", title: "Наружное освещение", condition_status: "ok", approval_status: "approved", recommendation: "", estimate: 0 },
    { area: "АКБ", title: "Состояние аккумулятора", condition_status: "ok", approval_status: "approved", recommendation: "", estimate: 0 }
];

function openInspectionModal(inspection = {}) {
    const lookupCustomers = state.data.lookups?.customers || state.data.customers;
    if (!lookupCustomers.length) {
        openModal(
            "Новый осмотр",
            `<div class="notice">В базе нет клиентов для цифрового осмотра.</div>`,
            `<button class="btn" type="button" data-save="cancel">Закрыть</button>`,
            "small"
        );
        return;
    }
    state.inspectionDraftItems = (inspection.items || standardInspectionTemplate).map(item => ({ ...item }));
    const selectedCustomer = inspection.customer_id || lookupCustomers[0]?.id || "";
    const selectedVehicle = inspection.vehicle_id || "";
    openModal(
        inspection.id ? "Цифровой осмотр DVI" : "Новый цифровой осмотр",
        `<form id="inspectionForm" class="stack">
            <div class="form-grid three">
                ${selectField("inspection", "customer_id", "Клиент", customerOptions(selectedCustomer), "required")}
                ${selectField("inspection", "vehicle_id", "Автомобиль", vehicleOptions(selectedCustomer, selectedVehicle))}
                ${selectField("inspection", "order_id", "Заказ-наряд", orderOptions(selectedCustomer, selectedVehicle, inspection.order_id))}
                ${selectField("inspection", "status", "Статус", inspectionStatusOptions(inspection.status))}
                ${inputField("inspection", "inspector", "Механик", `value="${esc(inspection.inspector || "Механик")}"`)}
                ${inputField("inspection", "inspected_at", "Дата осмотра", `type="datetime-local" value="${inputDateValue(inspection.inspected_at)}"`)}
                ${textareaField("inspection", "summary", "Итог осмотра", inspection.summary, "", "span-3")}
            </div>
            <div class="toolbar">
                <div class="toolbar-left"><strong>Чек-лист DVI</strong></div>
                <div class="toolbar-right">
                    <button class="btn" type="button" id="useInspectionTemplate">Шаблон</button>
                    <button class="btn" type="button" id="addInspectionItem">+ Пункт</button>
                </div>
            </div>
            <div id="inspectionItemsHost"></div>
        </form>`,
        `${inspection.id ? `<button class="btn danger" type="button" data-save="delete-inspection" data-id="${inspection.id}">Удалить</button>` : ""}
         <button class="btn" type="button" data-save="cancel">Отмена</button>
         <button class="btn primary" type="button" data-save="inspection" data-id="${inspection.id || ""}">Сохранить</button>`
    );
    renderInspectionItems();
    $("#inspection_customer_id").addEventListener("change", event => {
        $("#inspection_vehicle_id").innerHTML = vehicleOptions(event.target.value, "");
        $("#inspection_order_id").innerHTML = orderOptions(event.target.value, "", "");
    });
    $("#inspection_vehicle_id").addEventListener("change", event => {
        $("#inspection_order_id").innerHTML = orderOptions($("#inspection_customer_id").value, event.target.value, "");
    });
    $("#addInspectionItem").addEventListener("click", () => {
        state.inspectionDraftItems.push({ area: "", title: "", condition_status: "ok", approval_status: "approved", recommendation: "", estimate: 0 });
        renderInspectionItems();
    });
    $("#useInspectionTemplate").addEventListener("click", () => {
        state.inspectionDraftItems = standardInspectionTemplate.map(item => ({ ...item }));
        renderInspectionItems();
    });
}

function renderInspectionItems() {
    const host = $("#inspectionItemsHost");
    host.innerHTML = `<div class="items-table inspection-items">
        <table aria-label="Пункты цифрового осмотра">
            <thead>${tableHead(["Зона", "Пункт", "Состояние", "Согласование", "Рекомендация", {text: "Оценка", className: "money"}, ""])}</thead>
            <tbody>
                ${state.inspectionDraftItems.map((item, index) => `
                    <tr data-inspection-index="${index}">
                        <td><input data-inspection-item="area" aria-label="Зона осмотра" value="${esc(item.area)}" required></td>
                        <td><input data-inspection-item="title" aria-label="Пункт осмотра" value="${esc(item.title)}" required></td>
                        <td><select data-inspection-item="condition_status" aria-label="Состояние пункта осмотра">${inspectionConditionOptions(item.condition_status)}</select></td>
                        <td><select data-inspection-item="approval_status" aria-label="Статус согласования пункта осмотра">${itemApprovalOptions(item.approval_status)}</select></td>
                        <td><input data-inspection-item="recommendation" aria-label="Рекомендация" value="${esc(item.recommendation)}"></td>
                        <td><input data-inspection-item="estimate" aria-label="Оценка работ" class="money" type="number" inputmode="decimal" step="0.01" min="0" value="${esc(item.estimate || 0)}"></td>
                        <td><button class="btn icon" type="button" data-remove-inspection-item="${index}" title="Удалить" aria-label="Удалить пункт осмотра">×</button></td>
                    </tr>`).join("")}
            </tbody>
        </table>
    </div>`;
    $$("[data-inspection-item]", host).forEach(input => {
        input.addEventListener("input", syncInspectionItemStateOnly);
        input.addEventListener("change", syncInspectionItemStateOnly);
    });
    $$("[data-remove-inspection-item]", host).forEach(button => {
        button.addEventListener("click", event => {
            state.inspectionDraftItems.splice(Number(event.currentTarget.dataset.removeInspectionItem), 1);
            if (!state.inspectionDraftItems.length) state.inspectionDraftItems.push({ area: "", title: "", condition_status: "ok", approval_status: "approved", recommendation: "", estimate: 0 });
            renderInspectionItems();
        });
    });
}

function openCustomerModal(customer = {}) {
    openModal(
        customer.id ? "Клиент" : "Новый клиент",
        `<form id="entityForm" class="form-grid">
            ${inputField("customer", "name", "Имя", `value="${esc(customer.name)}" required`)}
            ${inputField("customer", "phone", "Телефон", `type="tel" value="${esc(customer.phone)}" inputmode="tel" autocomplete="tel" placeholder="+7 900 000-00-00"`)}
            ${inputField("customer", "email", "Email", `type="email" value="${esc(customer.email)}" inputmode="email" autocomplete="email"`)}
            ${inputField("customer", "source", "Источник", `value="${esc(customer.source)}"`)}
            ${selectField("customer", "preferred_channel", "Канал связи", channelOptions(customer.preferred_channel))}
            <label class="check-field" for="customer_reminder_consent"><input id="customer_reminder_consent" type="checkbox" name="reminder_consent" value="1" ${customer.reminder_consent === 0 ? "" : "checked"}> Сервисные напоминания</label>
            ${textareaField("customer", "notes", "Заметки", customer.notes, "", "span-2")}
        </form>`,
        `${customer.id ? `<button class="btn danger" type="button" data-save="delete-customer" data-id="${customer.id}">Удалить</button>` : ""}
         <button class="btn" type="button" data-save="cancel">Отмена</button>
         <button class="btn primary" type="button" data-save="customer" data-id="${customer.id || ""}">Сохранить</button>`,
        "small"
    );
}

function openVehicleModal(vehicle = {}) {
    const makes = state.data?.car_catalog?.makes || [];
    const customers = state.data.lookups?.customers || state.data.customers;
    const hasCustomers = customers.length > 0;
    openModal(
        vehicle.id ? "Автомобиль" : "Новый автомобиль",
        `<form id="entityForm" class="form-grid">
            ${hasCustomers ? "" : `<div class="notice span-2">В базе нет клиентов для привязки автомобиля.</div>`}
            ${selectField("vehicle", "customer_id", "Клиент", customerOptions(vehicle.customer_id), "required", "span-2")}
            ${labeledField("vehicleMake", "Марка", `<input name="make" id="vehicleMake" list="vehicleMakeList" value="${esc(vehicle.make)}"><datalist id="vehicleMakeList">${datalistOptions(makes, vehicle.make)}</datalist>`)}
            ${labeledField("vehicleModel", "Модель", `<input name="model" id="vehicleModel" list="vehicleModelList" value="${esc(vehicle.model)}"><datalist id="vehicleModelList">${datalistOptions(catalogModels(vehicle.make), vehicle.model)}</datalist>`)}
            ${inputField("vehicle", "year", "Год", `type="number" min="1900" max="${new Date().getFullYear() + 1}" value="${esc(vehicle.year || "")}"`)}
            ${inputField("vehicle", "plate", "Госномер", `value="${esc(vehicle.plate)}" autocomplete="off" maxlength="40" autocapitalize="characters" spellcheck="false"`)}
            ${inputField("vehicle", "vin", "VIN", `value="${esc(vehicle.vin)}" maxlength="17" minlength="17" pattern="[A-HJ-NPR-Za-hj-npr-z0-9]{17}" title="VIN должен содержать 17 символов без I, O и Q" autocomplete="off" autocapitalize="characters" spellcheck="false"`)}
            ${inputField("vehicle", "mileage", "Пробег, км", `type="number" inputmode="numeric" step="1" min="0" value="${esc(vehicle.mileage || "")}"`)}
            ${inputField("vehicle", "next_service_at", "Следующий сервис", `type="date" value="${esc(String(vehicle.next_service_at || "").slice(0, 10))}"`)}
            ${inputField("vehicle", "next_service_mileage", "Сервисный пробег", `type="number" inputmode="numeric" step="1" min="0" value="${esc(vehicle.next_service_mileage || "")}"`)}
            ${textareaField("vehicle", "notes", "Заметки", vehicle.notes, "", "span-2")}
        </form>`,
        `${vehicle.id ? `<button class="btn danger" type="button" data-save="delete-vehicle" data-id="${vehicle.id}">Удалить</button>` : ""}
         <button class="btn" type="button" data-save="cancel">Отмена</button>
         <button class="btn primary" type="button" data-save="vehicle" data-id="${vehicle.id || ""}" ${hasCustomers ? "" : "disabled"}>Сохранить</button>`,
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
    openModal(
        part.id ? "Складская позиция" : "Новая складская позиция",
        `<form id="entityForm" class="form-grid">
            ${inputField("inventory", "name", "Название", `value="${esc(part.name)}" required`)}
            ${inputField("inventory", "sku", "Артикул", `value="${esc(part.sku)}"`)}
            ${inputField("inventory", "brand", "Бренд", `value="${esc(part.brand)}"`)}
            ${inputField("inventory", "unit", "Ед.", `value="${esc(part.unit || "шт")}"`)}
            ${inputField("inventory", "quantity", "Остаток", `type="number" inputmode="decimal" step="0.01" min="0" value="${esc(part.quantity || 0)}"`)}
            ${inputField("inventory", "min_quantity", "Минимум", `type="number" inputmode="decimal" step="0.01" min="0" value="${esc(part.min_quantity || 0)}"`)}
            ${inputField("inventory", "price", "Цена", `type="number" inputmode="decimal" step="0.01" min="0" value="${esc(part.price || 0)}"`)}
            ${inputField("inventory", "cost", "Себестоимость", `type="number" inputmode="decimal" step="0.01" min="0" value="${esc(part.cost || 0)}"`)}
            ${inputField("inventory", "supplier", "Поставщик", `value="${esc(part.supplier)}"`, "span-2")}
            ${textareaField("inventory", "notes", "Заметки", part.notes, "", "span-2")}
        </form>`,
        `${part.id ? `<button class="btn danger" type="button" data-save="delete-inventory" data-id="${part.id}">Удалить</button>` : ""}
         <button class="btn" type="button" data-save="cancel">Отмена</button>
         <button class="btn primary" type="button" data-save="inventory" data-id="${part.id || ""}">Сохранить</button>`,
        "small"
    );
}

function openOrderModal(order = {}) {
    if (!order) {
        toast("Заказ не найден в текущей выборке. Очистите поиск или обновите данные.", "error");
        return;
    }
    state.orderDraftItems = (order.items || [{ kind: "service", title: "", approval_status: "approved", quantity: 1, unit_price: 0, unit_cost: 0 }])
        .map(item => ({ approval_status: "approved", inventory_id: "", ...item }));
    const lookupCustomers = state.data.lookups?.customers || state.data.customers;
    if (!lookupCustomers.length) {
        openModal(
            "Новый заказ-наряд",
            `<div class="notice">В базе нет клиентов для оформления заказ-наряда.</div>`,
            `<button class="btn" type="button" data-save="cancel">Закрыть</button>`,
            "small"
        );
        return;
    }
    const selectedCustomer = order.customer_id || lookupCustomers[0]?.id || "";
    openModal(
        order.id ? `Заказ-наряд ${order.number}` : "Новый заказ-наряд",
        `<form id="orderForm" class="stack">
            <div class="form-grid three">
                ${selectField("order", "customer_id", "Клиент", customerOptions(selectedCustomer), "required")}
                ${selectField("order", "vehicle_id", "Автомобиль", vehicleOptions(selectedCustomer, order.vehicle_id))}
                ${selectField("order", "status", "Статус", Object.entries(state.data.statuses).map(([key, label]) => `<option value="${esc(key)}" ${order.status === key ? "selected" : ""}>${esc(label)}</option>`).join(""))}
                ${selectField("order", "priority", "Приоритет", Object.entries(state.data.priorities || priorityLabels).map(([key, label]) => `<option value="${esc(key)}" ${(order.priority || "normal") === key ? "selected" : ""}>${esc(label)}</option>`).join(""))}
                ${inputField("order", "advisor", "Мастер-приемщик", `value="${esc(order.advisor || "Администратор")}"`)}
                ${inputField("order", "mechanic", "Механик", `value="${esc(order.mechanic)}"`)}
                ${inputField("order", "promised_at", "Срок", `type="datetime-local" value="${inputDateValue(order.promised_at)}"`)}
                ${inputField("order", "odometer", "Пробег", `type="number" inputmode="numeric" step="1" min="0" value="${esc(order.odometer || "")}"`)}
                ${inputField("order", "paid", "Оплачено", `type="number" inputmode="decimal" step="0.01" min="0" value="${esc(order.paid || 0)}"`)}
                ${inputField("order", "discount", "Скидка", `type="number" inputmode="decimal" step="0.01" min="0" value="${esc(order.discount || 0)}"`)}
                ${inputField("order", "tax_rate", "Налог, %", `type="number" inputmode="decimal" step="0.01" min="0" max="100" value="${esc(order.tax_rate || 0)}"`)}
                ${inputField("order", "payment_method", "Оплата", `value="${esc(order.payment_method)}"`)}
                ${inputField("order", "authorized_by", "Согласовал", `value="${esc(order.authorized_by)}"`)}
                ${inputField("order", "authorized_at", "Дата согласования", `type="datetime-local" value="${inputDateValue(order.authorized_at)}"`)}
                ${inputField("order", "follow_up_at", "Follow-up", `type="datetime-local" value="${inputDateValue(order.follow_up_at)}"`)}
                ${textareaField("order", "complaint", "Жалоба клиента", order.complaint, "", "span-3")}
                ${textareaField("order", "diagnosis", "Диагностика", order.diagnosis, "", "span-3")}
                ${textareaField("order", "recommendations", "Рекомендации", order.recommendations, "", "span-3")}
            </div>
            <div class="toolbar">
                <div class="toolbar-left"><strong>Работы и запчасти</strong></div>
                <div class="toolbar-right">
                    <button class="btn" type="button" id="addService">+ Работа</button>
                    <button class="btn" type="button" id="addPart">+ Запчасть</button>
                </div>
            </div>
            <div class="notice">Запчасть можно выбрать со склада или указать вручную как «вне склада» — такие позиции не списывают остатки, но учитываются в сумме заказ-наряда.</div>
            <div id="itemsHost"></div>
        </form>`,
        `${order.id ? `<button class="btn danger" type="button" data-save="delete-order" data-id="${order.id}">Удалить</button>` : ""}
         ${order.id ? `<button class="btn ghost" type="button" data-save="print-order" data-id="${order.id}">Печать</button>` : ""}
         <button class="btn" type="button" data-save="cancel">Отмена</button>
         <button class="btn primary" type="button" data-save="order" data-id="${order.id || ""}">Сохранить</button>`
    );
    renderOrderItems();
    $("#order_customer_id").addEventListener("change", event => {
        $("#order_vehicle_id").innerHTML = vehicleOptions(event.target.value, "");
    });
    $("#addService").addEventListener("click", () => {
        state.orderDraftItems.push({ kind: "service", title: "", approval_status: "approved", quantity: 1, unit_price: 0, unit_cost: 0 });
        renderOrderItems();
    });
    $("#addPart").addEventListener("click", () => {
        state.orderDraftItems.push({ kind: "part", inventory_id: "", title: "", approval_status: "approved", quantity: 1, unit_price: 0, unit_cost: 0 });
        renderOrderItems();
    });
    ['discount', 'tax_rate', 'paid'].forEach(name => {
        const input = document.querySelector(`[name="${name}"]`);
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
                        <td><select data-item="kind" aria-label="Тип позиции">
                            <option value="service" ${item.kind === "service" ? "selected" : ""}>Работа</option>
                            <option value="part" ${item.kind === "part" ? "selected" : ""}>Запчасть</option>
                        </select></td>
                        <td><select class="source-select" data-item="inventory_id" aria-label="Источник запчасти" ${item.kind !== "part" ? "disabled" : ""}>${partSourceOptions(item)}</select>${partSourceHint(item)}</td>
                        <td><input data-item="title" aria-label="Наименование позиции" value="${esc(item.title)}" required></td>
                        <td><select data-item="approval_status" aria-label="Статус согласования позиции">${itemApprovalOptions(item.approval_status)}</select></td>
                        <td><input data-item="quantity" aria-label="Количество" type="number" inputmode="decimal" step="0.01" min="0" value="${esc(item.quantity || 1)}"></td>
                        <td><input data-item="unit_price" aria-label="Цена" type="number" inputmode="decimal" step="0.01" min="0" value="${esc(item.unit_price || 0)}"></td>
                        <td><input data-item="unit_cost" aria-label="Себестоимость" type="number" inputmode="decimal" step="0.01" min="0" value="${esc(item.unit_cost || 0)}"></td>
                        <td class="money" data-row-total>${money((item.approval_status || "approved") === "approved" ? num(item.quantity) * num(item.unit_price) : 0)}</td>
                        <td><button class="btn icon" type="button" data-remove-item="${index}" title="Удалить" aria-label="Удалить позицию заказ-наряда">×</button></td>
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
            state.orderDraftItems.splice(Number(event.currentTarget.dataset.removeItem), 1);
            if (!state.orderDraftItems.length) state.orderDraftItems.push({ kind: "service", title: "", approval_status: "approved", quantity: 1, unit_price: 0, unit_cost: 0 });
            renderOrderItems();
        });
    });
}

function syncOrderItemsFromDom(event) {
    const row = event.target.closest("tr[data-index]");
    if (!row) return;
    const index = Number(row.dataset.index);
    const item = state.orderDraftItems[index];
    $$("[data-item]", row).forEach(input => {
        item[input.dataset.item] = input.value;
    });
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
    renderOrderItems();
}

function orderTotalsHtml() {
    const approved = state.orderDraftItems.filter(i => (i.approval_status || "approved") === "approved");
    const service = approved.filter(i => i.kind === "service").reduce((sum, i) => sum + num(i.quantity) * num(i.unit_price), 0);
    const parts = approved.filter(i => i.kind === "part").reduce((sum, i) => sum + num(i.quantity) * num(i.unit_price), 0);
    const deferred = state.orderDraftItems.filter(i => (i.approval_status || "approved") !== "approved")
        .reduce((sum, i) => sum + num(i.quantity) * num(i.unit_price), 0);
    const subtotal = service + parts;
    const discountPreview = Math.min(num(document.querySelector('[name="discount"]')?.value, 0), subtotal);
    const taxPreview = Math.max(0, subtotal - discountPreview) * Math.min(Math.max(num(document.querySelector('[name="tax_rate"]')?.value, 0), 0), 100) / 100;
    const paidPreview = Math.min(num(document.querySelector('[name="paid"]')?.value, 0), Math.max(0, subtotal - discountPreview) + taxPreview);
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

async function saveEntity(kind, id) {
    const form = $("#entityForm");
    if (form && !form.reportValidity()) return;
    const data = collectForm(form);
    const path = id ? `/api/${kind}/${id}` : `/api/${kind}`;
    const method = id ? "PUT" : "POST";
    setSaveButtonsBusy(true);
    try {
        await api(path, { method, body: JSON.stringify(data) });
        setSaveButtonsBusy(false);
        closeModal(true);
        await loadData();
        toast("Сохранено");
    } finally {
        if (state.saving) setSaveButtonsBusy(false);
    }
}

async function saveOrder(id) {
    const form = $("#orderForm");
    if (form && !form.reportValidity()) return;
    const data = collectForm(form);
    syncAllOrderItems();
    data.items = state.orderDraftItems.map(item => ({
        kind: item.kind,
        inventory_id: item.kind === "part" && num(item.inventory_id, 0) > 0 ? num(item.inventory_id, 0) : null,
        title: item.title,
        approval_status: item.approval_status || "approved",
        quantity: num(item.quantity, 0),
        unit_price: num(item.unit_price, 0),
        unit_cost: num(item.unit_cost, 0)
    }));
    const path = id ? `/api/orders/${id}` : "/api/orders";
    const method = id ? "PUT" : "POST";
    setSaveButtonsBusy(true);
    try {
        await api(path, { method, body: JSON.stringify(data) });
        setSaveButtonsBusy(false);
        closeModal(true);
        await loadData();
        toast("Заказ-наряд сохранен");
    } finally {
        if (state.saving) setSaveButtonsBusy(false);
    }
}

async function saveInspection(id) {
    const form = $("#inspectionForm");
    if (form && !form.reportValidity()) return;
    const data = collectForm(form);
    syncAllInspectionItems();
    data.items = state.inspectionDraftItems.map(item => ({
        area: item.area,
        title: item.title,
        condition_status: item.condition_status || "ok",
        approval_status: item.approval_status || ((item.condition_status || "ok") === "ok" ? "approved" : "deferred"),
        recommendation: item.recommendation,
        estimate: num(item.estimate, 0)
    }));
    const path = id ? `/api/inspections/${id}` : "/api/inspections";
    const method = id ? "PUT" : "POST";
    setSaveButtonsBusy(true);
    try {
        await api(path, { method, body: JSON.stringify(data) });
        setSaveButtonsBusy(false);
        closeModal(true);
        await loadData();
        toast("Осмотр сохранен");
    } finally {
        if (state.saving) setSaveButtonsBusy(false);
    }
}

function syncAllOrderItems() {
    $$("#itemsHost tr[data-index]").forEach(row => {
        const index = Number(row.dataset.index);
        const item = state.orderDraftItems[index];
        $$("[data-item]", row).forEach(input => {
            item[input.dataset.item] = input.value;
        });
    });
}

function syncAllInspectionItems() {
    $$("#inspectionItemsHost tr[data-inspection-index]").forEach(row => {
        const index = Number(row.dataset.inspectionIndex);
        const item = state.inspectionDraftItems[index];
        $$("[data-inspection-item]", row).forEach(input => {
            item[input.dataset.inspectionItem] = input.value;
        });
    });
}

function syncInspectionItemStateOnly(event) {
    const row = event.target.closest("tr[data-inspection-index]");
    if (!row) return;
    const index = Number(row.dataset.inspectionIndex);
    const item = state.inspectionDraftItems[index];
    $$("[data-inspection-item]", row).forEach(input => {
        item[input.dataset.inspectionItem] = input.value;
    });
    if (event.target.dataset.inspectionItem === "condition_status") {
        if (item.condition_status === "ok") {
            item.approval_status = "approved";
        }
        renderInspectionItems();
    }
}

function syncOrderItemStateOnly(event) {
    const row = event.target.closest("tr[data-index]");
    if (!row) return;
    const index = Number(row.dataset.index);
    const item = state.orderDraftItems[index];
    $$("[data-item]", row).forEach(input => {
        item[input.dataset.item] = input.value;
    });
    const totalCell = $("[data-row-total]", row);
    if (totalCell) totalCell.textContent = money((item.approval_status || "approved") === "approved" ? num(item.quantity) * num(item.unit_price) : 0);
    const totals = $("#orderTotals");
    if (totals) totals.outerHTML = orderTotalsHtml();
}

async function deleteEntity(kind, id) {
    if (state.saving) return;
    if (!confirm("Удалить запись? Это действие скроет запись из активной базы CRM.")) return;
    setSaveButtonsBusy(true);
    try {
        await api(`/api/${kind}/${id}`, { method: "DELETE" });
        setSaveButtonsBusy(false);
        closeModal(true);
        await loadData();
        toast("Удалено");
    } finally {
        if (state.saving) setSaveButtonsBusy(false);
    }
}

function showError(error) {
    if (error?.name === "AbortError") return;
    const status = Number(error?.status || 0);
    if (!status || status >= 500) setOnlineState(false);
    const message = error.message || String(error);
    state.lastError = message;
    applyFormError(error);
    const modalOpen = $("#modalBackdrop")?.classList.contains("open");
    if (!state.data) {
        if (!restoreCachedBootstrap()) {
            const content = $("#content");
            content.innerHTML = `${offlineBannerHtml()}<div class="notice" role="alert"><strong>Не удалось загрузить данные.</strong><p>${esc(message)}</p><button class="btn primary" type="button" data-action="retry-load">Повторить</button></div>`;
            bindViewActions(content);
        }
    } else if (!modalOpen) {
        render();
    }
    toast(message, "error");
}

document.addEventListener("click", event => {
    const navButton = event.target.closest("#nav button[data-route]");
    if (navButton) setRoute(navButton.dataset.route);

    const saveButton = event.target.closest("[data-save]");
    if (!saveButton) return;
    const action = saveButton.dataset.save;
    const id = Number(saveButton.dataset.id || 0);
    if (state.saving) return;
    if (action === "cancel") closeModal();
    else if (action === "appointment") saveEntity("appointments", id).catch(showError);
    else if (action === "inspection") saveInspection(id).catch(showError);
    else if (action === "customer") saveEntity("customers", id).catch(showError);
    else if (action === "vehicle") saveEntity("vehicles", id).catch(showError);
    else if (action === "inventory") saveEntity("inventory", id).catch(showError);
    else if (action === "order") saveOrder(id).catch(showError);
    else if (action === "delete-customer") deleteEntity("customers", id).catch(showError);
    else if (action === "delete-vehicle") deleteEntity("vehicles", id).catch(showError);
    else if (action === "delete-inventory") deleteEntity("inventory", id).catch(showError);
    else if (action === "delete-appointment") deleteEntity("appointments", id).catch(showError);
    else if (action === "delete-inspection") deleteEntity("inspections", id).catch(showError);
    else if (action === "delete-order") deleteEntity("orders", id).catch(showError);
    else if (action === "print-order") openPrintOrder(id).catch(showError);
});

const modalCloseButton = $("#modalClose");
modalCloseButton.addEventListener("click", () => closeModal());
document.addEventListener("keydown", handleModalKeydown);
$("#modalBackdrop").addEventListener("click", event => {
    if (event.target.id === "modalBackdrop") closeModal();
});
$("#globalSearch").addEventListener("input", event => {
    state.q = event.target.value;
    updateSearchClear();
    clearTimeout(state.searchTimer);
    state.searchTimer = setTimeout(() => loadData().catch(showError), 260);
});
$("#globalSearch").addEventListener("keydown", event => {
    if (event.key === "Escape" && state.q) {
        event.preventDefault();
        clearGlobalSearch();
    }
});
$("#clearSearch").addEventListener("click", clearGlobalSearch);
window.addEventListener("offline", () => {
    setOnlineState(false);
    announce("Браузер сообщает, что сеть недоступна. Работаем с последними загруженными данными.", true);
});
window.addEventListener("online", () => {
    setOnlineState(true);
    loadData().then(() => toast("Соединение восстановлено")).catch(showError);
});
$("#refreshBtn").addEventListener("click", () => loadData().then(() => toast("Обновлено")).catch(showError));
$("#backupBtn").addEventListener("click", createBackupFromUi);
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
async function shutdownApp() {
    if (!confirm("Остановить локальное приложение СТО CRM?")) return;
    try {
        await api("/api/shutdown", { method: "POST", body: "{}" });
        document.body.innerHTML = '<main class="shutdown-state"><section class="shutdown-card"><h1>СТО CRM остановлена</h1><p>Локальный сервер завершает работу. Окно можно закрыть.</p></section></main>';
    } catch (error) {
        toast(error.message || String(error), "error");
    }
}
$("#shutdownBtn").addEventListener("click", () => shutdownApp());

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
        themeButton.textContent = requested === "auto" ? "◐" : (isDark ? "◑" : "☼");
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
        densityButton.textContent = state.compactMode ? "↧" : "↕";
        densityButton.setAttribute("aria-pressed", state.compactMode ? "true" : "false");
        densityButton.setAttribute("aria-label", state.compactMode ? "Компактный режим включен. Нажмите для комфортного режима." : "Комфортный режим включен. Нажмите для компактного режима.");
        densityButton.title = state.compactMode ? "Компактный режим" : "Комфортный режим";
    }
}

function toggleDensity() {
    applyDensity(!state.compactMode);
    safeStorageSet("sto-crm-density", state.compactMode ? "compact" : null);
    toast(state.compactMode ? "Компактная плотность включена" : "Комфортная плотность включена");
}

function safeStorageGet(key) {
    try { return window.localStorage ? localStorage.getItem(key) : null; }
    catch (_error) { return null; }
}

function safeStorageSet(key, value) {
    try {
        if (!window.localStorage) return;
        if (value === null || value === "") localStorage.removeItem(key);
        else localStorage.setItem(key, value);
    }
    catch (_error) { /* storage can be disabled in private or locked-down modes */ }
}

function nextThemePreference(current) {
    const normalized = current === "dark" || current === "light" ? current : "auto";
    if (normalized === "auto") return "light";
    if (normalized === "light") return "dark";
    return "auto";
}

applyTheme(safeStorageGet("sto-crm-theme") || "auto");
applyDensity(safeStorageGet("sto-crm-density") === "compact");
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

window.addEventListener("popstate", () => setRoute(routeFromLocation(), false));
window.addEventListener("hashchange", () => setRoute(routeFromLocation(), false));
setRoute(state.route, false);
loadData().catch(showError);
