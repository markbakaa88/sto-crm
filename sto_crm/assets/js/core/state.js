// === Module: core/state.js ===
// Holds the core UI state, enum translations, and state transitions.

"use strict";

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
    backupBusy: false,
    orderDraftItems: [],
    orderDraftReadOnly: false,
    bootstrapAbortController: null,
    modalDirty: false,
    saving: false,
    loading: false,
    lastLoadedAt: "",
    offlineMode: false,
    accessToken: "",
    compactMode: false,
    audioFeedback: true,
    searchTimer: null,
    catalogSearchTimer: null,
    lastBackupAt: "",
    customerPage: 1,
    customerPageSize: 50,
    catalogLimit: 60,
    orderPage: 1,
    orderPageSize: 50,
    inventoryPage: 1,
    inventoryPageSize: 50,
    orderDraftItemsPage: 1,
    orderDraftItemsPageSize: 15,
    expandedMakes: {},
    routeScrollPositions: {},
    sort: {
        appointments: { key: "", dir: "" },
        orders: { key: "", dir: "" },
        customers: { key: "id", dir: "desc" },
        vehicles: { key: "", dir: "" },
        inventory: { key: "", dir: "" }
    }
};

const routes = {
    dashboard: "Панель",
    appointments: "Запись",
    orders: "Заказы",
    customers: "Клиенты",
    vehicles: "Автомобили",
    catalog: "Каталог авто",
    inventory: "Склад",
    reports: "Отчёты",
    updates: "Обновления"
};

const routeSubtitles = {
    dashboard: "Сводка смены",
    appointments: "Визиты и приёмка",
    orders: "Заказы, сроки и оплаты",
    customers: "Контакты и история",
    vehicles: "Авто, VIN и сервисный план",
    catalog: "Марки и модели",
    inventory: "Остатки и закупка",
    reports: "Финансы и риски",
    updates: "Релизы и установка"
};

function initialBootstrapToken() {
    try {
        const token = document.body?.dataset?.bootstrapToken || "";
        if (document.body?.dataset) {
            delete document.body.dataset.bootstrapToken;
        }
        return token;
    } catch {
        return "";
    }
}

state.bootstrapToken = initialBootstrapToken();

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

// Global system constants
const BOOTSTRAP_CACHE_KEY = "sto-crm-bootstrap";
const BOOTSTRAP_CACHE_SCHEMA_VERSION = 2;
const BOOTSTRAP_CACHE_TTL_MS = 30 * 60 * 1000;
const MAX_ORDER_ITEMS = 200;
const EXPORT_ENTITIES = new Set(["appointments", "orders", "customers", "vehicles", "inventory", "catalog"]);
const ENTITY_COLLECTION_PATHS = Object.freeze({
    appointments: "/api/appointments",
    customers: "/api/customers",
    vehicles: "/api/vehicles",
    inventory: "/api/inventory",
    orders: "/api/orders"
});
const BUTTON_STYLE_CLASSES = new Set(["primary", "ghost", "danger"]);
