function loadTipsContent() {
    fetch('/tips/content')
        .then(response => {
            if (!response.ok) {
                throw new Error('Failed to load tips content: Network response was not OK');
            }
            return response.text();
        })
        .then(htmlContent => {
            const contentContainer = document.getElementById('tips-content');
            if (contentContainer) {
                contentContainer.innerHTML = htmlContent;
            } else {
                console.error('Content container not found');
            }
        })
        .catch(error => console.error('Error loading tips content:', error));
}

window.loadTipsContent = loadTipsContent;


