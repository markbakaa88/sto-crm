// === Module: core/storage.js ===
// Safe wrapper around LocalStorage and IndexedDB offline cache helpers.

"use strict";

class SafeLocalStorage {
    constructor() {
        this.fallbackStore = new Map();
        this.isAvailable = this._checkAvailability();
    }

    _checkAvailability() {
        try {
            if (typeof window === "undefined" || !window.localStorage) return false;
            const testKey = "__sto_crm_storage_test__";
            window.localStorage.setItem(testKey, testKey);
            window.localStorage.removeItem(testKey);
            return true;
        } catch {
            return false;
        }
    }

    getItem(key) {
        if (!this.isAvailable) {
            return this.fallbackStore.has(key) ? this.fallbackStore.get(key) : null;
        }
        try {
            const val = window.localStorage.getItem(key);
            if (val !== null) return val;
            return this.fallbackStore.has(key) ? this.fallbackStore.get(key) : null;
        } catch (e) {
            console.error(`SafeLocalStorage: failed to get item for key "${key}"`, e);
            return this.fallbackStore.has(key) ? this.fallbackStore.get(key) : null;
        }
    }

    setItem(key, value) {
        const strValue = String(value);
        if (!this.isAvailable) {
            this.fallbackStore.set(key, strValue);
            return false;
        }
        try {
            window.localStorage.setItem(key, strValue);
            return true;
        } catch (e) {
            console.error(`SafeLocalStorage: failed to set item for key "${key}"`, e);
            const isQuotaError = e.name === "QuotaExceededError" ||
                                  e.name === "NS_ERROR_DOM_QUOTA_REACHED" ||
                                  e.code === 22 ||
                                  e.code === 1014;
            if (isQuotaError) {
                console.warn("SafeLocalStorage: LocalStorage quota exceeded. Freeing up space by removing bootstrap cache...");
                try {
                    window.localStorage.removeItem("sto-crm-bootstrap");
                    window.localStorage.setItem(key, strValue);
                    return true;
                } catch (retryError) {
                    console.error("SafeLocalStorage: Failed to set item even after clearing bootstrap cache", retryError);
                }
                if (typeof toast === "function") {
                    toast("Ошибка сохранения: недостаточно места в localStorage", "danger");
                }
            }
            this.fallbackStore.set(key, strValue);
            return false;
        }
    }

    removeItem(key) {
        this.fallbackStore.delete(key);
        if (!this.isAvailable) return;
        try {
            window.localStorage.removeItem(key);
        } catch (e) {
            console.error(`SafeLocalStorage: failed to remove item for key "${key}"`, e);
        }
    }

    clear() {
        this.fallbackStore.clear();
        if (!this.isAvailable) return;
        try {
            window.localStorage.clear();
        } catch (e) {
            console.error("SafeLocalStorage: failed to clear localStorage", e);
        }
    }
}
const safeLocalStorage = new SafeLocalStorage();

// Simple shortcuts maintaining contract
function safeStorageGet(key) {
    return safeLocalStorage.getItem(key);
}
function safeStorageSet(key, value) {
    return safeLocalStorage.setItem(key, value);
}

const DB_NAME = "sto-crm-db";
const STORE_NAME = "cache";

function getIndexedDB() {
    return new Promise((resolve) => {
        if (!window.indexedDB) {
            resolve(null);
            return;
        }
        try {
            const request = indexedDB.open(DB_NAME, 1);
            request.onupgradeneeded = event => {
                const db = event.target.result;
                if (!db.objectStoreNames.contains(STORE_NAME)) {
                    db.createObjectStore(STORE_NAME);
                }
            };
            request.onsuccess = event => {
                resolve(event.target.result);
            };
            request.onerror = () => {
                resolve(null);
            };
        } catch {
            resolve(null);
        }
    });
}

