(() => {
    "use strict";

    // =========================================================
    // CONFIG
    // =========================================================

    const config = window.EAGLE_CONFIG || {};

    const api = config.api || {};


    // =========================================================
    // STATE
    // =========================================================

    const state = {

        mode: (
            config.initialMode
            || config.initialTimeframe
            || "swing"
        ),

        results: [],

        topSectors: [],

        selectedSector: "",

        sectorStocks: [],

        filters: {
            sector: "",
            minimumTechnicalScore: "",
            chartPattern: ""
        },

        drawerOpen: false,

        sectorRequestId: 0,

        speechUnlocked: false,

        pendingAnnouncements: [],

        announcedStrongBuys: new Set()
    };


    // =========================================================
    // ELEMENTS
    // =========================================================

    const elements = {

        // -----------------------------------------------------
        // FINAL SIGNAL TABLE
        // -----------------------------------------------------

        tableBody: document.getElementById(
            "signalTableBody"
        ),

        resultCount: document.getElementById(
            "resultCount"
        ),

        signalsUpdatedAt: document.getElementById(
            "signalsUpdatedAt"
        ),


        // -----------------------------------------------------
        // FILTERS
        // -----------------------------------------------------

        sectorFilter: document.getElementById(
            "sectorFilter"
        ),

        technicalScoreFilter: document.getElementById(
            "technicalScoreFilter"
        ),

        patternFilter: document.getElementById(
            "patternFilter"
        ),

        resetFiltersButton: document.getElementById(
            "resetFiltersButton"
        ),


        // -----------------------------------------------------
        // MODE
        // -----------------------------------------------------

        timeframeTabs: document.getElementById(
            "timeframeTabs"
        ),


        // -----------------------------------------------------
        // MANUAL REFRESH
        // -----------------------------------------------------

        manualRefreshButton: document.getElementById(
            "manualRefreshButton"
        ),


        // -----------------------------------------------------
        // DETAIL DRAWER
        // -----------------------------------------------------

        drawer: document.getElementById(
            "detailDrawer"
        ),

        drawerTitle: document.getElementById(
            "detailDrawerTitle"
        ),

        drawerContent: document.getElementById(
            "detailDrawerContent"
        ),

        closeDrawerButton: document.getElementById(
            "closeDetailDrawer"
        ),


        // -----------------------------------------------------
        // TOP SECTORS
        // -----------------------------------------------------

        topSectorGrid: document.getElementById(
            "topSectorGrid"
        ),


        // -----------------------------------------------------
        // SELECTED SECTOR TOP 10 STOCKS
        // -----------------------------------------------------

        sectorStocksSection: document.getElementById(
            "sectorStocksSection"
        ),

        selectedSectorTitle: document.getElementById(
            "selectedSectorTitle"
        ),

        sectorStockCount: document.getElementById(
            "sectorStockCount"
        ),

        sectorStocksUpdatedAt: document.getElementById(
            "sectorStocksUpdatedAt"
        ),

        sectorStocksLoading: document.getElementById(
            "sectorStocksLoading"
        ),

        sectorStocksError: document.getElementById(
            "sectorStocksError"
        ),

        sectorStockTableBody: document.getElementById(
            "sectorStockTableBody"
        ),


        // -----------------------------------------------------
        // SCANNER STATUS
        // -----------------------------------------------------

        scannerStatusText: document.getElementById(
            "scannerStatusText"
        ),

        scannerProgressBar: document.getElementById(
            "scannerProgressBar"
        ),

        scannerStage: document.getElementById(
            "scannerStage"
        ),

        sectorCount: document.getElementById(
            "sectorCount"
        ),

        candidateCount: document.getElementById(
            "candidateCount"
        ),

        commonCount: document.getElementById(
            "commonCount"
        ),

        strongBuyCount: document.getElementById(
            "strongBuyCount"
        )
    };


    // =========================================================
    // BASIC HELPERS
    // =========================================================

    function escapeHtml(value) {

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


    function safeNumber(
        value,
        defaultValue = 0
    ) {

        const number = Number(
            value
        );

        return Number.isFinite(
            number
        )
            ? number
            : defaultValue;
    }


    function formatPrice(
        value
    ) {

        const number = Number(
            value
        );

        if (
            !Number.isFinite(
                number
            )
            || number <= 0
        ) {

            return "—";
        }

        return new Intl.NumberFormat(
            "en-IN",
            {
                style: "currency",
                currency: "INR",
                maximumFractionDigits: 2
            }
        ).format(
            number
        );
    }


    function formatNumber(
        value,
        digits = 2
    ) {

        const number = Number(
            value
        );

        if (
            !Number.isFinite(
                number
            )
        ) {

            return "—";
        }

        return number.toFixed(
            digits
        );
    }


    function formatPercent(
        value
    ) {

        const number = Number(
            value
        );

        if (
            !Number.isFinite(
                number
            )
        ) {

            return "—";
        }

        return (
            `${number.toFixed(2)}%`
        );
    }


    function formatDate(
        value
    ) {

        if (!value) {

            return "Waiting for scan";
        }

        const date = new Date(
            value
        );

        if (
            Number.isNaN(
                date.getTime()
            )
        ) {

            return String(
                value
            );
        }

        return new Intl.DateTimeFormat(
            "en-IN",
            {
                dateStyle: "medium",
                timeStyle: "medium",
                timeZone: "Asia/Kolkata"
            }
        ).format(
            date
        );
    }


    function normalizeMode(
        value
    ) {

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


    function isStrongBuy(
        item
    ) {

        if (
            !item
            || typeof item !== "object"
        ) {

            return false;
        }

        if (
            item.strong_buy === true
            || item.qualified_for_eagle_scanner === true
        ) {

            return true;
        }

        return (
            String(
                item.signal || ""
            )
                .trim()
                .toUpperCase()
            === "STRONG BUY"
        );
    }


    function signalClass(
        signal
    ) {

        return (
            String(
                signal || ""
            )
                .trim()
                .toUpperCase()
            === "STRONG BUY"
        )
            ? "strong-buy"
            : "no-trade";
    }


    // =========================================================
    // VOICE / SOUND
    // =========================================================

    function announcementKey(
        item
    ) {

        const symbol = String(
            item.symbol || ""
        )
            .trim()
            .toUpperCase();

        return (
            `${state.mode}:${symbol}`
        );
    }


    function loadAnnouncedSignals() {

        try {

            const stored = sessionStorage.getItem(
                "eagle-announced-strong-buys"
            );

            if (!stored) {
                return;
            }

            const values = JSON.parse(
                stored
            );

            if (
                !Array.isArray(
                    values
                )
            ) {

                return;
            }

            state.announcedStrongBuys = new Set(
                values
            );

        } catch (_) {

            state.announcedStrongBuys = new Set();
        }
    }


    function saveAnnouncedSignals() {

        try {

            sessionStorage.setItem(
                "eagle-announced-strong-buys",

                JSON.stringify(
                    [
                        ...state
                            .announcedStrongBuys
                    ]
                )
            );

        } catch (_) {
            // Storage unavailable.
        }
    }


    function buildStrongBuySpeech(
        item
    ) {

        const companyName = String(
            item.company_name
            || item.stock_name
            || item.symbol
            || "Stock"
        ).trim();

        const sector = String(
            item.sector
            || "Sector"
        ).trim();

        return (
            `${companyName}, `
            + `${sector}, `
            + "Strong Buy"
        );
    }


    function speakText(
        text
    ) {

        if (
            !("speechSynthesis" in window)
            || !window.SpeechSynthesisUtterance
        ) {

            return false;
        }

        try {

            const utterance = (
                new SpeechSynthesisUtterance(
                    text
                )
            );

            utterance.lang = (
                "en-IN"
            );

            utterance.rate = 0.92;

            utterance.pitch = 1;

            utterance.volume = 1;

            window.speechSynthesis.speak(
                utterance
            );

            return true;

        } catch (_) {

            return false;
        }
    }


    function flushPendingAnnouncements() {

        if (
            !state.speechUnlocked
            || !state.pendingAnnouncements.length
        ) {

            return;
        }

        const pending = [
            ...state.pendingAnnouncements
        ];

        state.pendingAnnouncements = [];

        pending.forEach(
            (text) => {

                speakText(
                    text
                );
            }
        );
    }


    function unlockSpeech() {

        if (
            state.speechUnlocked
        ) {

            flushPendingAnnouncements();

            return;
        }

        state.speechUnlocked = true;

        /*
         * Android browsers may require a user gesture
         * before speech is allowed.
         */

        try {

            if (
                "speechSynthesis"
                in window
            ) {

                window.speechSynthesis.resume();
            }

        } catch (_) {
            // Ignore.
        }

        flushPendingAnnouncements();
    }


    function announceNewStrongBuy(
        item
    ) {

        if (
            !isStrongBuy(
                item
            )
        ) {

            return;
        }

        const key = announcementKey(
            item
        );

        if (
            !key
            || state
                .announcedStrongBuys
                .has(
                    key
                )
        ) {

            return;
        }

        state
            .announcedStrongBuys
            .add(
                key
            );

        saveAnnouncedSignals();

        const speech = (
            buildStrongBuySpeech(
                item
            )
        );

        if (
            state.speechUnlocked
        ) {

            speakText(
                speech
            );

        } else {

            state
                .pendingAnnouncements
                .push(
                    speech
                );
        }
    }


    function announceNewStrongBuyResults(
        results
    ) {

        if (
            !Array.isArray(
                results
            )
        ) {

            return;
        }

        results.forEach(
            (item) => {

                announceNewStrongBuy(
                    item
                );
            }
        );
    }


    // =========================================================
    // FINAL SIGNAL FILTERING
    // =========================================================

    function getFilteredResults() {

        return state.results.filter(
            (item) => {

                if (
                    !isStrongBuy(
                        item
                    )
                ) {

                    return false;
                }


                if (
                    state.filters.sector
                    && String(
                        item.sector || ""
                    )
                        .trim()
                        .toLowerCase()
                    !== String(
                        state.filters.sector
                    )
                        .trim()
                        .toLowerCase()
                ) {

                    return false;
                }


                if (
                    state.filters
                        .minimumTechnicalScore
                ) {

                    const minimum = Number(
                        state.filters
                            .minimumTechnicalScore
                    );

                    const score = Number(
                        item.technical_score
                        || 0
                    );

                    if (
                        Number.isFinite(
                            minimum
                        )
                        && score < minimum
                    ) {

                        return false;
                    }
                }


                if (
                    state.filters
                        .chartPattern
                ) {

                    const selectedPattern = (
                        String(
                            state.filters
                                .chartPattern
                            || ""
                        )
                            .trim()
                            .toLowerCase()
                    );

                    const itemPattern = String(
                        item.chart_pattern
                        || ""
                    )
                        .trim()
                        .toLowerCase();

                    if (
                        itemPattern
                        !== selectedPattern
                    ) {

                        return false;
                    }
                }

                return true;
            }
        );
    }


    // =========================================================
    // FINAL STRONG BUY TABLE
    // =========================================================

    function renderEmptyState(
        message
    ) {

        if (
            !elements.tableBody
        ) {

            return;
        }

        elements.tableBody.innerHTML = `
            <tr>
                <td
                    colspan="12"
                    class="empty-state-cell"
                >
                    ${escapeHtml(
                        message
                    )}
                </td>
            </tr>
        `;

        if (
            elements.resultCount
        ) {

            elements.resultCount.textContent =
                "0 stocks";
        }
    }


    function renderTable() {

        if (
            !elements.tableBody
        ) {

            return;
        }

        const results = (
            getFilteredResults()
        );

        if (
            !results.length
        ) {

            renderEmptyState(
                "No confirmed Strong Buy setup matches the selected filters."
            );

            return;
        }


        elements.tableBody.innerHTML = (
            results.map(
                (item) => `

                    <tr>

                        <td>

                            <strong>
                                ${escapeHtml(
                                    item.company_name
                                    || item.stock_name
                                    || item.symbol
                                    || "—"
                                )}
                            </strong>

                            <small>
                                ${escapeHtml(
                                    item.symbol
                                    || ""
                                )}
                            </small>

                        </td>


                        <td>
                            ${escapeHtml(
                                item.sector
                                || "—"
                            )}
                        </td>


                        <td>
                            ${formatPrice(
                                item.current_price
                            )}
                        </td>


                        <td>
                            ${formatPrice(
                                item.entry_price
                            )}
                        </td>


                        <td>
                            ${formatPrice(
                                item.stop_loss
                            )}
                        </td>


                        <td>
                            ${formatPrice(
                                item.target_price
                            )}
                        </td>


                        <td>
                            ${
                                Number.isFinite(
                                    Number(
                                        item.risk_reward
                                    )
                                )
                                    ? `1:${Number(
                                        item.risk_reward
                                    ).toFixed(2)}`
                                    : "—"
                            }
                        </td>


                        <td>

                            <strong
                                class="technical-score"
                            >
                                ${formatNumber(
                                    item.technical_score
                                )}
                            </strong>

                        </td>


                        <td>
                            ${escapeHtml(
                                item.chart_pattern
                                || "—"
                            )}
                        </td>


                        <td>
                            ${escapeHtml(
                                item.candlestick_pattern
                                || "—"
                            )}
                        </td>


                        <td>

                            <span
                                class="signal-badge strong-buy"
                            >
                                STRONG BUY
                            </span>

                        </td>


                        <td>

                            <button
                                type="button"
                                class="detail-button"
                                data-symbol="${escapeHtml(
                                    item.symbol
                                    || ""
                                )}"
                            >
                                View
                            </button>

                        </td>

                    </tr>
                `
            ).join("")
        );


        if (
            elements.resultCount
        ) {

            elements.resultCount.textContent = (
                `${results.length} `
                + (
                    results.length === 1
                        ? "stock"
                        : "stocks"
                )
            );
        }
    }


    // =========================================================
    // TOP 10 SECTORS
    // =========================================================

    function renderTopSectors(
        sectors
    ) {

        if (
            !elements.topSectorGrid
        ) {

            return;
        }

        if (
            !Array.isArray(
                sectors
            )
            || !sectors.length
        ) {

            elements.topSectorGrid.innerHTML = `
                <div class="empty-sector-state">
                    Top sectors will appear after the technical scan.
                </div>
            `;

            return;
        }


        elements.topSectorGrid.innerHTML = (
            sectors.map(
                (
                    item,
                    index
                ) => {

                    const sector = String(
                        item.sector || ""
                    );

                    const selected = (
                        sector
                        === state.selectedSector
                    );

                    return `

                        <button
                            type="button"
                            class="
                                top-sector-card
                                sector-select-card
                                ${selected
                                    ? "active"
                                    : ""
                                }
                            "
                            data-sector="${escapeHtml(
                                sector
                            )}"
                            aria-pressed="${
                                selected
                                    ? "true"
                                    : "false"
                            }"
                        >

                            <div
                                class="top-sector-card-copy"
                            >

                                <strong>
                                    ${index + 1}.
                                    ${escapeHtml(
                                        sector
                                        || "—"
                                    )}
                                </strong>

                                <span>
                                    Tap to view Top 10 stocks
                                </span>

                            </div>


                            <div
                                class="sector-score-wrap"
                            >

                                <span>
                                    Score
                                </span>

                                <strong
                                    class="sector-score"
                                >
                                    ${formatNumber(
                                        item.score
                                    )}
                                </strong>

                            </div>

                        </button>
                    `;
                }
            ).join("")
        );
    }


    // =========================================================
    // SECTOR TOP 10 TABLE
    // =========================================================

    function renderSectorStocksEmpty(
        message
    ) {

        if (
            !elements.sectorStockTableBody
        ) {

            return;
        }

        elements.sectorStockTableBody.innerHTML = `
            <tr>
                <td
                    colspan="12"
                    class="empty-state-cell"
                >
                    ${escapeHtml(
                        message
                    )}
                </td>
            </tr>
        `;

        if (
            elements.sectorStockCount
        ) {

            elements.sectorStockCount.textContent =
                "0 stocks";
        }
    }


    function renderSectorStocks(
        stocks
    ) {

        if (
            !elements.sectorStockTableBody
        ) {

            return;
        }

        if (
            !Array.isArray(
                stocks
            )
            || !stocks.length
        ) {

            renderSectorStocksEmpty(
                "No verified ranked stocks are available for this sector."
            );

            return;
        }


        elements
            .sectorStockTableBody
            .innerHTML = (

                stocks.map(
                    (
                        item,
                        index
                    ) => {

                        const strongBuy = (
                            isStrongBuy(
                                item
                            )
                        );

                        const rank = (
                            safeNumber(
                                item.rank,
                                index + 1
                            )
                        );

                        return `

                            <tr
                                class="${
                                    strongBuy
                                        ? "sector-stock-strong-buy"
                                        : ""
                                }"
                            >

                                <td>

                                    <strong>
                                        ${rank}
                                    </strong>

                                </td>


                                <td>

                                    <strong>
                                        ${escapeHtml(
                                            item.company_name
                                            || item.stock_name
                                            || item.symbol
                                            || "—"
                                        )}
                                    </strong>

                                    <small>
                                        ${escapeHtml(
                                            item.symbol
                                            || ""
                                        )}
                                    </small>

                                </td>


                                <td>
                                    ${escapeHtml(
                                        item.sector
                                        || state.selectedSector
                                        || "—"
                                    )}
                                </td>


                                <td>
                                    ${formatPrice(
                                        item.current_price
                                    )}
                                </td>


                                <td>

                                    <strong
                                        class="technical-score"
                                    >
                                        ${formatNumber(
                                            item.score
                                        )}
                                    </strong>

                                </td>


                                <td>
                                    ${formatNumber(
                                        item.trend_score
                                    )}
                                </td>


                                <td>
                                    ${formatNumber(
                                        item.momentum_score
                                    )}
                                </td>


                                <td>
                                    ${formatNumber(
                                        item.volume_score
                                    )}
                                </td>


                                <td>
                                    ${formatNumber(
                                        item.rsi_score
                                    )}
                                </td>


                                <td>
                                    ${formatNumber(
                                        item.relative_strength_score
                                    )}
                                </td>


                                <td>

                                    ${
                                        strongBuy
                                            ? `
                                                <span
                                                    class="signal-badge strong-buy"
                                                >
                                                    STRONG BUY
                                                </span>
                                            `
                                            : `
                                                <span
                                                    class="signal-badge no-trade"
                                                >
                                                    RANKED
                                                </span>
                                            `
                                    }

                                </td>


                                <td>

                                    <button
                                        type="button"
                                        class="detail-button"
                                        data-symbol="${escapeHtml(
                                            item.symbol
                                            || ""
                                        )}"
                                    >
                                        View
                                    </button>

                                </td>

                            </tr>
                        `;
                    }
                ).join("")
            );


        if (
            elements.sectorStockCount
        ) {

            elements.sectorStockCount.textContent = (
                `${stocks.length} `
                + (
                    stocks.length === 1
                        ? "stock"
                        : "stocks"
                )
            );
        }
    }


    // =========================================================
    // LOAD ONE SECTOR TOP 10 STOCKS
    // =========================================================

    async function loadSectorStocks(
        sector,
        options = {}
    ) {

        const selectedSector = String(
            sector || ""
        ).trim();

        if (
            !selectedSector
        ) {

            return;
        }


        const requestId = (
            ++state.sectorRequestId
        );

        state.selectedSector = (
            selectedSector
        );

        state.sectorStocks = [];


        renderTopSectors(
            state.topSectors
        );


        if (
            elements.selectedSectorTitle
        ) {

            elements.selectedSectorTitle.textContent = (
                `${selectedSector} — Top 10 Stocks`
            );
        }


        if (
            elements.sectorStocksUpdatedAt
        ) {

            elements.sectorStocksUpdatedAt.textContent =
                "Loading verified technical ranking...";
        }


        if (
            elements.sectorStocksLoading
        ) {

            elements.sectorStocksLoading.hidden =
                false;
        }


        if (
            elements.sectorStocksError
        ) {

            elements.sectorStocksError.hidden =
                true;

            elements.sectorStocksError.textContent =
                "";
        }


        renderSectorStocksEmpty(
            "Loading Top 10 sector stocks..."
        );


        const endpoint = (
            api.sectorStocks
            || "/api/sector-stocks"
        );

        const url = new URL(
            endpoint,
            window.location.origin
        );

        url.searchParams.set(
            "sector",
            selectedSector
        );

        url.searchParams.set(
            "mode",
            state.mode
        );


        if (
            options.forceRefresh
        ) {

            url.searchParams.set(
                "refresh",
                "true"
            );
        }


        try {

            const response = await fetch(
                url.toString(),
                {
                    credentials:
                        "same-origin",

                    headers: {
                        "Accept":
                            "application/json"
                    }
                }
            );


            let payload = {};

            try {

                payload = (
                    await response.json()
                );

            } catch (_) {

                payload = {};
            }


            if (
                requestId
                !== state.sectorRequestId
            ) {

                return;
            }


            if (
                !response.ok
                || !payload.success
            ) {

                throw new Error(
                    payload.error
                    || (
                        "Top 10 sector stocks "
                        + "could not be loaded."
                    )
                );
            }


            const stocks = (
                Array.isArray(
                    payload.stocks
                )
                    ? payload.stocks
                    : (
                        Array.isArray(
                            payload.results
                        )
                            ? payload.results
                            : []
                    )
            );


            state.sectorStocks = (
                stocks
            );


            renderSectorStocks(
                stocks
            );


            if (
                elements.sectorStocksUpdatedAt
            ) {

                elements.sectorStocksUpdatedAt.textContent = (
                    formatDate(
                        payload.generated_at
                    )
                );
            }


            /*
             * If one of these ranked stocks has
             * already qualified as a final Strong Buy,
             * it is allowed to trigger the same alert.
             *
             * Duplicate alerts are blocked by
             * announcedStrongBuys Set.
             */

            announceNewStrongBuyResults(
                stocks
            );


            if (
                options.scrollIntoView !== false
                && elements.sectorStocksSection
            ) {

                elements
                    .sectorStocksSection
                    .scrollIntoView(
                        {
                            behavior:
                                "smooth",

                            block:
                                "start"
                        }
                    );
            }


            return payload;

        } catch (error) {

            if (
                requestId
                !== state.sectorRequestId
            ) {

                return;
            }


            state.sectorStocks = [];


            renderSectorStocksEmpty(
                error.message
            );


            if (
                elements.sectorStocksError
            ) {

                elements.sectorStocksError.hidden =
                    false;

                elements.sectorStocksError.textContent = (
                    error.message
                );
            }


            if (
                elements.sectorStocksUpdatedAt
            ) {

                elements.sectorStocksUpdatedAt.textContent =
                    "Unable to load";
            }

        } finally {

            if (
                requestId
                === state.sectorRequestId
                && elements.sectorStocksLoading
            ) {

                elements.sectorStocksLoading.hidden =
                    true;
            }
        }
    }


    // =========================================================
    // SCANNER STATUS
    // =========================================================

    function renderScannerStatus(
        scanner
    ) {

        const status = (
            scanner
            && typeof scanner === "object"
        )
            ? scanner
            : {};


        const running = Boolean(
            status.running
        );


        if (
            elements.scannerStatusText
        ) {

            if (running) {

                elements.scannerStatusText.textContent =
                    "Running";

            } else if (
                status.stage
                === "failed"
            ) {

                elements.scannerStatusText.textContent =
                    "Failed";

            } else if (
                status.stage
                === "authentication_required"
            ) {

                elements.scannerStatusText.textContent =
                    "Login Required";

            } else {

                elements.scannerStatusText.textContent =
                    "Ready";
            }
        }


        if (
            elements.scannerProgressBar
        ) {

            const progress = Math.max(
                0,
                Math.min(
                    100,

                    safeNumber(
                        status.progress_percent,
                        0
                    )
                )
            );

            elements
                .scannerProgressBar
                .style
                .width = (
                    `${progress}%`
                );
        }


        if (
            elements.scannerStage
        ) {

            elements.scannerStage.textContent = (
                status.stage
                || "idle"
            );
        }


        if (
            elements.sectorCount
        ) {

            elements.sectorCount.textContent = (
                safeNumber(
                    status.sector_count,
                    0
                )
            );
        }


        if (
            elements.candidateCount
        ) {

            elements.candidateCount.textContent = (
                safeNumber(
                    status.candidate_count,
                    0
                )
            );
        }


        if (
            elements.commonCount
        ) {

            elements.commonCount.textContent = (
                safeNumber(
                    status.common_count,
                    0
                )
            );
        }


        if (
            elements.strongBuyCount
        ) {

            elements.strongBuyCount.textContent = (
                safeNumber(
                    status.strong_buy_count,
                    0
                )
            );
        }


        if (
            elements.manualRefreshButton
        ) {

            elements.manualRefreshButton.disabled = (
                running
            );

            elements.manualRefreshButton.textContent = (
                running
                    ? "Scanning..."
                    : "Refresh Scan"
            );
        }
    }


    // =========================================================
    // DETAIL HELPERS
    // =========================================================

    function renderBooleanStatus(
        value
    ) {

        return value
            ? `
                <span class="status-pass">
                    Pass
                </span>
            `
            : `
                <span class="status-fail">
                    Fail
                </span>
            `;
    }


    function renderReasons(
        reasons
    ) {

        if (
            !Array.isArray(
                reasons
            )
            || !reasons.length
        ) {

            return `
                <div class="detail-empty">
                    No bullish confirmations recorded.
                </div>
            `;
        }

        return `
            <ul class="reason-list">

                ${reasons.map(
                    (reason) => `

                        <li>
                            ${escapeHtml(
                                reason
                            )}
                        </li>

                    `
                ).join("")}

            </ul>
        `;
    }


    function renderRejectedReasons(
        reasons
    ) {

        if (
            !Array.isArray(
                reasons
            )
            || !reasons.length
        ) {

            return "";
        }

        return `

            <section
                class="detail-section danger-section"
            >

                <div
                    class="detail-section-heading"
                >

                    <div>

                        <p class="eyebrow">
                            FAILED CONDITIONS
                        </p>

                        <h3>
                            Rejection Reasons
                        </h3>

                    </div>

                </div>


                <ul class="reason-list">

                    ${reasons.map(
                        (reason) => `

                            <li>
                                ${escapeHtml(
                                    reason
                                )}
                            </li>

                        `
                    ).join("")}

                </ul>

            </section>
        `;
    }


    // =========================================================
    // DETAIL CONTENT
    // =========================================================

    function renderDetail(
        data
    ) {

        if (
            !elements.drawerContent
        ) {

            return;
        }


        if (
            !data
            || typeof data !== "object"
        ) {

            elements.drawerContent.innerHTML = `
                <div class="detail-error">
                    Verified technical analysis is unavailable.
                </div>
            `;

            return;
        }


        const companyName = (
            data.company_name
            || data.stock_name
            || data.symbol
            || "Stock Detail"
        );


        if (
            elements.drawerTitle
        ) {

            elements.drawerTitle.textContent = (
                companyName
            );
        }


        const qualified = (
            data.qualified_for_eagle_scanner
            || isStrongBuy(
                data
            )
        );


        elements.drawerContent.innerHTML = `

            <section
                class="detail-summary-grid"
            >

                <article
                    class="detail-summary-card"
                >

                    <span>
                        Signal
                    </span>

                    <strong
                        class="signal-badge ${signalClass(
                            data.signal
                        )}"
                    >
                        ${escapeHtml(
                            data.signal
                            || "NO SIGNAL"
                        )}
                    </strong>

                </article>


                <article
                    class="detail-summary-card"
                >

                    <span>
                        Trading Mode
                    </span>

                    <strong>
                        ${escapeHtml(
                            data.mode
                            || state.mode
                        )}
                    </strong>

                </article>


                <article
                    class="detail-summary-card"
                >

                    <span>
                        Current Price
                    </span>

                    <strong>
                        ${formatPrice(
                            data.current_price
                        )}
                    </strong>

                </article>


                <article
                    class="detail-summary-card"
                >

                    <span>
                        Entry Price
                    </span>

                    <strong>
                        ${formatPrice(
                            data.entry_price
                        )}
                    </strong>

                </article>


                <article
                    class="detail-summary-card"
                >

                    <span>
                        Stop Loss
                    </span>

                    <strong>
                        ${formatPrice(
                            data.stop_loss
                        )}
                    </strong>

                </article>


                <article
                    class="detail-summary-card"
                >

                    <span>
                        Target
                    </span>

                    <strong>
                        ${formatPrice(
                            data.target_price
                        )}
                    </strong>

                </article>


                <article
                    class="detail-summary-card"
                >

                    <span>
                        Technical Score
                    </span>

                    <strong>
                        ${formatNumber(
                            data.technical_score
                        )}
                    </strong>

                </article>


                <article
                    class="detail-summary-card"
                >

                    <span>
                        Confirmations
                    </span>

                    <strong>
                        ${safeNumber(
                            data.confirmations,
                            0
                        )}
                    </strong>

                </article>


                <article
                    class="detail-summary-card"
                >

                    <span>
                        Risk:Reward
                    </span>

                    <strong>
                        ${
                            Number.isFinite(
                                Number(
                                    data.risk_reward
                                )
                            )
                                ? `1:${Number(
                                    data.risk_reward
                                ).toFixed(2)}`
                                : "—"
                        }
                    </strong>

                </article>


                <article
                    class="detail-summary-card"
                >

                    <span>
                        Eagle Qualified
                    </span>

                    <strong>
                        ${
                            qualified
                                ? "YES"
                                : "NO"
                        }
                    </strong>

                </article>

            </section>


            ${renderRejectedReasons(
                data.rejected_reasons
            )}


            <section
                class="detail-section"
            >

                <div
                    class="detail-section-heading"
                >

                    <div>

                        <p class="eyebrow">
                            TREND & MOMENTUM
                        </p>

                        <h3>
                            Technical Conditions
                        </h3>

                    </div>

                </div>


                <div
                    class="detail-stat-grid"
                >

                    <article>

                        <span>
                            EMA Structure
                        </span>

                        <strong>
                            ${renderBooleanStatus(
                                data.ema_bullish
                            )}
                        </strong>

                    </article>


                    <article>

                        <span>
                            RSI
                        </span>

                        <strong>
                            ${formatNumber(
                                data.rsi
                            )}
                        </strong>

                    </article>


                    <article>

                        <span>
                            MACD
                        </span>

                        <strong>
                            ${renderBooleanStatus(
                                data.macd_bullish
                            )}
                        </strong>

                    </article>


                    <article>

                        <span>
                            Supertrend
                        </span>

                        <strong>
                            ${renderBooleanStatus(
                                data.supertrend_bullish
                            )}
                        </strong>

                    </article>


                    <article>

                        <span>
                            Above VWAP
                        </span>

                        <strong>
                            ${renderBooleanStatus(
                                data.above_vwap
                            )}
                        </strong>

                    </article>


                    <article>

                        <span>
                            Volume Ratio
                        </span>

                        <strong>
                            ${formatNumber(
                                data.volume_ratio
                            )}x
                        </strong>

                    </article>


                    <article>

                        <span>
                            Volume Confirmed
                        </span>

                        <strong>
                            ${renderBooleanStatus(
                                data.volume_confirmed
                            )}
                        </strong>

                    </article>


                    <article>

                        <span>
                            Breakout
                        </span>

                        <strong>
                            ${renderBooleanStatus(
                                data.breakout
                            )}
                        </strong>

                    </article>


                    <article>

                        <span>
                            Price Action
                        </span>

                        <strong>
                            ${renderBooleanStatus(
                                data.price_action_bullish
                            )}
                        </strong>

                    </article>


                    <article>

                        <span>
                            Relative Strength
                        </span>

                        <strong>
                            ${formatPercent(
                                data.relative_strength_pct
                            )}
                        </strong>

                    </article>

                </div>

            </section>


            <section
                class="detail-section"
            >

                <div
                    class="detail-section-heading"
                >

                    <div>

                        <p class="eyebrow">
                            CHART PATTERN
                        </p>

                        <h3>
                            Pattern Analysis
                        </h3>

                    </div>


                    <strong>
                        Score
                        ${formatNumber(
                            data.chart_pattern_score
                        )}
                    </strong>

                </div>


                <div
                    class="detail-stat-grid"
                >

                    <article>

                        <span>
                            Strongest Pattern
                        </span>

                        <strong>
                            ${escapeHtml(
                                data.chart_pattern
                                || "Not detected"
                            )}
                        </strong>

                    </article>


                    <article>

                        <span>
                            Confirmed
                        </span>

                        <strong>
                            ${renderBooleanStatus(
                                data.chart_pattern_confirmed
                            )}
                        </strong>

                    </article>


                    <article>

                        <span>
                            Breakout Level
                        </span>

                        <strong>
                            ${formatPrice(
                                data.breakout_price
                            )}
                        </strong>

                    </article>

                </div>

            </section>


            <section
                class="detail-section"
            >

                <div
                    class="detail-section-heading"
                >

                    <div>

                        <p class="eyebrow">
                            CANDLESTICK
                        </p>

                        <h3>
                            Bullish Candlestick Pattern
                        </h3>

                    </div>

                </div>


                <div
                    class="detail-stat-grid"
                >

                    <article>

                        <span>
                            Pattern
                        </span>

                        <strong>
                            ${escapeHtml(
                                data.candlestick_pattern
                                || "Not detected"
                            )}
                        </strong>

                    </article>


                    <article>

                        <span>
                            Confirmed
                        </span>

                        <strong>
                            ${renderBooleanStatus(
                                data.candlestick_confirmed
                            )}
                        </strong>

                    </article>

                </div>

            </section>


            <section
                class="detail-section"
            >

                <div
                    class="detail-section-heading"
                >

                    <div>

                        <p class="eyebrow">
                            CONFIRMATIONS
                        </p>

                        <h3>
                            Why This Setup
                        </h3>

                    </div>

                </div>


                ${renderReasons(
                    data.reasons
                )}

            </section>


            <section
                class="detail-section"
            >

                <div
                    class="detail-section-heading"
                >

                    <div>

                        <p class="eyebrow">
                            DATA
                        </p>

                        <h3>
                            Market Data Status
                        </h3>

                    </div>

                </div>


                <div
                    class="detail-stat-grid"
                >

                    <article>

                        <span>
                            Sector
                        </span>

                        <strong>
                            ${escapeHtml(
                                data.sector
                                || "—"
                            )}
                        </strong>

                    </article>


                    <article>

                        <span>
                            Primary Timeframe
                        </span>

                        <strong>
                            ${escapeHtml(
                                data.primary_resolution
                                || "—"
                            )}
                        </strong>

                    </article>


                    <article>

                        <span>
                            Confirmation
                        </span>

                        <strong>
                            ${escapeHtml(
                                data.confirmation_resolution
                                || "—"
                            )}
                        </strong>

                    </article>


                    <article>

                        <span>
                            Higher Timeframe
                        </span>

                        <strong>
                            ${escapeHtml(
                                data.higher_resolution
                                || "—"
                            )}
                        </strong>

                    </article>


                    <article>

                        <span>
                            Verified
                        </span>

                        <strong>
                            ${
                                data.verified
                                    ? "YES"
                                    : "NO"
                            }
                        </strong>

                    </article>

                </div>

            </section>
        `;
    }


    // =========================================================
    // DRAWER
    // =========================================================

    function openDrawer() {

        state.drawerOpen = true;

        elements.drawer?.classList.add(
            "open"
        );

        elements.drawer?.setAttribute(
            "aria-hidden",
            "false"
        );

        document.body.style.overflow = (
            "hidden"
        );
    }


    function closeDrawer() {

        state.drawerOpen = false;

        elements.drawer?.classList.remove(
            "open"
        );

        elements.drawer?.setAttribute(
            "aria-hidden",
            "true"
        );

        document.body.style.overflow = (
            ""
        );
    }


    // =========================================================
    // STOCK DETAIL API
    // =========================================================

    async function loadStockDetail(
        symbol
    ) {

        const normalizedSymbol = String(
            symbol || ""
        )
            .trim()
            .toUpperCase();

        if (
            !normalizedSymbol
        ) {

            return;
        }


        unlockSpeech();

        openDrawer();


        if (
            elements.drawerTitle
        ) {

            elements.drawerTitle.textContent = (
                normalizedSymbol
            );
        }


        if (
            elements.drawerContent
        ) {

            elements.drawerContent.innerHTML = `
                <div class="detail-loading">
                    Loading verified technical analysis...
                </div>
            `;
        }


        try {

            const base = (
                api.stockDetailBase
                || "/api/stock/"
            );

            const endpoint = (
                `${base}${encodeURIComponent(
                    normalizedSymbol
                )}`
            );


            const url = new URL(
                endpoint,
                window.location.origin
            );

            url.searchParams.set(
                "mode",
                state.mode
            );


            const response = await fetch(
                url.toString(),
                {
                    credentials:
                        "same-origin",

                    headers: {
                        "Accept":
                            "application/json"
                    }
                }
            );


            let payload = {};

            try {

                payload = (
                    await response.json()
                );

            } catch (_) {

                payload = {};
            }


            if (
                !response.ok
                || !payload.success
            ) {

                throw new Error(
                    payload.error
                    || (
                        "Technical analysis "
                        + "could not be loaded."
                    )
                );
            }


            renderDetail(
                payload.stock
            );


            if (
                isStrongBuy(
                    payload.stock
                )
            ) {

                announceNewStrongBuy(
                    payload.stock
                );
            }

        } catch (error) {

            if (
                elements.drawerContent
            ) {

                elements.drawerContent.innerHTML = `
                    <div class="detail-error">
                        ${escapeHtml(
                            error.message
                        )}
                    </div>
                `;
            }
        }
    }


    // =========================================================
    // SIGNALS API
    // =========================================================

    async function fetchSignals() {

        const endpoint = (
            api.signals
            || "/api/signals"
        );

        const url = new URL(
            endpoint,
            window.location.origin
        );

        url.searchParams.set(
            "mode",
            state.mode
        );


        try {

            const response = await fetch(
                url.toString(),
                {
                    credentials:
                        "same-origin",

                    headers: {
                        "Accept":
                            "application/json"
                    }
                }
            );


            let payload = {};

            try {

                payload = (
                    await response.json()
                );

            } catch (_) {

                payload = {};
            }


            if (
                !response.ok
                || !payload.success
            ) {

                throw new Error(
                    payload.error
                    || (
                        "Signals could not "
                        + "be loaded."
                    )
                );
            }


            const previousKeys = new Set(
                state.results
                    .filter(
                        (item) => (
                            isStrongBuy(
                                item
                            )
                        )
                    )
                    .map(
                        (item) => (
                            announcementKey(
                                item
                            )
                        )
                    )
            );


            state.results = (
                Array.isArray(
                    payload.results
                )
                    ? payload.results
                    : []
            );


            state.topSectors = (
                Array.isArray(
                    payload.top_sectors
                )
                    ? payload.top_sectors
                    : []
            );


            renderTable();


            renderTopSectors(
                state.topSectors
            );


            /*
             * Announce only verified Strong Buy stocks.
             *
             * sessionStorage prevents repeating the
             * same stock on every auto refresh.
             */

            state.results.forEach(
                (item) => {

                    if (
                        !isStrongBuy(
                            item
                        )
                    ) {

                        return;
                    }

                    const key = (
                        announcementKey(
                            item
                        )
                    );

                    if (
                        !previousKeys.has(
                            key
                        )
                        || !state
                            .announcedStrongBuys
                            .has(
                                key
                            )
                    ) {

                        announceNewStrongBuy(
                            item
                        );
                    }
                }
            );


            if (
                elements.signalsUpdatedAt
            ) {

                elements.signalsUpdatedAt.textContent = (
                    formatDate(
                        payload.generated_at
                    )
                );
            }


            if (
                elements.sectorCount
            ) {

                elements.sectorCount.textContent = (
                    state.topSectors.length
                );
            }


            if (
                elements.candidateCount
            ) {

                elements.candidateCount.textContent = (
                    safeNumber(
                        payload.candidate_count,
                        0
                    )
                );
            }


            if (
                elements.commonCount
            ) {

                elements.commonCount.textContent = (
                    safeNumber(
                        payload.common_count,
                        0
                    )
                );
            }


            if (
                elements.strongBuyCount
            ) {

                elements.strongBuyCount.textContent = (
                    safeNumber(
                        payload.strong_buy_count,
                        state.results.length
                    )
                );
            }


            renderScannerStatus(
                payload.scanner_status
                || {}
            );


            window.dispatchEvent(
                new CustomEvent(
                    "eagle:scanner-status",
                    {
                        detail: (
                            payload.scanner_status
                            || {}
                        )
                    }
                )
            );


            /*
             * If a sector is currently open,
             * refresh the Top-10 display after
             * final signals update so Strong Buy
             * marker also stays current.
             */

            if (
                state.selectedSector
            ) {

                loadSectorStocks(
                    state.selectedSector,
                    {
                        scrollIntoView:
                            false
                    }
                );
            }


            return payload;

        } catch (error) {

            renderEmptyState(
                error.message
            );

            throw error;
        }
    }


    // =========================================================
    // MANUAL REFRESH
    // =========================================================

    async function triggerManualRefresh() {

        if (
            !elements.manualRefreshButton
        ) {

            return;
        }


        unlockSpeech();


        elements.manualRefreshButton.disabled =
            true;

        elements.manualRefreshButton.textContent =
            "Starting...";


        try {

            const endpoint = (
                api.scanRefresh
                || "/api/scan/refresh"
            );


            const response = await fetch(
                endpoint,
                {
                    method:
                        "POST",

                    credentials:
                        "same-origin",

                    headers: {
                        "Accept":
                            "application/json",

                        "Content-Type":
                            "application/json"
                    },

                    body: JSON.stringify(
                        {
                            mode:
                                state.mode
                        }
                    )
                }
            );


            let payload = {};

            try {

                payload = (
                    await response.json()
                );

            } catch (_) {

                payload = {};
            }


            if (
                !response.ok
                || !payload.success
            ) {

                throw new Error(
                    payload.error
                    || (
                        "Scanner could not "
                        + "be started."
                    )
                );
            }


            renderScannerStatus(
                payload.scanner
                || {}
            );


            window.dispatchEvent(
                new CustomEvent(
                    "eagle:scanner-status",
                    {
                        detail: (
                            payload.scanner
                            || {}
                        )
                    }
                )
            );

        } catch (error) {

            window.alert(
                error.message
            );

        } finally {

            /*
             * Scanner status polling may
             * immediately disable this again
             * if scanner is still running.
             */

            if (
                elements.manualRefreshButton
            ) {

                elements.manualRefreshButton.disabled =
                    false;

                elements.manualRefreshButton.textContent =
                    "Refresh Scan";
            }
        }
    }


    // =========================================================
    // MODE CHANGE
    // =========================================================

    function clearSelectedSector() {

        state.selectedSector = "";

        state.sectorStocks = [];

        state.sectorRequestId += 1;


        if (
            elements.selectedSectorTitle
        ) {

            elements.selectedSectorTitle.textContent = (
                "Select a Sector"
            );
        }


        if (
            elements.sectorStocksUpdatedAt
        ) {

            elements.sectorStocksUpdatedAt.textContent = (
                "Tap a Top Sector above"
            );
        }


        if (
            elements.sectorStocksError
        ) {

            elements.sectorStocksError.hidden =
                true;

            elements.sectorStocksError.textContent =
                "";
        }


        if (
            elements.sectorStocksLoading
        ) {

            elements.sectorStocksLoading.hidden =
                true;
        }


        renderSectorStocksEmpty(
            "Tap any Top 10 Sector above to view its Top 10 ranked stocks."
        );
    }


    function setActiveMode(
        mode
    ) {

        const normalizedMode = (
            normalizeMode(
                mode
            )
        );


        if (
            normalizedMode
            === state.mode
        ) {

            return;
        }


        unlockSpeech();


        state.mode = (
            normalizedMode
        );


        state.results = [];

        state.topSectors = [];


        clearSelectedSector();


        document.querySelectorAll(
            ".timeframe-tab"
        ).forEach(
            (button) => {

                const buttonMode = (
                    button.dataset.mode
                    || button.dataset.timeframe
                );

                button.classList.toggle(
                    "active",

                    buttonMode
                    === normalizedMode
                );
            }
        );


        const url = new URL(
            window.location.href
        );

        url.searchParams.set(
            "mode",
            normalizedMode
        );

        url.searchParams.delete(
            "timeframe"
        );


        window.history.replaceState(
            {},
            "",
            url.toString()
        );


        renderEmptyState(
            "Loading verified Strong Buy signals..."
        );


        fetchSignals().catch(
            () => {}
        );
    }


    // =========================================================
    // FILTER BINDINGS
    // =========================================================

    function bindFilters() {

        elements.sectorFilter
            ?.addEventListener(
                "change",
                (event) => {

                    state.filters.sector = (
                        event.target.value
                    );

                    renderTable();
                }
            );


        elements.technicalScoreFilter
            ?.addEventListener(
                "change",
                (event) => {

                    state.filters
                        .minimumTechnicalScore = (
                            event.target.value
                        );

                    renderTable();
                }
            );


        elements.patternFilter
            ?.addEventListener(
                "change",
                (event) => {

                    state.filters
                        .chartPattern = (
                            event.target.value
                        );

                    renderTable();
                }
            );


        elements.resetFiltersButton
            ?.addEventListener(
                "click",
                () => {

                    state.filters = {
                        sector: "",
                        minimumTechnicalScore:
                            "",
                        chartPattern:
                            ""
                    };


                    if (
                        elements.sectorFilter
                    ) {

                        elements.sectorFilter.value =
                            "";
                    }


                    if (
                        elements.technicalScoreFilter
                    ) {

                        elements
                            .technicalScoreFilter
                            .value = "";
                    }


                    if (
                        elements.patternFilter
                    ) {

                        elements.patternFilter.value =
                            "";
                    }


                    renderTable();
                }
            );
    }


    // =========================================================
    // MODE BINDINGS
    // =========================================================

    function bindModes() {

        elements.timeframeTabs
            ?.addEventListener(
                "click",
                (event) => {

                    const button = (
                        event.target.closest(
                            ".timeframe-tab"
                        )
                    );

                    if (!button) {

                        return;
                    }

                    setActiveMode(
                        button.dataset.mode
                        || button.dataset.timeframe
                    );
                }
            );
    }


    // =========================================================
    // TOP SECTOR TAP BINDING
    // =========================================================

    function bindSectorCards() {

        elements.topSectorGrid
            ?.addEventListener(
                "click",
                (event) => {

                    const card = (
                        event.target.closest(
                            ".sector-select-card"
                        )
                    );

                    if (
                        !card
                        || !elements
                            .topSectorGrid
                            .contains(
                                card
                            )
                    ) {

                        return;
                    }


                    const sector = String(
                        card.dataset.sector
                        || ""
                    ).trim();


                    if (
                        !sector
                    ) {

                        return;
                    }


                    unlockSpeech();


                    loadSectorStocks(
                        sector,
                        {
                            scrollIntoView:
                                true
                        }
                    );
                }
            );
    }


    // =========================================================
    // DETAIL BUTTON EVENT DELEGATION
    // =========================================================

    function bindDetailButtons() {

        document.addEventListener(
            "click",
            (event) => {

                const button = (
                    event.target.closest(
                        ".detail-button"
                    )
                );

                if (!button) {

                    return;
                }


                const symbol = (
                    button.dataset.symbol
                );


                if (!symbol) {

                    return;
                }


                loadStockDetail(
                    symbol
                );
            }
        );
    }


    // =========================================================
    // DRAWER BINDINGS
    // =========================================================

    function bindDrawer() {

        elements.closeDrawerButton
            ?.addEventListener(
                "click",
                closeDrawer
            );


        elements.drawer
            ?.querySelector(
                ".detail-drawer-backdrop"
            )
            ?.addEventListener(
                "click",
                closeDrawer
            );


        document.addEventListener(
            "keydown",
            (event) => {

                if (
                    event.key === "Escape"
                    && state.drawerOpen
                ) {

                    closeDrawer();
                }
            }
        );
    }


    // =========================================================
    // SCANNER STATUS EVENT
    // =========================================================

    function bindScannerStatusEvent() {

        window.addEventListener(
            "eagle:scanner-status",
            (event) => {

                renderScannerStatus(
                    event.detail
                    || {}
                );
            }
        );
    }


    // =========================================================
    // SPEECH UNLOCK EVENTS
    // =========================================================

    function bindSpeechUnlock() {

        const unlockOnce = () => {

            unlockSpeech();

            document.removeEventListener(
                "pointerdown",
                unlockOnce
            );

            document.removeEventListener(
                "touchstart",
                unlockOnce
            );

            document.removeEventListener(
                "keydown",
                unlockOnce
            );
        };


        document.addEventListener(
            "pointerdown",
            unlockOnce,
            {
                once: true
            }
        );


        document.addEventListener(
            "touchstart",
            unlockOnce,
            {
                once: true,
                passive: true
            }
        );


        document.addEventListener(
            "keydown",
            unlockOnce,
            {
                once: true
            }
        );
    }


    // =========================================================
    // INITIALIZE
    // =========================================================

    function initialize() {

        state.mode = (
            normalizeMode(
                state.mode
            )
        );


        loadAnnouncedSignals();


        bindFilters();

        bindModes();

        bindSectorCards();

        bindDrawer();

        bindDetailButtons();

        bindScannerStatusEvent();

        bindSpeechUnlock();


        elements.manualRefreshButton
            ?.addEventListener(
                "click",
                triggerManualRefresh
            );


        fetchSignals().catch(
            () => {}
        );
    }


    // =========================================================
    // PUBLIC API
    // =========================================================

    window.EagleDashboard = {

        state,

        fetchSignals,

        loadStockDetail,

        loadSectorStocks,

        renderTable,

        renderTopSectors,

        renderSectorStocks,

        renderScannerStatus,

        setActiveMode,

        announceNewStrongBuy
    };


    // =========================================================
    // START
    // =========================================================

    document.addEventListener(
        "DOMContentLoaded",
        initialize
    );

})();
