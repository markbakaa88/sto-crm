// === Module: core/routing.js ===
// Handles layout state transitions, loading animation triggers, routing logic, and DOM render coordination.

"use strict";

const requestedRoute = new URLSearchParams(location.search).get("route") || location.hash.replace("#", "");
if (requestedRoute && routes[requestedRoute]) {
    state.route = requestedRoute;
}

function routeFromLocation() {
    const params = new URLSearchParams(location.search);
    const requested = params.get("route") || location.hash.replace("#", "");
    return routes[requested] ? requested : "dashboard";
}
const currentRouteFromLocation = routeFromLocation;

function prefersReducedMotion() {
    return window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function setLoadingState(isLoading) {
    state.loading = isLoading;
    const content = $("#content");
    if (content) content.setAttribute("aria-busy", String(isLoading));
    $("#refreshBtn")?.toggleAttribute("disabled", isLoading);
    const progress = $("#appProgress");
    if (progress) {
        progress.classList.toggle("is-active", Boolean(isLoading));
        progress.setAttribute("aria-hidden", "true");
    }
    const syncChip = $("#syncChip");
    if (syncChip && isLoading) syncChip.dataset.state = "syncing";
    renderShell();
    if (isLoading) {
        const routeName = routes[state.route] || "раздела";
        announce(`Загрузка раздела ${routeName}...`, false);
    }
    render();
}

function setRoute(route, updateUrl = true) {
    if (!routes[route]) return;
    closeTransientPanels();
    const previousRoute = state.route;
    const sameRoute = previousRoute === route;
    if (previousRoute && !sameRoute) {
        state.routeScrollPositions[previousRoute] = window.scrollY;
    }
    const hasOrderFilter = state.status !== "all" && !state.offlineMode;
    const leavingFilteredOrders = hasOrderFilter && route !== "orders" && previousRoute === "orders";
    const enteringFilteredOrders = hasOrderFilter && route === "orders" && previousRoute !== "orders";
    const needsRouteFilterReload = enteringFilteredOrders || leavingFilteredOrders;
    if (leavingFilteredOrders) state.status = "all";
    state.route = route;
    if (route === "catalog") {
        state.catalogLimit = 60;
        state.expandedMakes = {};
    }
    if (route === "orders") {
        state.orderPage = 1;
    }
    if (route === "inventory") {
        state.inventoryPage = 1;
    }
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
        const savedScroll = state.routeScrollPositions[route];
        if (savedScroll !== undefined) {
            window.scrollTo(0, savedScroll);
        } else {
            const content = $("#content");
            content?.scrollIntoView({ behavior: prefersReducedMotion() ? "auto" : "smooth", block: "start" });
        }
        const content = $("#content");
        content?.focus({ preventScroll: true });
        announce(`Открыт раздел ${routes[route]}.`);
    }
}

async function loadData() {
    const seq = ++state.loadSeq;
    if (state.bootstrapAbortController) state.bootstrapAbortController.abort();
    const controller = new AbortController();
    state.bootstrapAbortController = controller;

    let localData = null;
    try {
        const cached = await readCachedBootstrap();
        if (cached?.data) {
            localData = cached.data;
        }
    } catch (e) {
        console.error("Failed to read cached data for reconciliation:", e);
    }

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

        if (state.offlineMode && localData) {
            try {
                await reconcileDataVersions(localData, data);
            } catch (reconError) {
                console.error("Reconciliation error:", reconError);
            }
        }

        state.data = data;
        if (data.app?.access_token) state.accessToken = data.app.access_token;
        state.bootstrapToken = "";
        state.lastLoadedAt = loadedAt;
        state.offlineMode = false;
        await cacheBootstrap(data, loadedAt, { q: state.q, status: requestStatus, route: state.route });
        state.lastError = "";
        setOnlineState(true);
        const dbPath = $("#dbPath");
        if (dbPath) {
            dbPath.textContent = `База: ${state.data.app.db_path}`;
            dbPath.title = state.data.app.db_directory ? `Папка базы: ${state.data.app.db_directory}` : "";
        }
        if (seq === state.loadSeq) setLoadingState(false);
        updateSearchClear();
        announce(`Данные обновлены. Раздел: ${routes[state.route]}.`);
    } catch (error) {
        if (error?.name === "AbortError") return;
        throw error;
    } finally {
        if (state.bootstrapAbortController === controller) state.bootstrapAbortController = null;
        if (seq === state.loadSeq && state.loading) setLoadingState(false);
    }
}

function render() {
    const mainEl = document.querySelector('main');
    // Restart animation on route change by class swap (CSP compliant)
    if (mainEl) {
        mainEl.classList.remove('rendered');
        mainEl.offsetHeight; /* trigger reflow */
        mainEl.classList.add('rendered');
    }
    if (!state.data && !state.loading) return;
    const content = $("#content");
    if (!content) return;

    let bannersWrapper = content.querySelector(".banners-wrapper");
    let viewsWrapper = content.querySelector(".views-wrapper");
    if (!bannersWrapper || !viewsWrapper) {
        content.innerHTML = `<div class="banners-wrapper"></div><div class="views-wrapper"></div>`;
        bannersWrapper = content.querySelector(".banners-wrapper");
        viewsWrapper = content.querySelector(".views-wrapper");
    }

    bannersWrapper.innerHTML = `${offlineBannerHtml()}${errorBannerHtml()}${contextStripHtml()}`;

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

    let currentViewEl = viewsWrapper.querySelector(`[data-view="${state.route}"]`);
    if (!currentViewEl) {
        currentViewEl = document.createElement("div");
        currentViewEl.setAttribute("data-view", state.route);
        currentViewEl.className = "route-view";
        viewsWrapper.appendChild(currentViewEl);
    }

    viewsWrapper.querySelectorAll(".route-view").forEach(el => {
        if (el.getAttribute("data-view") !== state.route) {
            el.style.display = "none";
            el.setAttribute("aria-hidden", "true");
        } else {
            el.style.display = "";
            el.removeAttribute("aria-hidden");
        }
    });

    const busy = content.getAttribute("aria-busy") || "false";
    let viewHtml;
    try {
        viewHtml = renderers[state.route]();
    } catch (error) {
        console.error(error);
        state.lastError = error?.message || String(error);
        viewHtml = noticeHtml("error", "Не удалось отрисовать раздел.", state.lastError, `<button class="btn primary" type="button" data-action="retry-load">Обновить данные</button>`);
    }

    currentViewEl.innerHTML = viewHtml;
    content.setAttribute("aria-busy", busy);
    bindViewActions(currentViewEl);
    if (state.route === "dashboard") {
         initKanbanDragAndDrop();
    }
    bindCatalogFilter(currentViewEl);
    bindWorkspaceToolbar(currentViewEl);
    updateScrollHints(currentViewEl);
    applyCellTitles(currentViewEl);
    updateNavigationBadges();
    requestAnimationFrame(() => {
        if (!document.contains(currentViewEl)) return;
        updateScrollHints(currentViewEl);
        applyCellTitles(currentViewEl);
    });
}