function idbGet(key) {
    return new Promise(resolve => {
        getIndexedDB().then(db => {
            if (!db) {
                resolve(null);
                return;
            }
            try {
                const transaction = db.transaction(STORE_NAME, "readonly");
                const store = transaction.objectStore(STORE_NAME);
                const request = store.get(key);
                request.onsuccess = () => resolve(request.result);
                request.onerror = () => resolve(null);
            } catch {
                resolve(null);
            }
        }).catch(() => resolve(null));
    });
}

function idbSet(key, value) {
    return new Promise(resolve => {
        getIndexedDB().then(db => {
            if (!db) {
                resolve(false);
                return;
            }
            try {
                const transaction = db.transaction(STORE_NAME, "readwrite");
                const store = transaction.objectStore(STORE_NAME);
                const request = store.put(value, key);
                request.onsuccess = () => resolve(true);
                request.onerror = () => resolve(false);
            } catch {
                resolve(false);
            }
        }).catch(() => resolve(false));
    });
}

function idbDel(key) {
    return new Promise(resolve => {
        getIndexedDB().then(db => {
            if (!db) {
                resolve(false);
                return;
            }
            try {
                const transaction = db.transaction(STORE_NAME, "readwrite");
                const store = transaction.objectStore(STORE_NAME);
                const request = store.delete(key);
                request.onsuccess = () => resolve(true);
                request.onerror = () => resolve(false);
            } catch {
                resolve(false);
            }
        }).catch(() => resolve(false));
    });
}

async function dbGet(key) {
    let raw = await idbGet(key);
    if (!raw) {
        try {
            raw = safeLocalStorage.getItem(key);
            if (raw) return JSON.parse(raw);
        } catch {
            return null;
        }
    }
    return raw;
}

async function dbSet(key, value) {
    let ok = await idbSet(key, value);
    if (!ok) {
        try {
            safeLocalStorage.setItem(key, JSON.stringify(value));
        } catch {
            // storage disabled
        }
    }
}

async function dbDel(key) {
    await idbDel(key);
    try {
        safeLocalStorage.removeItem(key);
    } catch {
        // storage disabled
    }
}

async function cacheBootstrap(data, loadedAt = new Date().toISOString(), query = {}) {
    try {
        const q = String(query.q || "");
        const status = String(query.status || "all");
        const route = String(query.route || state.route || "dashboard");
        if (q || status !== "all") {
            await clearCachedBootstrap();
            return;
        }
        const cached = JSON.parse(JSON.stringify(data || {}));
        if (cached.app) {
            delete cached.app.csrf_token;
            delete cached.app.access_token;
        }
        const payload = {
            schemaVersion: BOOTSTRAP_CACHE_SCHEMA_VERSION,
            cachedAt: Date.now(),
            loadedAt,
            appVersion: cached.app?.version || "",
            dbPath: cached.app?.db_path || "",
            query: { q, status, route },
            data: cached
        };
        await dbSet(BOOTSTRAP_CACHE_KEY, payload);
    } catch (e) {
        console.error(e);
    }
}

async function clearCachedBootstrap() {
    try {
        await dbDel(BOOTSTRAP_CACHE_KEY);
    } catch (e) {
        console.error(e);
    }
}

async function readCachedBootstrap() {
    try {
        const parsed = await dbGet(BOOTSTRAP_CACHE_KEY);
        if (!parsed) return null;
        if (parsed?.data && typeof parsed.data === "object") {
            if (parsed.schemaVersion !== BOOTSTRAP_CACHE_SCHEMA_VERSION) {
                await clearCachedBootstrap();
                return null;
            }
            const query = parsed.query || {};
            if (String(query.q || "") || String(query.status || "all") !== "all") {
                await clearCachedBootstrap();
                return null;
            }
            const cachedAt = Number(parsed.cachedAt || 0);
            if (!Number.isFinite(cachedAt) || Date.now() - cachedAt > BOOTSTRAP_CACHE_TTL_MS) {
                await clearCachedBootstrap();
                return null;
            }
            return parsed;
        }
        if (parsed?.app) {
            await clearCachedBootstrap();
            return null;
        }
    } catch (e) {
        console.error(e);
        await clearCachedBootstrap();
    }
    return null;
}
