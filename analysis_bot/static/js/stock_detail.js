document.addEventListener('DOMContentLoaded', () => {
    const refreshBtn = document.getElementById('refreshBtn');

    if (refreshBtn) {
        refreshBtn.addEventListener('click', async () => {
            const ticker = refreshBtn.getAttribute('data-ticker');
            if (!ticker) return;

            // UI Feedback
            refreshBtn.disabled = true;
            refreshBtn.textContent = 'Refreshing...';
            const originalText = 'Force Refresh';

            try {
                // Call API with force=true
                const response = await fetch(`/analyze/${ticker}?force=true`, {
                    method: 'POST'
                });
                const result = await response.json();

                if (result.error) {
                    alert(`Error: ${result.error}`);
                    refreshBtn.disabled = false;
                    refreshBtn.textContent = originalText;
                } else {
                    // Success -> Reload to show new data/report
                    window.location.reload();
                }
            } catch (err) {
                console.error(err);
                alert('Refresh Failed');
                refreshBtn.disabled = false;
                refreshBtn.textContent = originalText;
            }
        });
    }
});
