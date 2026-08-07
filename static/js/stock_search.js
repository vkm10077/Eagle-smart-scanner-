(() => {
    "use strict";

    const config = window.EAGLE_CONFIG || {};

    const input = document.getElementById(
        "stockSearchInput"
    );

    const resultsBox = document.getElementById(
        "searchResults"
    );

    const clearButton = document.getElementById(
        "clearSearchButton"
    );

    if (!input || !resultsBox) {
        return;
    }

    let debounceTimer = null;
    let activeRequest = null;
    let selectedIndex = -1;
    let currentResults = [];


    // =========================================================
    // HELPERS
    // =========================================================

    function escapeHtml(value) {
        return String(value ?? "")
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#039;");
    }


    function normalizeMode(value) {
        const mode = String(
            value || ""
        )
            .trim()
            .toLowerCase();

        if (
            mode === "intraday"
            || mode === "swing"
        ) {
            return mode;
        }

        return "swing";
    }


    function getCurrentMode() {
        return normalizeMode(
            window.EagleDashboard
                ?.state
                ?.mode
            || config.initialMode
            || config.initialTimeframe
            || "swing"
        );
    }


    // =========================================================
    // RESULTS VISIBILITY
    // =========================================================

    function hideResults() {
        resultsBox.hidden = true;
        resultsBox.innerHTML = "";

        selectedIndex = -1;

        currentResults = [];
    }


    function showMessage(message) {
        resultsBox.innerHTML = `
            <div class="search-empty">
                ${escapeHtml(message)}
            </div>
        `;

        resultsBox.hidden = false;
    }


    // =========================================================
    // RENDER RESULTS
    // =========================================================

    function renderResults(results) {
        currentResults = (
            Array.isArray(results)
                ? results
                : []
        );

        selectedIndex = -1;

        if (!currentResults.length) {
            showMessage(
                "No NSE sector stock found."
            );

            return;
        }

        resultsBox.innerHTML = (
            currentResults.map(
                (item, index) => `
                    <button
                        type="button"
                        class="search-result-item"
                        data-index="${index}"
                        data-symbol="${escapeHtml(
                            item.symbol || ""
                        )}"
                    >

                        <span class="search-result-copy">

                            <strong>
                                ${escapeHtml(
                                    item.company_name
                                    || item.name
                                    || item.symbol
                                    || "-"
                                )}
                            </strong>

                            <span>
                                ${escapeHtml(
                                    item.sector
                                    || "Unknown Sector"
                                )}
                            </span>

                        </span>


                        <span class="search-result-symbol">
                            ${escapeHtml(
                                item.symbol || ""
                            )}
                        </span>

                    </button>
                `
            ).join("")
        );

        resultsBox.hidden = false;

        bindResultButtons();
    }


    // =========================================================
    // KEYBOARD SELECTION
    // =========================================================

    function updateKeyboardSelection() {
        const items = (
            resultsBox.querySelectorAll(
                ".search-result-item"
            )
        );

        items.forEach(
            (item, index) => {

                const isActive = (
                    index === selectedIndex
                );

                item.classList.toggle(
                    "active",
                    isActive
                );

                if (isActive) {
                    item.scrollIntoView(
                        {
                            block: "nearest"
                        }
                    );
                }
            }
        );
    }


    // =========================================================
    // OPEN STOCK
    // =========================================================

    function openStock(symbol) {
        const normalizedSymbol = String(
            symbol || ""
        ).trim().toUpperCase();

        if (!normalizedSymbol) {
            return;
        }

        hideResults();

        const mode = getCurrentMode();


        // Prefer dashboard detail drawer
        if (
            window.EagleDashboard
            && typeof (
                window.EagleDashboard
                    .loadStockDetail
            ) === "function"
        ) {
            window.EagleDashboard
                .loadStockDetail(
                    normalizedSymbol
                );

            return;
        }


        // Fallback full detail page
        window.location.href = (
            `/stock/${encodeURIComponent(
                normalizedSymbol
            )}`
            + `?mode=${encodeURIComponent(
                mode
            )}`
        );
    }


    function bindResultButtons() {
        resultsBox
            .querySelectorAll(
                ".search-result-item"
            )
            .forEach(
                (button) => {

                    button.addEventListener(
                        "click",
                        () => {

                            openStock(
                                button.dataset.symbol
                            );
                        }
                    );
                }
            );
    }


    // =========================================================
    // SEARCH REQUEST
    // =========================================================

    async function searchStocks(query) {
        const normalizedQuery = String(
            query || ""
        ).trim();

        if (!normalizedQuery) {
            hideResults();
            return;
        }

        if (activeRequest) {
            activeRequest.abort();
        }

        activeRequest = (
            new AbortController()
        );

        showMessage(
            "Searching NSE sector universe..."
        );

        try {
            const url = new URL(
                config.api.search,
                window.location.origin
            );

            url.searchParams.set(
                "q",
                normalizedQuery
            );


            const response = await fetch(
                url.toString(),
                {
                    credentials:
                        "same-origin",

                    headers: {
                        "Accept":
                            "application/json"
                    },

                    signal:
                        activeRequest.signal,

                    cache:
                        "no-store"
                }
            );


            const payload =
                await response.json();


            if (
                !response.ok
                || !payload.success
            ) {
                throw new Error(
                    payload.error
                    || "Stock search failed."
                );
            }


            // Ignore stale search response
            if (
                input.value.trim()
                !== normalizedQuery
            ) {
                return;
            }


            renderResults(
                payload.results
            );


        } catch (error) {
            if (
                error.name
                === "AbortError"
            ) {
                return;
            }

            showMessage(
                error.message
                || "Stock search failed."
            );
        }
    }


    // =========================================================
    // DEBOUNCE
    // =========================================================

    function scheduleSearch() {
        window.clearTimeout(
            debounceTimer
        );

        const query = (
            input.value.trim()
        );

        if (!query) {
            hideResults();
            return;
        }

        debounceTimer = (
            window.setTimeout(
                () => {
                    searchStocks(
                        query
                    );
                },
                260
            )
        );
    }


    // =========================================================
    // INPUT EVENTS
    // =========================================================

    input.addEventListener(
        "input",
        scheduleSearch
    );


    input.addEventListener(
        "focus",
        () => {

            if (
                input.value.trim()
                && currentResults.length
            ) {
                resultsBox.hidden =
                    false;
            }
        }
    );


    input.addEventListener(
        "keydown",
        (event) => {

            if (
                resultsBox.hidden
                || !currentResults.length
            ) {

                if (
                    event.key
                    === "Escape"
                ) {
                    input.blur();

                    hideResults();
                }

                return;
            }


            if (
                event.key
                === "ArrowDown"
            ) {
                event.preventDefault();

                selectedIndex = Math.min(
                    selectedIndex + 1,
                    currentResults.length - 1
                );

                updateKeyboardSelection();

                return;
            }


            if (
                event.key
                === "ArrowUp"
            ) {
                event.preventDefault();

                selectedIndex = Math.max(
                    selectedIndex - 1,
                    0
                );

                updateKeyboardSelection();

                return;
            }


            if (
                event.key
                === "Enter"
            ) {
                event.preventDefault();

                const selectedResult = (
                    selectedIndex >= 0
                        ? currentResults[
                            selectedIndex
                        ]
                        : currentResults[0]
                );

                openStock(
                    selectedResult
                        ?.symbol
                );

                return;
            }


            if (
                event.key
                === "Escape"
            ) {
                hideResults();
            }
        }
    );


    // =========================================================
    // CLEAR BUTTON
    // =========================================================

    clearButton?.addEventListener(
        "click",
        () => {

            input.value = "";

            input.focus();

            hideResults();
        }
    );


    // =========================================================
    // OUTSIDE CLICK
    // =========================================================

    document.addEventListener(
        "click",
        (event) => {

            const target =
                event.target;

            if (
                target === input
                || resultsBox.contains(
                    target
                )
                || clearButton?.contains(
                    target
                )
            ) {
                return;
            }

            hideResults();
        }
    );


    // =========================================================
    // CLEANUP
    // =========================================================

    window.addEventListener(
        "beforeunload",
        () => {

            if (activeRequest) {
                activeRequest.abort();
            }

            window.clearTimeout(
                debounceTimer
            );
        }
    );

})();
