// Map Dark mode     
window.addEventListener('themeChanged', (event) => {
    if (!mymap) return; 

    const { isDarkMode } = event.detail;
    
    if (isDarkMode) {
        if (mymap.hasLayer(lightTileLayer)) {
            mymap.removeLayer(lightTileLayer);
        }
        mymap.addLayer(darkTileLayer);
    } else {
        if (mymap.hasLayer(darkTileLayer)) {
            mymap.removeLayer(darkTileLayer);
        }
        mymap.addLayer(lightTileLayer);
    }
});

document.addEventListener('DOMContentLoaded', () => {
    // Map layer based on initial theme
    const isDarkMode = document.documentElement.classList.contains('dark');
    
    if (isDarkMode) {
        mymap.addLayer(darkTileLayer);
        if (mymap.hasLayer(lightTileLayer)) {
            mymap.removeLayer(lightTileLayer);
        }
    } else {
        mymap.addLayer(lightTileLayer);
        if (mymap.hasLayer(darkTileLayer)) {
            mymap.removeLayer(darkTileLayer);
        }
    }
});
