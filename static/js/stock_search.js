(() => {
    "use strict";

    // =========================================================
    // EAGLE SMART SCANNER
    // STOCK SEARCH
    //
    // Supported modes:
    // - Intraday
    // - BTST
    // - Swing
    //
    // Search behavior:
    // 1. User types symbol/company/sector
    // 2. /api/search is queried
    // 3. Multiple-result API is supported
    // 4. Single-stock API response is also supported
    // 5. Result opens inside Eagle detail drawer
    // =========================================================


    // =========================================================
    // CONFIG
    // =========================================================

    const config =
        window.EAGLE_CONFIG || {};

    const api =
        config.api || {};


    // =========================================================
    // ELEMENTS
    // =========================================================

    const input =
        document.getElementById(
            "stockSearchInput"
        );

    const resultsBox =
        document.getElementById(
            "searchResults"
        );

    const clearButton =
        document.getElementById(
            "clearSearchButton"
        );


    if (
        !input
        || !resultsBox
    ) {
        return;
    }


    // =========================================================
    // STATE
    // =========================================================

    let debounceTimer =
        null;

    let activeRequest =
        null;

    let selectedIndex =
        -1;

    let currentResults =
        [];

    let requestSequence =
        0;


    // =========================================================
    // HELPERS
    // =========================================================

    function escapeHtml(
        value
    ) {
        return String(
            value ?? ""
        )
            .replaceAll(
                "&",
                "&amp;"
            )
            .replaceAll(
                "<",
                "&lt;"
            )
            .replaceAll(
                ">",
                "&gt;"
            )
            .replaceAll(
                '"',
                "&quot;"
            )
            .replaceAll(
                "'",
                "&#039;"
            );
    }


    function normalizeText(
        value
    ) {
        return String(
            value ?? ""
        ).trim();
    }


    function normalizeSymbol(
        value
    ) {
        let symbol =
            normalizeText(
                value
            )
                .toUpperCase();

        if (
            symbol.startsWith(
                "NSE:"
            )
        ) {
            symbol =
                symbol.slice(
                    4
                );
        }

        if (
            symbol.endsWith(
                "-EQ"
            )
        ) {
            symbol =
                symbol.slice(
                    0,
                    -3
                );
        }

        return symbol.trim();
    }


    // =========================================================
    // MODE
    // =========================================================

    function normalizeMode(
        value
    ) {
        const mode =
            normalizeText(
                value
            ).toLowerCase();

        if (
            mode === "intraday"
            || mode === "btst"
            || mode === "swing"
        ) {
            return mode;
        }

        return "intraday";
    }


    function getCurrentMode() {
        return normalizeMode(
            window.EagleDashboard
                ?.state
                ?.mode
            || config.initialMode
            || config.initialTimeframe
            || "intraday"
        );
    }


    // =========================================================
    // SEARCH BOX VISIBILITY
    // =========================================================

    function hideResults() {
        resultsBox.hidden =
            true;

        resultsBox.innerHTML =
            "";

        selectedIndex =
            -1;

        currentResults =
            [];
    }


    function showMessage(
        message,
        className = "search-empty"
    ) {
        currentResults =
            [];

        selectedIndex =
            -1;

        resultsBox.innerHTML = `
            <div class="${escapeHtml(
                className
            )}">
                ${escapeHtml(
                    message
                )}
            </div>
        `;

        resultsBox.hidden =
            false;
    }


    function showLoading() {
        showMessage(
            "Searching NSE sector universe...",
            "search-loading"
        );
    }


    // =========================================================
    // RESULT NORMALIZATION
    // =========================================================

    function normalizeSearchItem(
        item
    ) {
        if (
            !item
            || typeof item !== "object"
        ) {
            return null;
        }

        const symbol =
            normalizeSymbol(
                item.symbol
                || item.stock_symbol
                || item.fyers_symbol
            );

        if (!symbol) {
            return null;
        }

        return {
            ...item,

            symbol,

            company_name:
                normalizeText(
                    item.company_name
                    || item.stock_name
                    || item.name
                    || symbol
                ),

            sector:
                normalizeText(
                    item.sector
                    || item.sector_name
                    || ""
                ),

            fyers_symbol:
                item.fyers_symbol
                || `NSE:${symbol}-EQ`
        };
    }


    function extractSearchResults(
        payload
    ) {
        if (
            !payload
            || typeof payload !== "object"
        ) {
            return [];
        }


        // -----------------------------------------------------
        // Preferred multi-result API
        // -----------------------------------------------------

        if (
            Array.isArray(
                payload.results
            )
        ) {
            return payload.results
                .map(
                    normalizeSearchItem
                )
                .filter(
                    Boolean
                );
        }


        // -----------------------------------------------------
        // Alternate "stocks" API format
        // -----------------------------------------------------

        if (
            Array.isArray(
                payload.stocks
            )
        ) {
            return payload.stocks
                .map(
                    normalizeSearchItem
                )
                .filter(
                    Boolean
                );
        }


        // -----------------------------------------------------
        // Current app.py /api/search compatibility:
        //
        // {
        //   success: true,
        //   stock: {...}
        // }
        // -----------------------------------------------------

        if (
            payload.stock
            && typeof payload.stock
                === "object"
        ) {
            const normalized =
                normalizeSearchItem(
                    payload.stock
                );

            return normalized
                ? [normalized]
                : [];
        }


        return [];
    }


    // =========================================================
    // RENDER RESULTS
    // =========================================================

    function renderResults(
        results
    ) {
        currentResults =
            Array.isArray(
                results
            )
                ? results
                    .map(
                        normalizeSearchItem
                    )
                    .filter(
                        Boolean
                    )
                : [];

        selectedIndex =
            -1;


        if (
            currentResults.length
            === 0
        ) {
            showMessage(
                "No NSE sector stock found."
            );

            return;
        }


        resultsBox.innerHTML =
            currentResults
                .map(
                    (
                        item,
                        index
                    ) => {

                        const companyName =
                            item.company_name
                            || item.symbol;

                        const sector =
                            item.sector
                            || "NSE";

                        return `
                            <button
                                type="button"
                                class="search-result-item"
                                data-index="${index}"
                                data-symbol="${escapeHtml(
                                    item.symbol
                                )}"
                                role="option"
                            >

                                <span
                                    class="search-result-copy"
                                >

                                    <strong>
                                        ${escapeHtml(
                                            companyName
                                        )}
                                    </strong>

                                    <span>
                                        ${escapeHtml(
                                            sector
                                        )}
                                    </span>

                                </span>


                                <span
                                    class="search-result-symbol"
                                >
                                    ${escapeHtml(
                                        item.symbol
                                    )}
                                </span>

                            </button>
                        `;
                    }
                )
                .join(
                    ""
                );


        resultsBox.hidden =
            false;

        bindResultButtons();
    }


    // =========================================================
    // KEYBOARD SELECTION
    // =========================================================

    function updateKeyboardSelection() {
        const items =
            resultsBox.querySelectorAll(
                ".search-result-item"
            );


        items.forEach(
            (
                item,
                index
            ) => {

                const active =
                    index
                    === selectedIndex;


                item.classList.toggle(
                    "active",
                    active
                );


                item.setAttribute(
                    "aria-selected",
                    active
                        ? "true"
                        : "false"
                );


                if (active) {
                    item.scrollIntoView(
                        {
                            block:
                                "nearest"
                        }
                    );
                }
            }
        );
    }


    // =========================================================
    // OPEN STOCK
    // =========================================================

    function openStock(
        symbol
    ) {
        const normalizedSymbol =
            normalizeSymbol(
                symbol
            );


        if (
            !normalizedSymbol
        ) {
            return;
        }


        hideResults();


        const mode =
            getCurrentMode();


        // -----------------------------------------------------
        // Preferred:
        // open inside dashboard detail drawer
        // -----------------------------------------------------

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


        // -----------------------------------------------------
        // Fallback:
        // open stock detail page
        // -----------------------------------------------------

        window.location.href =
            (
                `/stock/${
                    encodeURIComponent(
                        normalizedSymbol
                    )
                }`
                + `?mode=${
                    encodeURIComponent(
                        mode
                    )
                }`
            );
    }


    // =========================================================
    // RESULT BUTTONS
    // =========================================================

    function bindResultButtons() {
        resultsBox
            .querySelectorAll(
                ".search-result-item"
            )
            .forEach(
                (
                    button
                ) => {

                    button.addEventListener(
                        "click",
                        () => {

                            openStock(
                                button.dataset
                                    .symbol
                            );
                        }
                    );
                }
            );
    }


    // =========================================================
    // SEARCH REQUEST
    // =========================================================

    async function searchStocks(
        query
    ) {
        const normalizedQuery =
            normalizeText(
                query
            );


        if (
            !normalizedQuery
        ) {
            hideResults();

            return;
        }


        // -----------------------------------------------------
        // Cancel previous request
        // -----------------------------------------------------

        if (
            activeRequest
        ) {
            activeRequest.abort();
        }


        const controller =
            new AbortController();


        activeRequest =
            controller;


        requestSequence += 1;


        const thisRequest =
            requestSequence;


        showLoading();


        try {

            if (
                !api.search
            ) {
                throw new Error(
                    "Search API is not configured."
                );
            }


            const url =
                new URL(
                    api.search,
                    window.location.origin
                );


            url.searchParams.set(
                "q",
                normalizedQuery
            );


            url.searchParams.set(
                "mode",
                getCurrentMode()
            );


            // Allow backend to return a useful shortlist
            url.searchParams.set(
                "limit",
                "10"
            );


            const response =
                await fetch(
                    url.toString(),
                    {
                        credentials:
                            "same-origin",

                        headers: {
                            "Accept":
                                "application/json"
                        },

                        signal:
                            controller.signal,

                        cache:
                            "no-store"
                    }
                );


            let payload =
                {};


            try {
                payload =
                    await response.json();

            } catch {
                payload =
                    {};
            }


            if (
                !response.ok
                || payload.success
                    === false
            ) {
                throw new Error(
                    payload.message
                    || payload.error
                    || "Stock search failed."
                );
            }


            // -------------------------------------------------
            // Ignore response if newer request already exists
            // -------------------------------------------------

            if (
                thisRequest
                !== requestSequence
            ) {
                return;
            }


            // -------------------------------------------------
            // Ignore if user has already changed search text
            // -------------------------------------------------

            if (
                normalizeText(
                    input.value
                )
                !== normalizedQuery
            ) {
                return;
            }


            const results =
                extractSearchResults(
                    payload
                );


            renderResults(
                results
            );


        } catch (
            error
        ) {

            if (
                error?.name
                === "AbortError"
            ) {
                return;
            }


            console.warn(
                "Eagle stock search failed:",
                error
            );


            if (
                thisRequest
                === requestSequence
            ) {
                showMessage(
                    error?.message
                    || "Stock search failed.",
                    "search-error"
                );
            }

        } finally {

            if (
                activeRequest
                === controller
            ) {
                activeRequest =
                    null;
            }
        }
    }


    // =========================================================
    // DEBOUNCE
    // =========================================================

    function scheduleSearch() {
        window.clearTimeout(
            debounceTimer
        );


        const query =
            normalizeText(
                input.value
            );


        if (
            !query
        ) {
            if (
                activeRequest
            ) {
                activeRequest.abort();

                activeRequest =
                    null;
            }


            hideResults();

            return;
        }


        debounceTimer =
            window.setTimeout(
                () => {

                    searchStocks(
                        query
                    );

                },
                300
            );
    }


    // =========================================================
    // INPUT
    // =========================================================

    input.addEventListener(
        "input",
        scheduleSearch
    );


    input.addEventListener(
        "focus",
        () => {

            if (
                normalizeText(
                    input.value
                )
                && currentResults.length
            ) {
                resultsBox.hidden =
                    false;
            }
        }
    );


    // =========================================================
    // KEYBOARD
    // =========================================================

    input.addEventListener(
        "keydown",
        (
            event
        ) => {

            if (
                event.key
                === "Escape"
            ) {
                hideResults();

                input.blur();

                return;
            }


            if (
                resultsBox.hidden
                || currentResults.length
                    === 0
            ) {
                return;
            }


            if (
                event.key
                === "ArrowDown"
            ) {
                event.preventDefault();


                selectedIndex =
                    Math.min(
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


                selectedIndex =
                    Math.max(
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


                const selectedResult =
                    selectedIndex >= 0
                        ? currentResults[
                            selectedIndex
                        ]
                        : currentResults[0];


                if (
                    selectedResult
                ) {
                    openStock(
                        selectedResult.symbol
                    );
                }
            }
        }
    );


    // =========================================================
    // CLEAR
    // =========================================================

    clearButton
        ?.addEventListener(
            "click",
            () => {

                if (
                    activeRequest
                ) {
                    activeRequest.abort();

                    activeRequest =
                        null;
                }


                window.clearTimeout(
                    debounceTimer
                );


                input.value =
                    "";


                hideResults();


                input.focus();
            }
        );


    // =========================================================
    // OUTSIDE CLICK
    // =========================================================

    document.addEventListener(
        "click",
        (
            event
        ) => {

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
    // MODE CHANGE SUPPORT
    // =========================================================

    window.addEventListener(
        "eagle:mode-change",
        () => {

            if (
                activeRequest
            ) {
                activeRequest.abort();

                activeRequest =
                    null;
            }


            window.clearTimeout(
                debounceTimer
            );


            if (
                normalizeText(
                    input.value
                )
            ) {
                scheduleSearch();
            }
        }
    );


    // =========================================================
    // CLEANUP
    // =========================================================

    window.addEventListener(
        "beforeunload",
        () => {

            if (
                activeRequest
            ) {
                activeRequest.abort();
            }


            window.clearTimeout(
                debounceTimer
            );
        }
    );


    // =========================================================
    // PUBLIC API
    // =========================================================

    window.EagleStockSearch = {

        search:
            searchStocks,

        openStock,

        hideResults,

        getCurrentMode
    };

})();
