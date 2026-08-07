(() => {
    "use strict";

    // =========================================================
    // CONFIG
    // =========================================================

    const config = window.EAGLE_CONFIG || {};
    const api = config.api || {};

    const state = {
        mode:
            config.initialMode
            || config.initialTimeframe
            || "swing",

        results: [],

        topSectors: [],

        selectedSector: "",

        sectorStocks: [],

        sectorStocksLoading: false,

        filters: {
            sector: "",
            minimumTechnicalScore: "",
            chartPattern: ""
        },

        drawerOpen: false,

        signalsInitialized: false,

        knownStrongBuySymbols: new Set(),

        voiceEnabled: true
    };


    // =========================================================
    // ELEMENTS
    // =========================================================

    const elements = {
        tableBody:
            document.getElementById(
                "signalTableBody"
            ),

        resultCount:
            document.getElementById(
                "resultCount"
            ),

        signalsUpdatedAt:
            document.getElementById(
                "signalsUpdatedAt"
            ),

        sectorFilter:
            document.getElementById(
                "sectorFilter"
            ),

        technicalScoreFilter:
            document.getElementById(
                "technicalScoreFilter"
            ),

        patternFilter:
            document.getElementById(
                "patternFilter"
            ),

        resetFiltersButton:
            document.getElementById(
                "resetFiltersButton"
            ),

        timeframeTabs:
            document.getElementById(
                "timeframeTabs"
            ),

        manualRefreshButton:
            document.getElementById(
                "manualRefreshButton"
            ),

        drawer:
            document.getElementById(
                "detailDrawer"
            ),

        drawerTitle:
            document.getElementById(
                "detailDrawerTitle"
            ),

        drawerContent:
            document.getElementById(
                "detailDrawerContent"
            ),

        closeDrawerButton:
            document.getElementById(
                "closeDetailDrawer"
            ),

        topSectorGrid:
            document.getElementById(
                "topSectorGrid"
            ),

        scannerStatusText:
            document.getElementById(
                "scannerStatusText"
            ),

        scannerProgressBar:
            document.getElementById(
                "scannerProgressBar"
            ),

        scannerStage:
            document.getElementById(
                "scannerStage"
            ),

        sectorCount:
            document.getElementById(
                "sectorCount"
            ),

        candidateCount:
            document.getElementById(
                "candidateCount"
            ),

        commonCount:
            document.getElementById(
                "commonCount"
            ),

        strongBuyCount:
            document.getElementById(
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


    function normalizeText(
        value
    ) {
        return String(
            value || ""
        )
            .trim();
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


    function getSignal(
        item
    ) {
        return String(
            item?.signal || ""
        )
            .trim()
            .toUpperCase();
    }


    function isStrongBuy(
        item
    ) {
        return (
            getSignal(
                item
            )
            === "STRONG BUY"
        );
    }


    function getCompanyName(
        item
    ) {
        return (
            item?.company_name
            || item?.stock_name
            || item?.name
            || item?.symbol
            || "Stock"
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
    // API ENDPOINT
    // =========================================================

    function getSectorStocksEndpoint() {
        /*
         * app.py me hum /api/sector-stocks
         * endpoint connect karenge.
         *
         * Agar dashboard.html me URL config
         * available hai to wahi use hoga.
         */

        return (
            api.sectorStocks
            || "/api/sector-stocks"
        );
    }


    // =========================================================
    // VOICE ALERT
    // =========================================================

    function speechAvailable() {
        return (
            "speechSynthesis" in window
            && "SpeechSynthesisUtterance"
                in window
        );
    }


    function speakStrongBuy(
        item
    ) {
        if (
            !state.voiceEnabled
            || !speechAvailable()
            || !item
        ) {
            return;
        }

        const companyName =
            getCompanyName(
                item
            );

        const sector =
            normalizeText(
                item.sector
            );

        const text = sector
            ? (
                `${companyName}, `
                + `${sector}, `
                + "Strong Buy"
            )
            : (
                `${companyName}, `
                + "Strong Buy"
            );

        try {
            const utterance =
                new SpeechSynthesisUtterance(
                    text
                );

            utterance.lang =
                "en-IN";

            utterance.rate =
                0.9;

            utterance.pitch =
                1;

            utterance.volume =
                1;

            window.speechSynthesis.speak(
                utterance
            );

        } catch (error) {
            console.warn(
                "Voice alert failed:",
                error
            );
        }
    }


    function processStrongBuyAlerts(
        results
    ) {
        const validResults =
            Array.isArray(
                results
            )
                ? results.filter(
                    isStrongBuy
                )
                : [];

        /*
         * First API load par existing signals
         * sirf baseline bante hain.
         *
         * Isliye dashboard kholte hi purane
         * signals baar-baar nahi bolenge.
         */

        if (
            !state.signalsInitialized
        ) {
            state.knownStrongBuySymbols =
                new Set(
                    validResults
                        .map(
                            (item) => (
                                normalizeText(
                                    item.symbol
                                )
                                    .toUpperCase()
                            )
                        )
                        .filter(
                            Boolean
                        )
                );

            state.signalsInitialized =
                true;

            return;
        }

        const currentSymbols =
            new Set();

        for (
            const item
            of validResults
        ) {
            const symbol =
                normalizeText(
                    item.symbol
                )
                    .toUpperCase();

            if (!symbol) {
                continue;
            }

            currentSymbols.add(
                symbol
            );

            if (
                !state
                    .knownStrongBuySymbols
                    .has(
                        symbol
                    )
            ) {
                speakStrongBuy(
                    item
                );
            }
        }

        state.knownStrongBuySymbols =
            currentSymbols;
    }


    // =========================================================
    // MAIN SIGNAL FILTER
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
                ) {
                    const currentSector =
                        normalizeText(
                            item.sector
                        )
                            .toLowerCase();

                    const selectedSector =
                        normalizeText(
                            state.filters
                                .sector
                        )
                            .toLowerCase();

                    if (
                        currentSector
                        !== selectedSector
                    ) {
                        return false;
                    }
                }

                if (
                    state.filters
                        .minimumTechnicalScore
                ) {
                    const minimum =
                        Number(
                            state.filters
                                .minimumTechnicalScore
                        );

                    const score =
                        safeNumber(
                            item.technical_score,
                            0
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
                    const selectedPattern =
                        normalizeText(
                            state.filters
                                .chartPattern
                        )
                            .toLowerCase();

                    const itemPattern =
                        normalizeText(
                            item.chart_pattern
                        )
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
    // MAIN SIGNAL TABLE
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
            elements.resultCount
                .textContent =
                "0 stocks";
        }
    }


    function renderTable() {
        if (
            !elements.tableBody
        ) {
            return;
        }

        const results =
            getFilteredResults();

        if (
            results.length === 0
        ) {
            renderEmptyState(
                "No confirmed Strong Buy setup matches the selected filters."
            );

            return;
        }

        elements.tableBody.innerHTML =
            results.map(
                (item) => `
                    <tr>

                        <td>
                            <strong>
                                ${escapeHtml(
                                    getCompanyName(
                                        item
                                    )
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
                                    ? (
                                        `1:${
                                            Number(
                                                item.risk_reward
                                            )
                                            .toFixed(
                                                2
                                            )
                                        }`
                                    )
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
            ).join(
                ""
            );

        if (
            elements.resultCount
        ) {
            elements.resultCount
                .textContent = (
                    `${results.length} `
                    + (
                        results.length === 1
                            ? "stock"
                            : "stocks"
                    )
                );
        }

        bindDetailButtons();
    }


    // =========================================================
    // CREATE TOP 10 STOCK PANEL
    // =========================================================

    function ensureSectorStockPanel() {
        let section =
            document.getElementById(
                "sectorStockSection"
            );

        if (section) {
            return section;
        }

        if (
            !elements.topSectorGrid
        ) {
            return null;
        }

        const topSectorSection =
            elements.topSectorGrid
                .closest(
                    ".top-sector-section"
                );

        if (
            !topSectorSection
        ) {
            return null;
        }

        section =
            document.createElement(
                "section"
            );

        section.id =
            "sectorStockSection";

        section.className =
            "sector-stock-section";

        section.hidden =
            true;

        section.innerHTML = `
            <div class="section-heading">

                <div>
                    <p class="eyebrow">
                        SELECTED SECTOR
                    </p>

                    <h2 id="selectedSectorTitle">
                        Top 10 Stocks
                    </h2>
                </div>

                <div class="section-meta">
                    <span>
                        Technical ranking
                    </span>

                    <strong id="selectedSectorMeta">
                        Tap a sector
                    </strong>
                </div>

            </div>

            <div class="sector-stock-panel">

                <div class="sector-stock-header">

                    <div>
                        <h3 id="sectorStockPanelTitle">
                            Sector Stocks
                        </h3>

                        <p>
                            Top ranked stocks are shown
                            whether or not they currently
                            qualify as Strong Buy.
                        </p>
                    </div>

                    <span
                        id="sectorStockCount"
                        class="sector-stock-count"
                    >
                        0 stocks
                    </span>

                </div>

                <div
                    id="sectorStockContent"
                    class="sector-stock-content"
                ></div>

            </div>
        `;

        topSectorSection.insertAdjacentElement(
            "afterend",
            section
        );

        return section;
    }


    function getSectorPanelElements() {
        ensureSectorStockPanel();

        return {
            section:
                document.getElementById(
                    "sectorStockSection"
                ),

            title:
                document.getElementById(
                    "selectedSectorTitle"
                ),

            meta:
                document.getElementById(
                    "selectedSectorMeta"
                ),

            panelTitle:
                document.getElementById(
                    "sectorStockPanelTitle"
                ),

            count:
                document.getElementById(
                    "sectorStockCount"
                ),

            content:
                document.getElementById(
                    "sectorStockContent"
                )
        };
    }


    // =========================================================
    // TOP SECTOR CARDS
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
            || sectors.length === 0
        ) {
            elements.topSectorGrid
                .innerHTML = `
                    <div class="empty-sector-state">
                        Top sectors will appear after the technical scan.
                    </div>
                `;

            return;
        }

        elements.topSectorGrid
            .innerHTML = (
                sectors.map(
                    (
                        item,
                        index
                    ) => {

                        const sector =
                            normalizeText(
                                item.sector
                            );

                        const active =
                            sector
                            && sector
                                .toLowerCase()
                            === state
                                .selectedSector
                                .toLowerCase();

                        return `
                            <div
                                class="top-sector-card ${
                                    active
                                        ? "active"
                                        : ""
                                }"
                                role="button"
                                tabindex="0"
                                data-sector="${escapeHtml(
                                    sector
                                )}"
                                aria-label="Show top stocks for ${escapeHtml(
                                    sector
                                )}"
                            >

                                <div>
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

                                <div class="sector-score">
                                    ${formatNumber(
                                        item.score
                                    )}
                                </div>

                            </div>
                        `;
                    }
                ).join(
                    ""
                )
            );

        bindSectorCards();
    }


    function bindSectorCards() {
        document.querySelectorAll(
            ".top-sector-card[data-sector]"
        ).forEach(
            (card) => {

                const activate =
                    () => {

                        const sector =
                            normalizeText(
                                card.dataset.sector
                            );

                        if (!sector) {
                            return;
                        }

                        selectSector(
                            sector
                        );
                    };

                card.addEventListener(
                    "click",
                    activate
                );

                card.addEventListener(
                    "keydown",
                    (event) => {

                        if (
                            event.key
                                === "Enter"
                            || event.key
                                === " "
                        ) {
                            event.preventDefault();

                            activate();
                        }
                    }
                );
            }
        );
    }


    // =========================================================
    // SECTOR STOCKS LOADING
    // =========================================================

    function renderSectorStocksLoading(
        sector
    ) {
        const panel =
            getSectorPanelElements();

        if (
            !panel.section
            || !panel.content
        ) {
            return;
        }

        panel.section.hidden =
            false;

        panel.title.textContent =
            `${sector} — Top 10 Stocks`;

        panel.panelTitle.textContent =
            sector;

        panel.meta.textContent =
            "Loading verified ranking";

        panel.count.textContent =
            "Loading";

        panel.content.innerHTML = `
            <div class="sector-stocks-loading">
                <div class="sector-stock-skeleton"></div>
                <div class="sector-stock-skeleton"></div>
                <div class="sector-stock-skeleton"></div>
                <div class="sector-stock-skeleton"></div>
                <div class="sector-stock-skeleton"></div>
            </div>
        `;
    }


    function renderSectorStocksError(
        message
    ) {
        const panel =
            getSectorPanelElements();

        if (
            !panel.section
            || !panel.content
        ) {
            return;
        }

        panel.section.hidden =
            false;

        panel.meta.textContent =
            "Unable to load";

        panel.count.textContent =
            "0 stocks";

        panel.content.innerHTML = `
            <div class="sector-stock-error">
                ${escapeHtml(
                    message
                )}
            </div>
        `;
    }


    // =========================================================
    // SECTOR STOCK CONDITIONS
    // =========================================================

    function renderPassFail(
        value
    ) {
        if (
            value === true
        ) {
            return `
                <span
                    class="condition-badge condition-pass"
                >
                    PASS
                </span>
            `;
        }

        if (
            value === false
        ) {
            return `
                <span
                    class="condition-badge condition-fail"
                >
                    FAIL
                </span>
            `;
        }

        return `
            <span
                class="condition-badge condition-neutral"
            >
                —
            </span>
        `;
    }


    function stockScoreClass(
        value
    ) {
        const score =
            safeNumber(
                value,
                0
            );

        if (
            score >= 80
        ) {
            return "high";
        }

        if (
            score >= 65
        ) {
            return "medium";
        }

        return "";
    }


    // =========================================================
    // RENDER TOP 10 STOCKS
    // =========================================================

    function renderSectorStocks(
        sector,
        stocks
    ) {
        const panel =
            getSectorPanelElements();

        if (
            !panel.section
            || !panel.content
        ) {
            return;
        }

        const rows =
            Array.isArray(
                stocks
            )
                ? stocks.slice(
                    0,
                    10
                )
                : [];

        panel.section.hidden =
            false;

        panel.title.textContent =
            `${sector} — Top 10 Stocks`;

        panel.panelTitle.textContent =
            sector;

        panel.meta.textContent =
            "Technical ranking";

        panel.count.textContent =
            (
                `${rows.length} `
                + (
                    rows.length === 1
                        ? "stock"
                        : "stocks"
                )
            );

        if (
            rows.length === 0
        ) {
            panel.content.innerHTML = `
                <div class="sector-stock-empty">
                    No verified ranked stocks are available for this sector yet.
                </div>
            `;

            return;
        }

        panel.content.innerHTML = `
            <div class="sector-stock-scroll">

                <table class="sector-stock-table">

                    <thead>
                        <tr>
                            <th>Rank</th>
                            <th>Stock</th>
                            <th>Score</th>
                            <th>Momentum</th>
                            <th>Trend</th>
                            <th>Volume</th>
                            <th>RS</th>
                            <th>Signal</th>
                            <th>Detail</th>
                        </tr>
                    </thead>

                    <tbody>

                        ${rows.map(
                            (
                                item,
                                index
                            ) => {

                                const strongBuy =
                                    isStrongBuy(
                                        item
                                    );

                                return `
                                    <tr
                                        class="${
                                            strongBuy
                                                ? "strong-buy-candidate"
                                                : ""
                                        }"
                                    >

                                        <td>
                                            <span class="stock-rank">
                                                ${index + 1}
                                            </span>
                                        </td>

                                        <td class="sector-stock-name">
                                            <strong>
                                                ${escapeHtml(
                                                    getCompanyName(
                                                        item
                                                    )
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
                                            <span
                                                class="stock-score-badge ${stockScoreClass(
                                                    item.score
                                                    ?? item.stock_score
                                                    ?? item.technical_score
                                                )}"
                                            >
                                                ${formatNumber(
                                                    item.score
                                                    ?? item.stock_score
                                                    ?? item.technical_score
                                                )}
                                            </span>
                                        </td>

                                        <td>
                                            ${formatNumber(
                                                item.momentum_score
                                            )}
                                        </td>

                                        <td>
                                            ${formatNumber(
                                                item.trend_score
                                            )}
                                        </td>

                                        <td>
                                            ${formatNumber(
                                                item.volume_score
                                            )}
                                        </td>

                                        <td>
                                            ${formatNumber(
                                                item.relative_strength_score
                                                ?? item.relative_strength_pct
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
                                                            class="condition-badge condition-neutral"
                                                        >
                                                            RANKED
                                                        </span>
                                                    `
                                            }
                                        </td>

                                        <td>
                                            <button
                                                type="button"
                                                class="detail-button sector-detail-button"
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
                        ).join("")}

                    </tbody>

                </table>

            </div>
        `;

        bindDetailButtons();
    }


    // =========================================================
    // FETCH TOP 10 STOCKS OF SECTOR
    // =========================================================

    async function fetchSectorStocks(
        sector
    ) {
        const normalizedSector =
            normalizeText(
                sector
            );

        if (
            !normalizedSector
        ) {
            return;
        }

        state.sectorStocksLoading =
            true;

        renderSectorStocksLoading(
            normalizedSector
        );

        try {

            const endpoint =
                getSectorStocksEndpoint();

            const url =
                new URL(
                    endpoint,
                    window.location.origin
                );

            url.searchParams.set(
                "sector",
                normalizedSector
            );

            url.searchParams.set(
                "mode",
                state.mode
            );

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
                        }
                    }
                );

            let payload = {};

            try {
                payload =
                    await response.json();

            } catch {
                payload = {};
            }

            if (
                !response.ok
                || payload.success
                    === false
            ) {
                throw new Error(
                    payload.error
                    || (
                        "Top 10 sector stocks "
                        + "could not be loaded."
                    )
                );
            }

            const stocks =
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
                    );

            state.sectorStocks =
                stocks;

            renderSectorStocks(
                normalizedSector,
                stocks
            );

            return payload;

        } catch (error) {

            console.error(
                "Sector stock request failed:",
                error
            );

            renderSectorStocksError(
                error.message
                || (
                    "Top 10 sector stocks "
                    + "could not be loaded."
                )
            );

            throw error;

        } finally {

            state.sectorStocksLoading =
                false;
        }
    }


    // =========================================================
    // SELECT SECTOR
    // =========================================================

    function selectSector(
        sector
    ) {
        const normalizedSector =
            normalizeText(
                sector
            );

        if (
            !normalizedSector
        ) {
            return;
        }

        state.selectedSector =
            normalizedSector;

        renderTopSectors(
            state.topSectors
        );

        fetchSectorStocks(
            normalizedSector
        ).catch(
            () => {}
        );

        const panel =
            ensureSectorStockPanel();

        if (panel) {
            setTimeout(
                () => {
                    panel.scrollIntoView(
                        {
                            behavior:
                                "smooth",

                            block:
                                "start"
                        }
                    );
                },
                60
            );
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
            && typeof scanner
                === "object"
        )
            ? scanner
            : {};

        const running =
            Boolean(
                status.running
            );

        if (
            elements.scannerStatusText
        ) {
            elements.scannerStatusText
                .textContent = (
                    running
                        ? "Running"
                        : (
                            status.stage
                                === "failed"
                                ? "Failed"
                                : "Ready"
                        )
                );
        }

        if (
            elements.scannerProgressBar
        ) {
            const progress =
                Math.max(
                    0,
                    Math.min(
                        100,
                        safeNumber(
                            status.progress_percent,
                            0
                        )
                    )
                );

            elements.scannerProgressBar
                .style.width =
                `${progress}%`;
        }

        if (
            elements.scannerStage
        ) {
            elements.scannerStage
                .textContent =
                status.stage
                || "idle";
        }

        if (
            elements.sectorCount
        ) {
            elements.sectorCount
                .textContent =
                safeNumber(
                    status.sector_count,
                    0
                );
        }

        if (
            elements.candidateCount
        ) {
            elements.candidateCount
                .textContent =
                safeNumber(
                    status.candidate_count,
                    0
                );
        }

        if (
            elements.commonCount
        ) {
            elements.commonCount
                .textContent =
                safeNumber(
                    status.common_count,
                    0
                );
        }

        if (
            elements.strongBuyCount
        ) {
            elements.strongBuyCount
                .textContent =
                safeNumber(
                    status.strong_buy_count,
                    0
                );
        }

        if (
            elements.manualRefreshButton
        ) {
            elements.manualRefreshButton
                .disabled =
                running;
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
            || reasons.length === 0
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
            || reasons.length === 0
        ) {
            return "";
        }

        return `
            <section
                class="detail-section danger-section"
            >

                <div class="detail-section-heading">
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
    // DETAIL RENDERING
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
            || typeof data
                !== "object"
        ) {
            elements.drawerContent
                .innerHTML = `
                    <div class="detail-error">
                        Verified technical analysis is unavailable.
                    </div>
                `;

            return;
        }

        const companyName =
            getCompanyName(
                data
            );

        if (
            elements.drawerTitle
        ) {
            elements.drawerTitle
                .textContent =
                companyName;
        }

        elements.drawerContent
            .innerHTML = `

            <section class="detail-summary-grid">

                <article class="detail-summary-card">
                    <span>Signal</span>

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

                <article class="detail-summary-card">
                    <span>Trading Mode</span>

                    <strong>
                        ${escapeHtml(
                            data.mode
                            || state.mode
                        )}
                    </strong>
                </article>

                <article class="detail-summary-card">
                    <span>Current Price</span>

                    <strong>
                        ${formatPrice(
                            data.current_price
                        )}
                    </strong>
                </article>

                <article class="detail-summary-card">
                    <span>Entry Price</span>

                    <strong>
                        ${formatPrice(
                            data.entry_price
                        )}
                    </strong>
                </article>

                <article class="detail-summary-card">
                    <span>Stop Loss</span>

                    <strong>
                        ${formatPrice(
                            data.stop_loss
                        )}
                    </strong>
                </article>

                <article class="detail-summary-card">
                    <span>Target</span>

                    <strong>
                        ${formatPrice(
                            data.target_price
                        )}
                    </strong>
                </article>

                <article class="detail-summary-card">
                    <span>Technical Score</span>

                    <strong>
                        ${formatNumber(
                            data.technical_score
                        )}
                    </strong>
                </article>

                <article class="detail-summary-card">
                    <span>Confirmations</span>

                    <strong>
                        ${safeNumber(
                            data.confirmations,
                            0
                        )}
                    </strong>
                </article>

                <article class="detail-summary-card">
                    <span>Risk:Reward</span>

                    <strong>
                        ${
                            Number.isFinite(
                                Number(
                                    data.risk_reward
                                )
                            )
                                ? (
                                    `1:${
                                        Number(
                                            data.risk_reward
                                        )
                                        .toFixed(
                                            2
                                        )
                                    }`
                                )
                                : "—"
                        }
                    </strong>
                </article>

                <article class="detail-summary-card">
                    <span>Eagle Qualified</span>

                    <strong>
                        ${
                            data
                                .qualified_for_eagle_scanner
                            || isStrongBuy(
                                data
                            )
                                ? "YES"
                                : "NO"
                        }
                    </strong>
                </article>

            </section>

            ${renderRejectedReasons(
                data.rejected_reasons
            )}

            <section class="detail-section">

                <div class="detail-section-heading">
                    <div>
                        <p class="eyebrow">
                            TREND & MOMENTUM
                        </p>

                        <h3>
                            Technical Conditions
                        </h3>
                    </div>
                </div>

                <div class="detail-stat-grid">

                    <article>
                        <span>EMA Structure</span>

                        <strong>
                            ${renderBooleanStatus(
                                data.ema_bullish
                            )}
                        </strong>
                    </article>

                    <article>
                        <span>RSI</span>

                        <strong>
                            ${formatNumber(
                                data.rsi
                            )}
                        </strong>
                    </article>

                    <article>
                        <span>MACD</span>

                        <strong>
                            ${renderBooleanStatus(
                                data.macd_bullish
                            )}
                        </strong>
                    </article>

                    <article>
                        <span>Supertrend</span>

                        <strong>
                            ${renderBooleanStatus(
                                data.supertrend_bullish
                            )}
                        </strong>
                    </article>

                    <article>
                        <span>Above VWAP</span>

                        <strong>
                            ${renderBooleanStatus(
                                data.above_vwap
                            )}
                        </strong>
                    </article>

                    <article>
                        <span>Volume Ratio</span>

                        <strong>
                            ${formatNumber(
                                data.volume_ratio
                            )}x
                        </strong>
                    </article>

                    <article>
                        <span>Volume Confirmed</span>

                        <strong>
                            ${renderBooleanStatus(
                                data.volume_confirmed
                            )}
                        </strong>
                    </article>

                    <article>
                        <span>Breakout</span>

                        <strong>
                            ${renderBooleanStatus(
                                data.breakout
                            )}
                        </strong>
                    </article>

                    <article>
                        <span>Price Action</span>

                        <strong>
                            ${renderBooleanStatus(
                                data.price_action_bullish
                            )}
                        </strong>
                    </article>

                    <article>
                        <span>Relative Strength</span>

                        <strong>
                            ${formatPercent(
                                data.relative_strength_pct
                            )}
                        </strong>
                    </article>

                </div>

            </section>


            <section class="detail-section">

                <div class="detail-section-heading">
                    <div>
                        <p class="eyebrow">
                            PATTERNS
                        </p>

                        <h3>
                            Chart & Candlestick
                        </h3>
                    </div>
                </div>

                <div class="detail-stat-grid">

                    <article>
                        <span>Chart Pattern</span>

                        <strong>
                            ${escapeHtml(
                                data.chart_pattern
                                || "Not detected"
                            )}
                        </strong>
                    </article>

                    <article>
                        <span>Chart Confirmed</span>

                        <strong>
                            ${renderBooleanStatus(
                                data.chart_pattern_confirmed
                            )}
                        </strong>
                    </article>

                    <article>
                        <span>Candlestick</span>

                        <strong>
                            ${escapeHtml(
                                data.candlestick_pattern
                                || "Not detected"
                            )}
                        </strong>
                    </article>

                    <article>
                        <span>Candle Confirmed</span>

                        <strong>
                            ${renderBooleanStatus(
                                data.candlestick_confirmed
                            )}
                        </strong>
                    </article>

                </div>

            </section>


            <section class="detail-section">

                <div class="detail-section-heading">
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
        `;
    }


    // =========================================================
    // DRAWER
    // =========================================================

    function openDrawer() {
        state.drawerOpen =
            true;

        elements.drawer
            ?.classList
            .add(
                "open"
            );

        elements.drawer
            ?.setAttribute(
                "aria-hidden",
                "false"
            );

        document.body
            .style.overflow =
            "hidden";
    }


    function closeDrawer() {
        state.drawerOpen =
            false;

        elements.drawer
            ?.classList
            .remove(
                "open"
            );

        elements.drawer
            ?.setAttribute(
                "aria-hidden",
                "true"
            );

        document.body
            .style.overflow =
            "";
    }


    // =========================================================
    // STOCK DETAIL API
    // =========================================================

    async function loadStockDetail(
        symbol
    ) {
        const normalizedSymbol =
            normalizeText(
                symbol
            );

        if (
            !normalizedSymbol
        ) {
            return;
        }

        openDrawer();

        if (
            elements.drawerTitle
        ) {
            elements.drawerTitle
                .textContent =
                normalizedSymbol;
        }

        if (
            elements.drawerContent
        ) {
            elements.drawerContent
                .innerHTML = `
                    <div class="detail-loading">
                        Loading verified technical analysis...
                    </div>
                `;
        }

        try {

            const endpoint =
                (
                    `${api.stockDetailBase
                        || "/api/stock/"}`
                    + encodeURIComponent(
                        normalizedSymbol
                    )
                );

            const url =
                new URL(
                    endpoint,
                    window.location.origin
                );

            url.searchParams.set(
                "mode",
                state.mode
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
                        }
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
                    || (
                        "Technical analysis "
                        + "could not be loaded."
                    )
                );
            }

            renderDetail(
                payload.stock
            );

        } catch (error) {

            if (
                elements.drawerContent
            ) {
                elements.drawerContent
                    .innerHTML = `
                        <div class="detail-error">
                            ${escapeHtml(
                                error.message
                                || "Technical analysis failed."
                            )}
                        </div>
                    `;
            }
        }
    }


    function bindDetailButtons() {
        document.querySelectorAll(
            ".detail-button"
        ).forEach(
            (button) => {

                if (
                    button.dataset
                        .eagleBound
                    === "1"
                ) {
                    return;
                }

                button.dataset
                    .eagleBound =
                    "1";

                button.addEventListener(
                    "click",
                    () => {
                        loadStockDetail(
                            button.dataset.symbol
                        );
                    }
                );
            }
        );
    }


    // =========================================================
    // FETCH SIGNALS
    // =========================================================

    async function fetchSignals() {
        if (
            !api.signals
        ) {
            return null;
        }

        const url =
            new URL(
                api.signals,
                window.location.origin
            );

        url.searchParams.set(
            "mode",
            state.mode
        );

        try {

            const response =
                await fetch(
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

            const payload =
                await response.json();

            if (
                !response.ok
                || !payload.success
            ) {
                throw new Error(
                    payload.error
                    || (
                        "Signals could "
                        + "not be loaded."
                    )
                );
            }

            const newResults =
                Array.isArray(
                    payload.results
                )
                    ? payload.results
                    : [];

            processStrongBuyAlerts(
                newResults
            );

            state.results =
                newResults;

            state.topSectors =
                Array.isArray(
                    payload.top_sectors
                )
                    ? payload.top_sectors
                    : [];

            renderTable();

            renderTopSectors(
                state.topSectors
            );

            if (
                elements.signalsUpdatedAt
            ) {
                elements.signalsUpdatedAt
                    .textContent =
                    formatDate(
                        payload.generated_at
                    );
            }

            if (
                elements.sectorCount
            ) {
                elements.sectorCount
                    .textContent =
                    state.topSectors.length;
            }

            if (
                elements.candidateCount
            ) {
                elements.candidateCount
                    .textContent =
                    safeNumber(
                        payload.candidate_count,
                        0
                    );
            }

            if (
                elements.commonCount
            ) {
                elements.commonCount
                    .textContent =
                    safeNumber(
                        payload.common_count,
                        0
                    );
            }

            if (
                elements.strongBuyCount
            ) {
                elements.strongBuyCount
                    .textContent =
                    safeNumber(
                        payload.strong_buy_count,
                        state.results.length
                    );
            }

            renderScannerStatus(
                payload.scanner_status
                || {}
            );

            /*
             * Agar selected sector already
             * open hai to fresh scan ke baad
             * Top 10 stocks ko bhi refresh karo.
             */

            if (
                state.selectedSector
                && !state.sectorStocksLoading
            ) {
                fetchSectorStocks(
                    state.selectedSector
                ).catch(
                    () => {}
                );
            }

            window.dispatchEvent(
                new CustomEvent(
                    "eagle:scanner-status",
                    {
                        detail:
                            payload.scanner_status
                            || {}
                    }
                )
            );

            return payload;

        } catch (error) {

            renderEmptyState(
                error.message
                || (
                    "Signals could "
                    + "not be loaded."
                )
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
            || !api.scanRefresh
        ) {
            return;
        }

        elements.manualRefreshButton
            .disabled =
            true;

        elements.manualRefreshButton
            .textContent =
            "Starting...";

        try {

            const response =
                await fetch(
                    api.scanRefresh,
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

                        body:
                            JSON.stringify(
                                {
                                    mode:
                                        state.mode
                                }
                            )
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
                    || (
                        "Scanner could "
                        + "not be started."
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
                        detail:
                            payload.scanner
                            || {}
                    }
                )
            );

        } catch (error) {

            window.alert(
                error.message
                || (
                    "Scanner could "
                    + "not be started."
                )
            );

        } finally {

            elements.manualRefreshButton
                .disabled =
                false;

            elements.manualRefreshButton
                .textContent =
                "Refresh Scan";
        }
    }


    // =========================================================
    // MODE CHANGE
    // =========================================================

    function setActiveMode(
        mode
    ) {
        const normalizedMode =
            normalizeMode(
                mode
            );

        if (
            state.mode
            === normalizedMode
        ) {
            return;
        }

        state.mode =
            normalizedMode;

        state.results =
            [];

        state.topSectors =
            [];

        state.sectorStocks =
            [];

        state.selectedSector =
            "";

        state.signalsInitialized =
            false;

        state.knownStrongBuySymbols =
            new Set();

        document.querySelectorAll(
            ".timeframe-tab"
        ).forEach(
            (button) => {

                const buttonMode =
                    button.dataset.mode
                    || button.dataset
                        .timeframe;

                button.classList.toggle(
                    "active",
                    buttonMode
                    === normalizedMode
                );
            }
        );

        const sectorSection =
            document.getElementById(
                "sectorStockSection"
            );

        if (
            sectorSection
        ) {
            sectorSection.hidden =
                true;
        }

        const url =
            new URL(
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

        fetchSignals().catch(
            () => {}
        );
    }


    // =========================================================
    // FILTERS
    // =========================================================

    function bindFilters() {

        elements.sectorFilter
            ?.addEventListener(
                "change",
                (event) => {

                    state.filters.sector =
                        event.target.value;

                    renderTable();
                }
            );


        elements
            .technicalScoreFilter
            ?.addEventListener(
                "change",
                (event) => {

                    state.filters
                        .minimumTechnicalScore =
                        event.target.value;

                    renderTable();
                }
            );


        elements.patternFilter
            ?.addEventListener(
                "change",
                (event) => {

                    state.filters
                        .chartPattern =
                        event.target.value;

                    renderTable();
                }
            );


        elements
            .resetFiltersButton
            ?.addEventListener(
                "click",
                () => {

                    state.filters = {
                        sector: "",
                        minimumTechnicalScore:
                            "",
                        chartPattern: ""
                    };

                    if (
                        elements.sectorFilter
                    ) {
                        elements.sectorFilter
                            .value =
                            "";
                    }

                    if (
                        elements
                            .technicalScoreFilter
                    ) {
                        elements
                            .technicalScoreFilter
                            .value =
                            "";
                    }

                    if (
                        elements.patternFilter
                    ) {
                        elements.patternFilter
                            .value =
                            "";
                    }

                    renderTable();
                }
            );
    }


    // =========================================================
    // MODE BINDING
    // =========================================================

    function bindModes() {
        elements.timeframeTabs
            ?.addEventListener(
                "click",
                (event) => {

                    const button =
                        event.target.closest(
                            ".timeframe-tab"
                        );

                    if (!button) {
                        return;
                    }

                    setActiveMode(
                        button.dataset.mode
                        || button.dataset
                            .timeframe
                    );
                }
            );
    }


    // =========================================================
    // DRAWER BINDING
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
                    event.key
                    === "Escape"
                    && state.drawerOpen
                ) {
                    closeDrawer();
                }
            }
        );
    }


    // =========================================================
    // STATUS EVENT
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
    // INITIALIZE
    // =========================================================

    function initialize() {
        state.mode =
            normalizeMode(
                state.mode
            );

        ensureSectorStockPanel();

        bindFilters();

        bindModes();

        bindDrawer();

        bindDetailButtons();

        bindScannerStatusEvent();

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

        fetchSectorStocks,

        selectSector,

        loadStockDetail,

        renderTable,

        renderTopSectors,

        renderSectorStocks,

        renderScannerStatus,

        setActiveMode,

        speakStrongBuy
    };


    document.addEventListener(
        "DOMContentLoaded",
        initialize
    );

})();
