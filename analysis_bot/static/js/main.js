document.addEventListener('DOMContentLoaded', () => {
    const analyzeBtn = document.getElementById('analyzeBtn');
    const tickerInput = document.getElementById('tickerInput');
    const stockGrid = document.getElementById('stockGrid');

    // 6 Hours in seconds
    const STALE_THRESHOLD = 6 * 60 * 60;

    function isFresh(timestamp) {
        if (!timestamp) return false;
        const now = Date.now() / 1000; // current time in seconds
        return (now - parseFloat(timestamp)) < STALE_THRESHOLD;
    }

    function filterCards() {
        const query = tickerInput.value.trim().toUpperCase();
        const cards = document.querySelectorAll('.stock-card');
        let exactMatchFresh = false;

        cards.forEach(card => {
            // Skip loading cards
            if (card.classList.contains('loading-card')) return;

            const ticker = (card.dataset.ticker || '').toUpperCase();
            const name = (card.dataset.name || '').toUpperCase();
            const sector = (card.dataset.sector || '').toUpperCase();
            const tags = (card.dataset.tags || '').toUpperCase();

            // If empty query, show all
            if (!query) {
                card.style.display = '';
                return;
            }

            // Fuzzy match inclusive
            const isMatch = ticker.includes(query) ||
                name.includes(query) ||
                sector.includes(query) ||
                tags.includes(query);

            if (isMatch) {
                card.style.display = ''; // Show
                // Check specific condition: Exact Ticker Match AND Fresh
                // If this is true, user doesn't need to analyze
                if (ticker === query && isFresh(card.dataset.timestamp)) {
                    exactMatchFresh = true;
                }
            } else {
                card.style.display = 'none'; // Hide
            }
        });

        // Update Button State
        if (exactMatchFresh) {
            analyzeBtn.textContent = 'Fresh Data Available';
            analyzeBtn.disabled = true;
            analyzeBtn.classList.add('btn-disabled'); // Optional styling
        } else {
            analyzeBtn.disabled = false;
            analyzeBtn.classList.remove('btn-disabled');
            if (query) {
                analyzeBtn.textContent = `Analyze ${query}`;
            } else {
                analyzeBtn.textContent = 'Analyze';
            }
        }
    }

    // Real-time filtering
    tickerInput.addEventListener('input', filterCards);

    // Enter key support
    tickerInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            if (!analyzeBtn.disabled) {
                analyzeBtn.click();
            }
        }
    });

    analyzeBtn.addEventListener('click', async () => {
        const ticker = tickerInput.value.trim().toUpperCase();
        if (!ticker) return;

        // Double check freshness just in case
        const existingCard = document.getElementById(`card-${ticker}`);
        if (existingCard && isFresh(existingCard.dataset.timestamp)) {
            // Visual cue - scroll to it
            existingCard.scrollIntoView({ behavior: 'smooth', block: 'center' });
            existingCard.classList.add('highlight'); // Add some CSS for flash
            setTimeout(() => existingCard.classList.remove('highlight'), 1000);
            return;
        }

        // Proceed to Analyze
        analyzeBtn.disabled = true;
        analyzeBtn.textContent = 'Analyzing...';
        tickerInput.disabled = true;

        const tempCard = document.createElement('div');
        tempCard.className = 'stock-card loading-card';
        tempCard.innerHTML = `<div class="loader"></div><div style="text-align:center; margin-top:10px">Loading ${ticker}...</div>`;
        stockGrid.prepend(tempCard);

        try {
            const response = await fetch(`/analyze/${ticker}`, {
                method: 'POST'
            });
            const result = await response.json();

            if (result.error) {
                alert(`Error: ${result.error}`);
                tempCard.remove();
            } else {
                tempCard.remove();
                addOrUpdateCard(result);
                // Re-run filter to ensure it shows up and button state updates
                filterCards();
            }
        } catch (err) {
            console.error(err);
            alert('Analysis Failed');
            tempCard.remove();
        } finally {
            analyzeBtn.disabled = false;
            if (tickerInput.value) {
                analyzeBtn.textContent = `Analyze ${tickerInput.value}`;
            } else {
                analyzeBtn.textContent = 'Analyze';
            }
            tickerInput.disabled = false;
            // Keep input value so user can filter what they just searched
        }
    });

    function addOrUpdateCard(data) {
        const existing = document.getElementById(`card-${data.ticker}`);
        if (existing) existing.remove();

        const card = document.createElement('div');
        card.className = 'stock-card';
        card.id = `card-${data.ticker}`;

        // Add Data Attributes
        card.dataset.ticker = data.ticker;
        card.dataset.name = data.data_preview.name || '';
        card.dataset.sector = data.data_preview.sector || '';
        card.dataset.tags = data.tags || ''; // Backend should return tags
        // Timestamp: Python returns ISO usually in data_preview? Or we need to ask backend for timestamp.
        // The /analyze endpoint returns 'last_updated' in data_preview as ISO string
        // We need epoch seconds.
        const ts = data.data_preview.last_updated ? new Date(data.data_preview.last_updated).getTime() / 1000 : Date.now() / 1000;
        card.dataset.timestamp = ts;

        card.innerHTML = `
            <div class="card-header">
                <span class="ticker">${data.data_preview.name || data.ticker}</span>
                <span class="price">${data.data_preview.price || '--'}</span>
            </div>
            <div class="card-body">
                <div class="name">${data.ticker}</div>
                <div class="sector">${data.data_preview.sector || '--'}</div>
            </div>
            <div class="card-footer">
                <span class="last-updated">Analyzed: ${new Date(ts * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
                <span class="status-badge updated">✅ Active</span>
            </div>
            <a href="/stock/${data.ticker}" class="details-link-overlay"
                style="position:absolute; top:0; left:0; width:100%; height:100%;"></a>
        `;

        // Remove empty state if present
        const emptyState = document.querySelector('.empty-state');
        if (emptyState) emptyState.remove();

        stockGrid.prepend(card);
    }
});
