function loadTipsContent() {
    const contentContainer = document.getElementById('tips-content');
    if (!contentContainer) {
        console.error('Content container not found');
        return;
    }

    if (typeof DOMPurify === 'undefined' || typeof DOMPurify.sanitize !== 'function') {
        contentContainer.textContent = t('Tips temporarily unavailable. Please refresh the page.');
        console.error('DOMPurify unavailable — refusing to render unsanitized content');
        return;
    }

    fetch('/tips/content')
        .then(response => {
            if (!response.ok) {
                throw new Error('Failed to load tips content: Network response was not OK');
            }
            return response.text();
        })
        .then(htmlContent => {
            contentContainer.innerHTML = DOMPurify.sanitize(htmlContent);
        })
        .catch(error => {
            contentContainer.textContent = t('Tips temporarily unavailable. Please refresh the page.');
            console.error('Error loading tips content:', error);
        });
}

window.loadTipsContent = loadTipsContent;


