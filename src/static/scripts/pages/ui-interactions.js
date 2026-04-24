// map.html
updateDynamicContent()

let mymap = L.map('mapid').setView([52.231, 21.004], 7); //  default location and zoom level

const lightTileLayer = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; <a href="www.openstreetmap.org/copyright">OpenStreetMap contributors</a>'
}).addTo(mymap);

const darkTileLayer = L.tileLayer('https://tiles.stadiamaps.com/tiles/alidade_smooth_dark/{z}/{x}/{y}{r}.png', {
    attribution: '&copy; <a href="https://www.stadiamaps.com/" target="_blank">Stadia Maps</a> &copy; <a href="https://openmaptiles.org/" target="_blank">OpenMapTiles</a> &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
});

const satelliteLayer = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
    attribution: 'Tiles &copy; Esri'
});

// Layer control for map styles
const baseMaps = {
    "Street": lightTileLayer,
    "Dark": darkTileLayer,
    "Satellite": satelliteLayer
};
L.control.layers(baseMaps, null, { position: 'topright' }).addTo(mymap);

const greenIcon = new L.Icon({ 
iconUrl: 'static/css/images/marker-icon-green.png', shadowUrl: 'static/css/images/marker-shadow.png', iconSize: [25, 41], iconAnchor: [12, 41], popupAnchor: [1, -34], shadowSize: [41, 41]
});

const providerColors = {
    'P4 sp. z o.o.': 'violet', // purple/violet marker for Play
    'Orange Polska S.A.': 'orange',
    'T-Mobile Polska S.A.': 'red',
    'Polkomtel sp. z o.o.': 'green'
};

const providerClasses = {
    'P4 sp. z o.o.': 'play',
    'Orange Polska S.A.': 'orange',
    'T-Mobile Polska S.A.': 'tmobile',
    'Polkomtel sp. z o.o.': 'plus'
};

const providerShortNames = {
    'P4 sp. z o.o.': 'Play',
    'Orange Polska S.A.': 'Orange',
    'T-Mobile Polska S.A.': 'T-Mobile',
    'Polkomtel sp. z o.o.': 'Plus'
};

let selectedStationIndex = null;

const initialFilters = () => ({
    lat: null,
    lng: null,
    limit: null,
    maxDistance: null,
    serviceProvider: [],
    frequencyBands: [],
    mode: 'all' // 'all', 'nearest', 'withinDistance'
});

let locationSetInitially = false;
let currentFilters = initialFilters();
let stationMarkers = [];
let marker;
let userSubmittedLocation = null;
let countryBoundaries;
let isFirstClick = true;
let currentBand = 'low';
let connectionLine = null;

const frequencyRanges = {
    high: [200, 500, 1000, 1500], // high band frequency distance radius
    mid: [300, 750, 1500, 2000], //  mid band frequency
    low: [500, 1500, 3000, 5000] // low band frequency
};

const frequencyRangecolors = ['green', 'yellow', 'orange', 'red'];

window.onload = hideSidebar; // Hide the sidebar initially

globalFetch('/static/PL-administrative-boundaries.json')
.then(data => {
    countryBoundaries = L.geoJson(data, {
    style: function (feature) {
        return {
            fillColor: 'transparent',
            fill: false,
            color: '#4a90e2',
            weight: 2
        };
    }
}).addTo(mymap);
});

mymap.on('click', function(e) {
    // Ignore clicks originating from map controls (zoom buttons, GPS, filters)
    if (e.originalEvent && e.originalEvent.target) {
        const target = e.originalEvent.target;
        if (target.closest('.leaflet-control')) {
            return;
        }
    }

    let coord = e.latlng;
    let lat = coord.lat;
    let lng = coord.lng;

    // Clear existing marker,
    if (marker) {
        mymap.removeLayer(marker);
    }

    // marker to show where you clicked.
    marker = L.marker([lat, lng], {icon: greenIcon}).addTo(mymap);
    currentFilters.lat = lat;
    currentFilters.lng = lng;
    if (isFirstClick) {
        sendLocation(lat, lng);
        isFirstClick = false;
    } else {
        fetchStations();
    }
});

function setupTouchInteraction(mymap) {
    let isInteracting = false;
    const interactionStarted = () => isInteracting = true;
    const interactionEnded = () => setTimeout(() => isInteracting = false, 500);

    mymap.on('touchstart', interactionStarted);
    mymap.on('touchmove', interactionStarted); // Touchmove for pinch or drag
    mymap.on('touchend', interactionEnded); // Detect end
    mymap.on('click', function(e) {
        if (isInteracting) {
            e.originalEvent.preventDefault();
        }
    });
    // Disable zoom on double tap
    mymap.doubleClickZoom.disable();

    // Prevent zoom control clicks from propagating to the map on mobile
    const zoomControl = document.querySelector('.leaflet-control-zoom');
    if (zoomControl) {
        L.DomEvent.disableClickPropagation(zoomControl);
        L.DomEvent.on(zoomControl, 'touchstart touchend', L.DomEvent.stopPropagation);
    }
}
setupTouchInteraction(mymap);

let gpsButton = L.control({position: 'topleft'});
gpsButton.onAdd = function(map) {
    let div = L.DomUtil.create('div', 'gps-location-control');
    div.innerHTML = `
        <button id="useMyLocationBtn" title="Use My Location" class="map-control-btn">
            <span class="control-icon">📍</span>
            <span class="control-label">GPS</span>
        </button>
    `;
    L.DomEvent.on(div, 'click', function(e) {
        L.DomEvent.stop(e);
        const btn = document.getElementById('useMyLocationBtn');
        btn.classList.add('collapsed');
        requestAndSendGPSLocation();
    });
    return div;
};
gpsButton.addTo(mymap);

let frequencyRangeLegend = L.control({position: 'topleft'});

    frequencyRangeLegend.onAdd = function(map) {
        let div = L.DomUtil.create('div', 'gps-location-control');
        div.style.cursor = 'grab';
        div.style.userSelect = "none"; 
        div.style.position = 'absolute';
        div.style.top = '112px';
        div.style.left = '0px';

        let toggleBtn = L.DomUtil.create('button', 'map-control-btn', div);
        toggleBtn.id = 'toggleFrequencyRangeLegendBtn';
        toggleBtn.title = 'Signal Range Legend';
        toggleBtn.innerHTML = `
            <span class="control-icon text-green-500 text-lg">◎</span>
            <span class="control-label">Range</span>
        `;

        let legendDiv = L.DomUtil.create('div', 'frequency-range-container bg-white p-1 rounded shadow text-black dark:bg-black dark:text-white w-76 accent-blue-500 dark:accent-gray-400', div);
        legendDiv.innerHTML = `
            <table class="frequency-table min-w-full divide-y divide-gray-200">
                <thead class="text-gray-700 font-bold dark:text-white">
                    <tr>
                        <th>Signal Strength</th>
                        <th class="column-high" data-band="high">High Band Frequency<br>(5G3600, L2600) (km)</th>
                        <th class="column-mid" data-band="mid">Mid Band Frequency <br>(5G/L2100, L1800) (km)</th>
                        <th class="column-low" data-band="low">Low Band Frequency<br>(L900, L800, G900) (km)</th>
                    </tr>
                </thead>
                <tbody class="text-gray-700 font-bold dark:text-white divide-y divide-gray-200">
                    <tr class="bg-green-600 dark:bg-green-700"><td>Excellent</td><td>0.2</td><td>0.3</td><td>0.5</td></tr>
                    <tr class="bg-yellow-300 dark:bg-yellow-400"><td>Good</td><td>0.5</td><td>0.75</td><td>1.5</td></tr>
                    <tr class="bg-orange-400 dark:bg-orange-400"><td>Fair</td><td>1.0</td><td>1.5</td><td>3.0</td></tr>
                    <tr class="bg-red-500 dark:bg-red-600"><td>Poor</td><td>1.5</td><td>2.0</td><td>5.0</td></tr>
                </tbody>
            </table>
        `;
        legendDiv.querySelectorAll('th[data-band]').forEach(th => {
            L.DomEvent.on(th, 'click', function(e) {
                L.DomEvent.stop(e);
                changeFrequency(th.getAttribute('data-band'));
            });
        });

        L.DomEvent.on(toggleBtn, 'click', function() {
            legendDiv.classList.toggle('hidden');
            toggleBtn.classList.add('collapsed');
        });

        // Make draggable 
        let startPos = null;
        const onDragStart = function(e) {
            startPos = { x: e.clientX, y: e.clientY };
            div.style.cursor = 'grabbing';
            document.addEventListener('mousemove', onDragMove);
            document.addEventListener('mouseup', onDragEnd);
        };

        const onDragMove = function(e) {
            if (startPos) {
                let xDiff = e.clientX - startPos.x;
                let yDiff = e.clientY - startPos.y;

                // Calculate new position based on the difference
                let newLeft = parseInt(div.style.left, 10) + xDiff;
                let newTop = parseInt(div.style.top, 10) + yDiff;

                // Get map container's dimensions to constrain the movement
                let mapContainer = mymap.getContainer();
                let maxLeft = mapContainer.offsetWidth - div.offsetWidth;
                let maxTop = mapContainer.offsetHeight - div.offsetHeight;

                // Apply constraints
                newLeft = Math.max(0, Math.min(newLeft, maxLeft));
                newTop = Math.max(0, Math.min(newTop, maxTop));

                div.style.left = newLeft + 'px';
                div.style.top = newTop + 'px';

                // Update startPos for the next call
                startPos = { x: e.clientX, y: e.clientY };
            }
        };

        const onDragEnd = function() {
            document.removeEventListener('mousemove', onDragMove);
            document.removeEventListener('mouseup', onDragEnd);
            div.style.cursor = 'grab';
        };

        L.DomEvent.on(div, 'mousedown', onDragStart);
        L.DomEvent.disableClickPropagation(div);
        L.DomEvent.on(div, 'mousewheel', L.DomEvent.stopPropagation);

        return div;
};

frequencyRangeLegend.addTo(mymap);

let btsCountControl = L.control({position: 'bottomleft'});
btsCountControl.onAdd = function(map) {
    let div = L.DomUtil.create('div', '');
    div.className = 'bg-white p-2 dark:mt-[-4.5rem] dark:md:mt-0 rounded shadow text-black dark:bg-gray-800 dark:hover:bg-gray-500 dark:text-white';
    div.innerHTML = 'BTS count: <span id="btsCounter">0</span>';
    return div;
}
btsCountControl.addTo(mymap);

let filterControl = L.control({position: 'topright'});
filterControl.onAdd = function(map) {
    let div = L.DomUtil.create('div', 'filter-control-container');
    div.innerHTML = `
        <button id="toggle-filters-btn" class="bg-blue-500 hover:bg-blue-700 dark:bg-gray-800 dark:hover:bg-gray-500 text-white dark:text-white font-bold py-1 px-2 rounded w-76">
        Toggle Filters
        </button>

        <button id="reset-filters-btn" class="bg-blue-500 hover:bg-blue-700 dark:bg-gray-800 dark:hover:bg-gray-500 text-white dark:text-white font-bold py-1 px-2 rounded w-76">
        Reset Filters
        </button>

        <div id="filterContainer" class="bg-white p-1 rounded shadow text-black dark:bg-black dark:text-white w-76 accent-blue-500 dark:accent-gray-400 hidden">
            <div class="static-content">
                <div class="my-2">
                    <p class="text-gray-700 font-bold dark:text-white">Service Provider:</p>
                    <div class="flex flex-wrap label-container gap-1">    
                        <label><input type="checkbox" name="service_provider" value="P4 Sp. z o.o.'"> Play</label>
                        <label><input type="checkbox" name="service_provider" value="Orange Polska S.A."> Orange</label>
                        <label><input type="checkbox" name="service_provider" value="T-Mobile Polska S.A."> T-Mobile</label>
                        <label><input type="checkbox" name="service_provider" value="POLKOMTEL Sp. z o.o."> Plus</label>
                    </div>
                </div>

                <div class="my-2">
                    <p class="text-gray-700 font-bold dark:text-white">Frequency:</p>
                    <div class="grid grid-cols-2 md:grid-cols-3 gap-1">
                        <label><input type="checkbox" name="frequency_bands" value="5G3600"> 5G3600</label>
                        <label><input type="checkbox" name="frequency_bands" value="5G2100"> 5G2100</label>
                        <label><input type="checkbox" name="frequency_bands" value="5G1800"> 5G1800</label>
                        <label><input type="checkbox" name="frequency_bands" value="5G700"> 5G700</label>
                        <label><input type="checkbox" name="frequency_bands" value="LTE2600"> LTE2600</label>
                        <label><input type="checkbox" name="frequency_bands" value="LTE2100"> LTE2100</label>
                        <label><input type="checkbox" name="frequency_bands" value="LTE1800"> LTE1800</label>
                        <label><input type="checkbox" name="frequency_bands" value="LTE900"> LTE900</label>
                        <label><input type="checkbox" name="frequency_bands" value="LTE800"> LTE800</label>
                        <label><input type="checkbox" name="frequency_bands" value="LTE700"> LTE700</label>
                        <label><input type="checkbox" name="frequency_bands" value="UMTS2100"> UMTS2100</label>
                        <label><input type="checkbox" name="frequency_bands" value="UMTS900"> UMTS900</label>
                        <label><input type="checkbox" name="frequency_bands" value="GSM1800"> GSM1800</label>
                        <label><input type="checkbox" name="frequency_bands" value="GSM900"> GSM900</label>
                    </div>
                </div>

                <button id="apply-filters" class="apply-filters-btn mt-2 w-full text-white bg-blue-300 dark:bg-gray-700 hover:bg-blue-500 dark:hover:bg-gray-500 rounded">
                    Apply Filters
                </button>

                <div class="slider-container my-2">
                    <div class="flex justify-between items-center">
                        <button id="showNearestBtn" class="mt-2 w-48 text-white bg-blue-300 dark:bg-gray-700 hover:bg-blue-500 dark:hover:bg-gray-500 rounded">Show Nearest BTS</button>
                    </div>
                    <input type="number" id="nearestBtsRange" min="1" max="10" placeholder="" class="w-[4.25rem] mt-1 bg-blue-100 hover:bg-blue-300 dark:bg-gray-700 dark:hover:bg-gray-500">
                </div>

                <div class="slider-container my-2">
                    <div class="flex justify-between items-center">
                        <button id="showWithinDistanceBtn" class="mt-2 w-48 text-white bg-blue-300 dark:bg-gray-700 hover:bg-blue-500 dark:hover:bg-gray-500 rounded">Show BTS Within Distance</button>
                    </div>
                    <input type="number" id="withinDistanceRange" min="0.0" max="10" step="0.1" placeholder="" class="w-[4.25rem] mt-1 bg-blue-100 hover:bg-blue-300 dark:bg-gray-700 dark:hover:bg-gray-500">
                </div>

                <div id="dynamicContent">
                
                </div>
            </div> 
        </div>
        
    `; 
    L.DomEvent.disableClickPropagation(div);
    L.DomEvent.on(div, 'mousewheel', L.DomEvent.stopPropagation);
    
    return div;
    };

filterControl.addTo(mymap);

document.getElementById('toggle-filters-btn').addEventListener('click', function() {
        let filterContainer = document.getElementById('filterContainer');
        filterContainer.classList.toggle('hidden');
        });

document.getElementById('reset-filters-btn').addEventListener('click', resetFiltersUI); {
};        

document.getElementById('apply-filters').addEventListener('click', function() {
    let frequencyBands = Array.from(document.querySelectorAll('input[name="frequency_bands"]:checked')).map(el => el.value);
    let serviceProvider = Array.from(document.querySelectorAll('input[name="service_provider"]:checked')).map(el => el.value);
    
    currentFilters.serviceProvider = serviceProvider;
    currentFilters.frequencyBands = frequencyBands;
    currentFilters.nearestBts = document.getElementById('nearestBtsRange').value;
    currentFilters.distance = document.getElementById('withinDistanceRange').value;
    currentFilters.mode = 'all'; // Reset to 'all'

    checkAndSetInitialLocation();
    fetchStations();
})

setTimeout(() => {

    document.getElementById('showNearestBtn').addEventListener('click', function() {
        currentFilters.mode = 'nearest';
        currentFilters.limit = nearestBtsRange.value;

        checkAndSetInitialLocation();
        fetchStations();
    });

    document.getElementById('showWithinDistanceBtn').addEventListener('click', function() {
        currentFilters.mode = 'withinDistance';
        currentFilters.maxDistance = withinDistanceRange.value;

        checkAndSetInitialLocation();
        fetchStations();
    });
}, 0);

function requestAndSendGPSLocation() {
    // Leaflet's locate to find the user's position
    mymap.locate({ setView: true, maxZoom: 7, enableHighAccuracy: true, timeout: 10000, maximumAge: 0 });
    mymap.on('locationfound', function(e) {
        let userLat = e.latlng.lat;
        let userLng = e.latlng.lng;
        gpsMarker = L.marker([userLat, userLng], {icon: greenIcon}).addTo(mymap).bindPopup(`<div class=" dark:text-white">Your Location</div>`).openPopup();
        sendLocation(userLat, userLng);
    });

    mymap.on('locationerror', function(e) {

        if (e.message.includes("denied")) {
            showToast('Location permission was denied. Please enable it to use this feature.', 'error');
        } else if (e.message.includes("unavailable")) {
            showToast('Location information is currently unavailable.', 'error');
        } else if (e.message.includes("timeout")) {
            showToast('The request to get your location timed out. Please try again.', 'error');
        } else {
            showToast('An unknown location error occurred. ' + e.message, 'error');
        }
    });
}

function checkAndSetInitialLocation() {
    if (!locationSetInitially) {
        const center = mymap.getCenter();
        currentFilters.lat = center.lat;
        currentFilters.lng = center.lng;
    }
}

function updateBTSCount(count) {
    let btsCounter = document.getElementById('btsCounter');
    if (btsCounter) {
        btsCounter.textContent = count;
    }
}

function clearBTSCount(count) {
    let btsCounter = document.getElementById('btsCounter')
    btsCounter.textContent = 0;
}

function sendLocation(lat, lng, limit = 9, max_distance = null) {
    currentFilters.lat = lat;
    currentFilters.lng = lng;
    currentFilters.limit = limit;
    currentFilters.maxDistance = max_distance;
    locationSetInitially = true;

    showLoadingSkeleton();
    let url = `/submit_location`;
    const userSubmittedLocation = { lat: lat, lng: lng };
    const requestData = {
        lat: lat,
        lng: lng,
        limit: limit,
        max_distance: max_distance
    };

    const messageBox = document.getElementById('messageBox');
    const sidebar = document.getElementById('sidebar');

    // Pulled out so both the success branch and the .catch fallback
    // (network error, 5xx) leave the user with a clean sidebar instead
    // of the indefinite skeleton.
    const clearSkeletonAndCount = () => {
        sidebar.innerHTML = '';
        updateBTSCount(0);
    };

    const showOutsidePolandToast = () => {
        clearSkeletonAndCount();
        messageBox.classList.remove('hidden');
        setTimeout(() => {
            messageBox.classList.add('hidden');
            mymap.zoomOut(4);
        }, 7700);
    };

    globalFetch(url, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRF-Token': getCsrfToken()
        },
        body: JSON.stringify(requestData)
    })
    .then(data => {
        // Backend signals out-of-PL with `outside_pl: true` (and an
        // empty stations[] so the API contract stays consistent).
        // Treat both that flag AND the local geometry check as "outside"
        // — flag wins, geometry is a defensive fallback in case the
        // bounds disagree slightly.
        const outside =
            (data && data.outside_pl === true) ||
            !countryBoundaries.getBounds().contains(userSubmittedLocation);
        if (outside) {
            showOutsidePolandToast();
            return;
        }
        messageBox.classList.add('hidden');
        if (data && Array.isArray(data.stations)) {
            updateBTSCount(data.count);
            showSidebar();
            displayStations(data.stations);
            addRingsForLocation(lat, lng);
            applyFrequencyColors();
            scrollToSidebar();
        } else {
            // Got a 200 with no stations payload — clear skeleton so the
            // user doesn't stare at the loading state forever.
            clearSkeletonAndCount();
        }
    })
    .catch(err => {
        // Network failure / 5xx / globalFetch threw on non-2xx. The
        // sidebar must come out of the loading state regardless of
        // whether we render anything else.
        console.error('submit_location failed:', err);
        if (!countryBoundaries.getBounds().contains(userSubmittedLocation)) {
            // Pre-fix backend (or stale Cloud Run revision) returned 400
            // for outside-PL — fall back to the geometry check so the
            // toast still shows for users on the old deploy.
            showOutsidePolandToast();
        } else {
            clearSkeletonAndCount();
        }
    });
}

function showSidebar() {
    let sidebar = document.getElementById('sidebar');
    sidebar.classList.remove('hidden');
}

function scrollToSidebar() {
    let sidebar = document.getElementById('sidebar');
    if (sidebar && window.innerWidth < 768) {
        setTimeout(function() {
            sidebar.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }, 2000);
    }
}

function hideSidebar() {
    let sidebar = document.getElementById('sidebar');
    sidebar.classList.add('hidden');
    
}

function clearStationMarkers() { // clearing markers when new location is submitted
    for (let i = 0; i < stationMarkers.length; i++) {
        mymap.removeLayer(stationMarkers[i]);
    }
    stationMarkers = []; // Reset the array
    clearConnectionLine();
}

// Draw line from user location to a station
function drawConnectionLine(stationLat, stationLng) {
    clearConnectionLine();
    if (currentFilters.lat && currentFilters.lng) {
        connectionLine = L.polyline([
            [currentFilters.lat, currentFilters.lng],
            [stationLat, stationLng]
        ], {
            color: '#3b82f6',
            weight: 3,
            opacity: 0.7,
            dashArray: '10, 10',
            className: 'connection-line'
        }).addTo(mymap);
    }
}

// Clear the connection line
function clearConnectionLine() {
    if (connectionLine) {
        mymap.removeLayer(connectionLine);
        connectionLine = null;
    }
}

function showLoadingSkeleton() {
    let sidebarContent = document.getElementById('sidebar');
    sidebarContent.innerHTML = '';
    sidebarContent.classList.remove('hidden');

    // Show 3 skeleton cards
    for (let i = 0; i < 3; i++) {
        let skeleton = document.createElement('div');
        skeleton.className = 'skeleton-card';
        skeleton.innerHTML = `
            <div class="skeleton-line skeleton-title"></div>
            <div class="skeleton-line skeleton-text"></div>
            <div class="skeleton-line skeleton-text-short"></div>
            <div class="skeleton-line skeleton-text"></div>
            <div class="skeleton-line skeleton-text-short"></div>
        `;
        sidebarContent.appendChild(skeleton);
    }
}

// Calculate signal strength level based on distance and currently selected frequency band
// Uses currentBand (low/mid/high) to match the ring visualization on the map
function getSignalStrength(distance) {
    const thresholds = frequencyRanges[currentBand];
    const distanceMeters = distance * 1000;

    if (distanceMeters <= thresholds[0]) return { level: 'excellent', bars: 4, label: 'Excellent' };
    if (distanceMeters <= thresholds[1]) return { level: 'good', bars: 3, label: 'Good' };
    if (distanceMeters <= thresholds[2]) return { level: 'fair', bars: 2, label: 'Fair' };
    return { level: 'poor', bars: 1, label: 'Poor' };
}

// Calculate bearing from user location to station
function calculateBearing(lat1, lng1, lat2, lng2) {
    const toRad = deg => deg * Math.PI / 180;
    const toDeg = rad => rad * 180 / Math.PI;

    const dLng = toRad(lng2 - lng1);
    const y = Math.sin(dLng) * Math.cos(toRad(lat2));
    const x = Math.cos(toRad(lat1)) * Math.sin(toRad(lat2)) -
              Math.sin(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.cos(dLng);

    let bearing = toDeg(Math.atan2(y, x));
    return (bearing + 360) % 360;
}

// Get compass direction from bearing
function getCompassDirection(bearing) {
    const directions = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'];
    const index = Math.round(bearing / 45) % 8;
    return directions[index];
}

// Copy to clipboard helper
function copyToClipboard(text, button) {
    navigator.clipboard.writeText(text).then(() => {
        const originalText = button.innerHTML;
        button.innerHTML = '✓';
        button.style.color = '#22c55e';
        setTimeout(() => {
            button.innerHTML = originalText;
            button.style.color = '';
        }, 1500);
    }).catch(err => {
        console.error('Failed to copy:', err);
    });
}

// Generate signal bars HTML
function createSignalBars(signal) {
    let barsHtml = '';
    for (let i = 1; i <= 4; i++) {
        const active = i <= signal.bars ? 'active' : '';
        barsHtml += `<div class="signal-bar ${active}"></div>`;
    }
    return `<div class="signal-indicator signal-${signal.level}">${barsHtml}</div>`;
}

// Show empty state when no stations found
function showEmptyState() {
    let sidebarContent = document.getElementById('sidebar');
    sidebarContent.innerHTML = `
        <div class="empty-state col-span-full">
            <div class="empty-state-icon">📡</div>
            <div class="empty-state-title">No stations found</div>
            <div class="empty-state-text">Try adjusting your filters or clicking a different location on the map.</div>
        </div>
    `;
    sidebarContent.classList.remove('hidden');
}

function displayStations(data) {
    clearStationMarkers(); // Clear existing markers
    clearRings();
    selectedStationIndex = null;
    let sidebarContent = document.getElementById('sidebar');
    sidebarContent.innerHTML = ''; // Clear existing sidebar content (and skeletons)
    let stations;
    let bounds = [];

    if (Array.isArray(data)) {
        stations = data;
    } else if (data && Array.isArray(data.stations)) {
        stations = data.stations;
    }

    // Handle empty results
    if (!stations || stations.length === 0) {
        showEmptyState();
        return;
    }

    // Add stats panel
    const statsPanel = createStatsPanel(stations);
    sidebarContent.appendChild(statsPanel);

    stations.forEach((station, index) => {
        addStationMarker(station, index);
        addStationInfoToSidebar(station, index, sidebarContent);

        let latLng = L.latLng(station.latitude, station.longitude);
        bounds.push(latLng);
    });

    function updateBTSView(bounds) {
        if (bounds.length > 0) {
            let boundsLatLng = L.latLngBounds(bounds);
            mymap.fitBounds(boundsLatLng, { padding: [50, 50] });
            let currentZoom = mymap.getZoom();
            let newZoom = currentZoom - 1;
            if (newZoom < currentZoom) {
                mymap.setZoom(newZoom);
            }
        }
    }
    updateBTSView(bounds);
}

// Store stations for quick access
let currentStations = [];

// Create stats panel showing summary of stations
function createStatsPanel(stations) {
    currentStations = stations;
    const totalStations = stations.length;
    const avgDistance = (stations.reduce((sum, s) => sum + s.distance, 0) / totalStations).toFixed(2);
    const nearestStation = stations.reduce((min, s) => s.distance < min.distance ? s : min, stations[0]);
    const nearestIndex = stations.findIndex(s => s === nearestStation);
    const nearestSignal = getSignalStrength(nearestStation.distance);
    const providerShort = providerShortNames[nearestStation.service_provider] || nearestStation.service_provider;
    const providerClass = providerClasses[nearestStation.service_provider] || '';

    // Count providers
    const providerCounts = {};
    stations.forEach(s => {
        const shortName = providerShortNames[s.service_provider] || s.service_provider;
        providerCounts[shortName] = (providerCounts[shortName] || 0) + 1;
    });

    const providerBadges = Object.entries(providerCounts).map(([name, count]) => {
        const cssClass = escapeHtml(name.toLowerCase().replace('-', ''));
        return `<span class="inline-flex items-center"><span class="provider-dot ${cssClass}"></span>${escapeHtml(name)}: ${Number(count)}</span>`;
    }).join('');

    const panel = document.createElement('div');
    panel.className = 'stats-panel col-span-full';
    panel.innerHTML = `
        <div class="stats-grid">
            <div class="stat-item">
                <div class="stat-value">${Number(totalStations)}</div>
                <div class="stat-label">Stations</div>
            </div>
            <div class="stat-item">
                <div class="stat-value">${escapeHtml(avgDistance)}</div>
                <div class="stat-label">Avg Dist</div>
            </div>
            <div class="stat-item">
                <div class="stat-value">${nearestStation.distance.toFixed(2)}</div>
                <div class="stat-label">Nearest</div>
            </div>
            <div class="stat-item">
                <div class="stat-value flex justify-center">${createSignalBars(nearestSignal)}</div>
                <div class="stat-label">Best Signal</div>
            </div>
        </div>
        <div class="provider-summary">
            ${providerBadges}
        </div>
        <div class="nearest-quick-card" data-index="${Number(nearestIndex)}">
            <div class="quick-card-header">
                <span class="quick-card-badge">📍 Nearest</span>
                <span class="quick-card-arrow">→</span>
            </div>
            <div class="quick-card-content">
                <span class="provider-dot ${escapeHtml(providerClass)}"></span>
                <span class="font-medium">${escapeHtml(nearestStation.basestation_id)}</span>
                <span class="text-gray-500 dark:text-gray-400">•</span>
                <span>${escapeHtml(providerShort)}</span>
                <span class="text-gray-500 dark:text-gray-400">•</span>
                <span>${nearestStation.distance.toFixed(2)} km</span>
            </div>
        </div>
    `;

    // Add click handler for nearest station quick card
    const quickCard = panel.querySelector('.nearest-quick-card');
    quickCard.addEventListener('click', function() {
        const index = parseInt(this.dataset.index);
        navigateToStation(index);
    });

    return panel;
}

// Navigate to a station by index
function navigateToStation(index) {
    if (!currentStations[index]) return;
    const station = currentStations[index];

    // Remove previous selection
    document.querySelectorAll('.sidebar-item.selected').forEach(item => {
        item.classList.remove('selected');
    });

    // Select the sidebar item
    const sidebarItem = document.querySelector(`.sidebar-item[data-index="${index}"]`);
    if (sidebarItem) {
        sidebarItem.classList.add('selected');
        sidebarItem.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }

    selectedStationIndex = index;
    drawConnectionLine(station.latitude, station.longitude);

    // Open marker popup and pan to location
    if (stationMarkers[index]) {
        stationMarkers[index].openPopup();
        mymap.panTo([station.latitude, station.longitude]);
    }
}

function createCustomIcon(station, index, providerIconUrl) {
    let iconHtml = `<div style="background-image: url(${providerIconUrl}); width: 30px; height: 46px; background-size: cover; position: relative;">
                        <div style="position: absolute; bottom: 1px; width: 100%; text-align: center; color: white; font-weight: bold; font-size: 21px;">
                            ${index + 1}
                        </div>
                    </div>`;
    return L.divIcon({ 
        html: iconHtml, iconSize: [12, 41], iconAnchor: [12, 41], popupAnchor: [1, -34], className: '' 
    });
}

function addStationMarker(station, index) {
    let providerIconUrl = `static/css/images/marker-icon-${providerColors[station.service_provider]}.png` || 'grey'; // grey color if provider not found
    let customIcon = createCustomIcon(station, index, providerIconUrl);
    let stationMarker = L.marker([station.latitude, station.longitude], {icon: customIcon}).addTo(mymap);
    let popupContent = createPopupContent(station, index);
    const coloredContent = applyFrequencyColorsToTooltipContent(popupContent);
    stationMarker.bindPopup(coloredContent);
    stationMarkers.push(stationMarker);

    let tooltipContent = `${index + 1}. ${station.basestation_id}`; // tooltip
    stationMarker.bindTooltip(tooltipContent);

    // Draw connection line when marker is clicked
    stationMarker.on('click', function() {
        drawConnectionLine(station.latitude, station.longitude);
    });
}

function addStationInfoToSidebar(station, index, sidebarContent) {
    let stationInfoDiv = document.createElement('div');
    const providerClass = providerClasses[station.service_provider] || '';
    stationInfoDiv.className = `sidebar-item provider-${providerClass}`;
    stationInfoDiv.dataset.index = index;

    // Create the card content
    stationInfoDiv.innerHTML = createSidebarContent(station, index);
    sidebarContent.appendChild(stationInfoDiv);

    // Wire copy-coords button (replaces previous inline onclick — CSP-safe)
    const copyBtn = stationInfoDiv.querySelector('button[data-copy-coords]');
    if (copyBtn) {
        copyBtn.addEventListener('click', function(e) {
            e.stopPropagation();
            copyToClipboard(copyBtn.getAttribute('data-copy-coords'), copyBtn);
        });
    }

    // Add click handler for selection
    stationInfoDiv.addEventListener('click', function(e) {
        // Don't trigger if clicking a link or button
        if (e.target.tagName === 'A' || e.target.tagName === 'BUTTON' || e.target.closest('a') || e.target.closest('button')) {
            return;
        }

        // Remove selected class from previous selection
        document.querySelectorAll('.sidebar-item.selected').forEach(item => {
            item.classList.remove('selected');
        });

        // Add selected class to this item
        this.classList.add('selected');
        selectedStationIndex = index;

        // Draw connection line to this station
        drawConnectionLine(station.latitude, station.longitude);

        // Open the marker popup on map
        if (stationMarkers[index]) {
            stationMarkers[index].openPopup();
            mymap.panTo([station.latitude, station.longitude]);
        }
    });

    // Add links container
    const linksDiv = document.createElement('div');
    linksDiv.className = 'flex flex-wrap gap-2 mt-2 pt-2 border-t border-gray-200 dark:border-gray-700';

    let googleMapsLink = document.createElement('a');
    googleMapsLink.href = `https://www.google.com/maps/search/?api=1&query=${station.latitude},${station.longitude}`;
    googleMapsLink.target = '_blank';
    googleMapsLink.textContent = 'Google Maps';
    googleMapsLink.className = 'text-xs no-underline hover:underline text-blue-500 hover:text-blue-700 dark:text-blue-300 dark:hover:text-blue-400 font-semibold';
    linksDiv.appendChild(googleMapsLink);

    // Add compass button if supported and user location is available
    if (window.CompassModule && window.CompassModule.isSupported() && currentFilters.lat && currentFilters.lng) {
        const compassBtn = window.CompassModule.addButton(
            station.latitude,
            station.longitude,
            `${station.basestation_id} (${station.service_provider})`,
            currentFilters.lat,
            currentFilters.lng
        );
        compassBtn.className += ' text-xs';
        linksDiv.appendChild(compassBtn);
    }

    stationInfoDiv.appendChild(linksDiv);
}

function createPopupContent(station, index) {
    const formattedLat = station.latitude.toFixed(5);
    const formattedLng = station.longitude.toFixed(5);
    const formattedDistance = station.distance.toFixed(2);
    const latHemisphere = station.latitude >= 0 ? 'N' : 'S';
    const lngHemisphere = station.longitude >= 0 ? 'E' : 'W';
    const googleMapsLink = `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(station.latitude)},${encodeURIComponent(station.longitude)}`;
    const bands = Array.isArray(station.frequency_bands) ? station.frequency_bands.join(', ') : '';

    return `
        <div class="bg-blue-50 dark:bg-gray-800 dark:text-white p-1 rounded-lg">
            <b>${Number(index) + 1}. Service Provider:</b> ${escapeHtml(station.service_provider)}<br>
            <b>Distance:</b> ${formattedDistance}km<br>
            <b>Base Station ID:</b> ${escapeHtml(station.basestation_id)}<br>
            <b>Frequency Bands:</b> ${escapeHtml(bands)}<br>
            <b>City:</b> ${escapeHtml(station.city)}<br>
            <b>Location:</b> ${escapeHtml(station.location)}<br>
            <b>Coordinates:</b> ${formattedLat}°${latHemisphere}, ${formattedLng}°${lngHemisphere}<br>
            <a href="${escapeHtml(googleMapsLink)}" target="_blank" rel="noopener noreferrer" class="no-underline hover:underline text-blue-500 hover:text-blue-700 dark:text-blue-300 dark:hover:text-blue-400 font-semibold">View on Google Maps</a>
        </div>`;
}

function createSidebarContent(station, index) {
    const formattedLat = station.latitude.toFixed(5);
    const formattedLng = station.longitude.toFixed(5);
    const formattedDistance = station.distance.toFixed(2);
    const latHemisphere = station.latitude >= 0 ? 'N' : 'S';
    const lngHemisphere = station.longitude >= 0 ? 'E' : 'W';
    const coordsText = `${formattedLat}°${latHemisphere}, ${formattedLng}°${lngHemisphere}`;

    // Get signal strength
    const signal = getSignalStrength(station.distance);
    const providerShort = providerShortNames[station.service_provider] || station.service_provider;
    const providerClass = providerClasses[station.service_provider] || '';

    // Calculate bearing if user location is available
    let bearingHtml = '';
    if (currentFilters.lat && currentFilters.lng) {
        const bearing = calculateBearing(currentFilters.lat, currentFilters.lng, station.latitude, station.longitude);
        const direction = getCompassDirection(bearing);
        bearingHtml = `
            <span class="bearing-indicator ml-2">
                <span class="bearing-arrow" style="transform: rotate(${Number(bearing)}deg)">↑</span>
                ${escapeHtml(direction)} (${Math.round(bearing)}°)
            </span>`;
    }

    // Group frequency bands by type. Each individual band sits in its own
    // <span class="band-chip">…</span> so applyFrequencyColors() can recolor
    // them per RSRP-signal-level. Labels stay as plain bold text — they would
    // otherwise be picked up by the band-color rebuild and replace real values.
    const bandsArr = Array.isArray(station.frequency_bands) ? station.frequency_bands : [];
    const bands5G = bandsArr.filter(b => b.startsWith('5G'));
    const bandsLTE = bandsArr.filter(b => b.startsWith('LTE'));
    const bandsUMTS = bandsArr.filter(b => b.startsWith('UMTS'));
    const bandsGSM = bandsArr.filter(b => b.startsWith('GSM'));

    function bandGroup(label, bands) {
        if (bands.length === 0) return '';
        const chips = bands.map(b => `<span class="band-chip">${escapeHtml(b)}</span>`).join(', ');
        return `<b>${label}</b> ${chips} `;
    }

    const bandsHtml =
        bandGroup('5G:', bands5G) +
        bandGroup('LTE:', bandsLTE) +
        bandGroup('3G:', bandsUMTS) +
        bandGroup('GSM:', bandsGSM);

    const cityLocation = station.location
        ? `${escapeHtml(station.city)} • ${escapeHtml(station.location)}`
        : escapeHtml(station.city);

    return `
        <div class="dark:text-white">
            <div class="card-header">
                <h4>${Number(index) + 1}. ${escapeHtml(station.basestation_id)}</h4>
                <span class="signal-badge ${escapeHtml(signal.level)}">
                    ${createSignalBars(signal)}
                    <span class="hidden sm:inline">${escapeHtml(signal.label)}</span>
                </span>
            </div>
            <div class="card-meta">
                <span class="provider-dot ${escapeHtml(providerClass)}"></span>
                <span class="font-medium">${escapeHtml(providerShort)}</span>
                <span class="text-gray-500 dark:text-gray-400">•</span>
                <span>${formattedDistance} km</span>
                ${bearingHtml}
            </div>
            <p class="text-xs md:text-sm mb-1"><b>Bands:</b> ${bandsHtml}</p>
            <p class="text-xs md:text-sm mb-1 text-gray-600 dark:text-gray-300">${cityLocation}</p>
            <p class="text-xs md:text-sm mb-0 text-gray-500 dark:text-gray-400">
                ${coordsText}
                <button data-copy-coords="${formattedLat}, ${formattedLng}" class="copy-btn" title="Copy coordinates">📋</button>
            </p>
        </div>`;
}

function constructFilterURL() {
    let params = new URLSearchParams();

    params.append('lat', currentFilters.lat);
    params.append('lng', currentFilters.lng);

    if (Array.isArray(currentFilters.serviceProvider)) {
        currentFilters.serviceProvider.forEach(provider => params.append('service_provider', provider));
    }
    if (Array.isArray(currentFilters.frequencyBands)) {
        currentFilters.frequencyBands.forEach(band => params.append('frequency_bands', band));
    }

    if (currentFilters.mode === 'nearest') {
        if (currentFilters.limit !== undefined) params.append('limit', currentFilters.limit);
    } else if (currentFilters.mode === 'withinDistance') {
        if (currentFilters.maxDistance !== undefined) params.append('max_distance', currentFilters.maxDistance);
    }

    return `/stations?${params.toString()}`;
}

function fetchStations() {
    showLoadingSkeleton();
    let filterURL = constructFilterURL();
    globalFetch(filterURL)
    .then(data => {
        // Assuming data is already the parsed JSON object
        if (!data || typeof data !== 'object') {
            console.error('Invalid data received:', data);
            return;  // Early return if data is invalid or not an object
        }
        locationSetInitially = true;
        updateBTSCount(data.count);
        showSidebar();
        displayStations(data.stations);
        if (currentFilters.lat && currentFilters.lng) {
            addRingsForLocation(currentFilters.lat, currentFilters.lng);
        }
        applyFrequencyColors();
        scrollToSidebar();
    })
    .catch(error => {
        console.error('Failed to process station data:', error);
    });
}

function resetFiltersUI() {
    document.getElementById('nearestBtsRange').value = '';
    document.getElementById('withinDistanceRange').value = '';

    document.querySelectorAll('input[type="checkbox"]').forEach(checkbox => {
        checkbox.checked = false;
    });
    const center = mymap.getCenter();
    currentFilters = {
        ...initialFilters(),
        lat: currentFilters.lat || center.lat,
        lng: currentFilters.lng || center.lng
    };
}    

document.addEventListener('DOMContentLoaded', function() {
    const nearestBtsRangeInput = document.getElementById('nearestBtsRange');
    const withinDistanceInput = document.getElementById('withinDistanceRange');

    function validateAndCorrectInput(input, isInteger = false) {
    input.addEventListener('input', function() {
        const validValue = this.value.match(isInteger ? /^\d+$/ : /^\d*\.?\d?$/);
        
        if (validValue) {
            let value = isInteger ? parseInt(this.value, 10) : parseFloat(this.value);
            const max = parseFloat(this.max);

            if (value > max) {
                this.value = max.toString();
            } else if (value === max && this.value.endsWith('.0')) {
                this.value = this.value.slice(0, -2);
            } else if ((!isInteger && value <= 0) || (isInteger && value < 1)) {
                this.value = isInteger ? "1" : "0.1"; // 1 for integer, 0.1 for decimal
            } else {
                this.value = isInteger ? value.toString() : value.toFixed(1);
            }
        } else {
            this.value = this.value.slice(0, -1); // remove the last invalid character
        }
    });
}

    validateAndCorrectInput(nearestBtsRangeInput, true); // true for integer validation
    validateAndCorrectInput(withinDistanceInput); // default for decimal validation

    nearestBtsRangeInput.setAttribute('placeholder', '1-10');
    withinDistanceInput.setAttribute('placeholder', '0.1-10');
});

document.addEventListener('DOMContentLoaded', function() {
    const dynamicContent = document.getElementById('dynamicContent');

    function setupLatLngInputValidation(selector, min, max) {
        dynamicContent.addEventListener('change', function(event) {
            if (event.target.matches(selector)) {
                const input = event.target;
                let value = parseFloat(input.value);
                if (value < min) {
                    input.value = min.toFixed(3);
                } else if (value > max) {
                    input.value = max.toFixed(3);
                } else {
                    input.value = parseFloat(input.value).toFixed(3);
                }
            }
        });
    }

    // specific selectors to match input elements
    setupLatLngInputValidation('#latitudeInput', 48, 58);
    setupLatLngInputValidation('#longitudeInput', 13.5, 24.5);
});

function updateDynamicContent() {
    globalFetch('/session_check')
    .then(data => {
        const dynamicContent = document.getElementById('dynamicContent');
        const isLoggedIn = data.logged_in;
        if (isLoggedIn) {
            dynamicContent.innerHTML = `
                <div id="latLngContainer" class="flex flex-col space-y-0.5">
                <button id="submitCoords" class="mt-2 w-48 bg-blue-300 dark:bg-gray-700 hover:bg-blue-500 dark:hover:bg-gray-500 text-white rounded">Search</button>
                    <div class="flex space-x-2">
                    <input type="number" id="latitudeInput" placeholder="52.230 (°N)" class="w-[5.5rem] mt-0.5 bg-blue-100 hover:bg-blue-300 dark:bg-gray-700 dark:hover:bg-gray-500" min="48" max="58" step="0.1">
                    <input type="number" id="longitudeInput" placeholder="21.003 (°E)" class="w-[5.5rem] mt-0.5 bg-blue-100 hover:bg-blue-300 dark:bg-gray-700 dark:hover:bg-gray-500" min="13.5" max="24.5" step="0.1">
                    </div>
                </div>
                <div id="searchByBtsContainer" class="mt-4 flex flex-col space-y-0.5">    
                    <button id="submitfilteredstation" class="w-48 bg-blue-300 dark:bg-gray-700 hover:bg-blue-500 dark:hover:bg-gray-500 text-white rounded">Search</button>
                    <div class="flex space-x-2">
                        <input type="text" id="baseStationIdInput" placeholder="Enter Base Station ID" class="w-[8rem] mt-0.5 bg-blue-100 hover:bg-blue-300 dark:bg-gray-700 dark:hover:bg-gray-500">
                    </div>
                </div>`;
        } else {
            dynamicContent.innerHTML = `
                <div id="latLngContainer" class="opacity-50 cursor-not-allowed flex flex-col space-y-0.5 title="Log in to use this feature.">
                    <button id="submitCoords" class="mt-2 w-48 bg-blue-300 dark:bg-gray-700 hover:bg-blue-500 dark:hover:bg-gray-500 text-white rounded cursor-not-allowed" disabled title="Log in to use this feature.">Search</button>
                    <div class="flex space-x-2">
                        <input type="number" id="latitudeInput" placeholder="52.230 (°N)" class="w-[5.5rem] mt-0.5 bg-blue-100 hover:bg-blue-300 dark:bg-gray-700 dark:hover:bg-gray-500 cursor-not-allowed" min="48" max="58" step="0.1" disabled title="Log in to use this feature.">
                        <input type="number" id="longitudeInput" placeholder="21.003 (°E)" class="w-[5.5rem] mt-0.5 bg-blue-100 hover:bg-blue-300 dark:bg-gray-700 dark:hover:bg-gray-500 cursor-not-allowed" min="13.5" max="24.5" step="0.1" disabled title="Log in to use this feature.">
                    </div>
                </div>
                <div id="searchByBtsContainer" class="mt-4 opacity-50 cursor-not-allowed flex flex-col space-y-0.5 title="Log in to use this feature.">
                    <button id="submitfilteredstation" class="w-48 bg-blue-300 dark:bg-gray-700 hover:bg-blue-500 dark:hover:bg-gray-500 text-white rounded cursor-not-allowed" disabled title="Log in to use this feature.">Search</button>
                    <div class="flex space-x-2">
                        <input type="text" id="baseStationIdInput" placeholder="Enter Base Station ID" class="w-[8rem] mt-0.5 bg-blue-100 hover:bg-blue-300 dark:bg-gray-700 dark:hover:bg-gray-500 cursor-not-allowed" disabled title="Log in to use this feature.">
                    </div>
                </div>`;
        }
    })
    .catch(error => console.error('Error:', error));
}

function updateLatLngFilters() {
    const latitudeInput = document.getElementById('latitudeInput');
    const longitudeInput = document.getElementById('longitudeInput');

    if (!latitudeInput.value.trim() || !longitudeInput.value.trim()) {
        showToast('Both latitude and longitude must be filled out to proceed.', 'error');
        return;
    }

    let lat = parseFloat(latitudeInput.value);
    let lng = parseFloat(longitudeInput.value);
    let validationPassed = true;

    if (isNaN(lat) || lat < 48 || lat > 58) {
        showToast('Latitude is out of range. Please enter a value between 48 and 58.', 'error');
        validationPassed = false;
    }

    if (isNaN(lng) || lng < 13.5 || lng > 24.5) {
        showToast('Longitude is out of range. Please enter a value between 13 and 25.', 'error');
        validationPassed = false;
    }

    if (validationPassed) {
        currentFilters.lat = lat;
        currentFilters.lng = lng;
        fetchStations();
    }
}

document.getElementById('dynamicContent').addEventListener('click', function(event) {
    if (event.target.id === 'submitCoords') {
        updateLatLngFilters();
    }
});

function updateStationFilters() {
    const baseStationIdInput = document.getElementById('baseStationIdInput');
    let basestation_id = baseStationIdInput.value;
    basestation_id = basestation_id.toUpperCase();
    if (!basestation_id || basestation_id.length > 7 || !/^[A-Za-z0-9]+$/.test(basestation_id)) {
        showToast('Base Station ID must be up to 7 letters or digits.', 'error');
        return;
    }
    if (!basestation_id) {
        showToast('Base Station ID is required', 'error');
        return;
    }

    globalFetch(`/find_station?basestation_id=${basestation_id}`)
        .then(station => {
            if (station.error) {
                showToast(station.error, 'error'); 
                return; 
            }

            currentFilters.lat = station.latitude;
            currentFilters.lng = station.longitude;
            fetchStations();
        })
        .catch(error => {
            console.error('Error fetching station:', error);
        });
}
  
document.addEventListener('click', function(event) {
    if (event.target.id === 'submitfilteredstation') {
        updateStationFilters();
    }
});

// ── Search-as-you-type for Base Station ID ──
let searchDebounceTimer = null;
let searchSuggestionsVisible = false;

function setupBaseStationSearch() {
    const input = document.getElementById('baseStationIdInput');
    if (!input) return;

    // Create suggestions container
    let suggestionsContainer = document.getElementById('bts-suggestions');
    if (!suggestionsContainer) {
        suggestionsContainer = document.createElement('div');
        suggestionsContainer.id = 'bts-suggestions';
        suggestionsContainer.className = 'bts-suggestions hidden';
        input.parentElement.style.position = 'relative';
        input.parentElement.appendChild(suggestionsContainer);
    }

    input.addEventListener('input', function() {
        const query = this.value.trim().toUpperCase();

        clearTimeout(searchDebounceTimer);

        if (query.length < 2) {
            hideSuggestions();
            return;
        }

        searchDebounceTimer = setTimeout(() => {
            searchBaseStations(query);
        }, 300);
    });

    input.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') {
            hideSuggestions();
        }
    });

    // Hide suggestions when clicking outside
    document.addEventListener('click', function(e) {
        if (!e.target.closest('#searchByBtsContainer')) {
            hideSuggestions();
        }
    });
}

function searchBaseStations(query) {
    globalFetch(`/search_stations?q=${encodeURIComponent(query)}&limit=5`)
        .then(data => {
            if (data && data.stations && data.stations.length > 0) {
                showSuggestions(data.stations);
            } else {
                hideSuggestions();
            }
        })
        .catch(err => {
            console.error('Search error:', err);
            hideSuggestions();
        });
}

function showSuggestions(stations) {
    const container = document.getElementById('bts-suggestions');
    if (!container) return;

    container.innerHTML = '';
    stations.forEach(station => {
        const item = document.createElement('div');
        item.className = 'suggestion-item';
        const providerShort = providerShortNames[station.service_provider] || station.service_provider;

        const idEl = document.createElement('span');
        idEl.className = 'font-medium';
        idEl.textContent = station.basestation_id;

        const sep1 = document.createElement('span');
        sep1.className = 'text-gray-500 dark:text-gray-400';
        sep1.textContent = '•';

        const providerEl = document.createElement('span');
        providerEl.className = 'text-xs';
        providerEl.textContent = providerShort;

        const sep2 = sep1.cloneNode(true);

        const cityEl = document.createElement('span');
        cityEl.className = 'text-xs text-gray-500 dark:text-gray-400';
        cityEl.textContent = station.city || 'Unknown';

        item.append(idEl, sep1, providerEl, sep2, cityEl);

        item.addEventListener('click', function() {
            document.getElementById('baseStationIdInput').value = station.basestation_id;
            hideSuggestions();
            // Trigger search
            currentFilters.lat = station.latitude;
            currentFilters.lng = station.longitude;
            fetchStations();
        });
        container.appendChild(item);
    });

    container.classList.remove('hidden');
    searchSuggestionsVisible = true;
}

function hideSuggestions() {
    const container = document.getElementById('bts-suggestions');
    if (container) {
        container.classList.add('hidden');
    }
    searchSuggestionsVisible = false;
}

// Initialize search on dynamic content load
new MutationObserver(function(mutations, observer) {
    if (document.getElementById('baseStationIdInput')) {
        setupBaseStationSearch();
    }
}).observe(document.getElementById('dynamicContent'), { childList: true });

function addRing(lat, lng, radius, color) {
    L.circle([lat, lng], {
        color: color,
        fillColor: color,
        fillOpacity: 0, 
        radius: radius
    }).addTo(mymap);
}

function addRingsForLocation(lat, lng) {
    const distanceRadius = frequencyRanges[currentBand];
    addRing(lat, lng, distanceRadius[0], 'green'); // Excellent
    addRing(lat, lng, distanceRadius[1], 'yellow'); // Good
    addRing(lat, lng, distanceRadius[2], 'orange'); // Fair
    addRing(lat, lng, distanceRadius[3], 'red'); // Poor
}

function clearRings() {
    mymap.eachLayer(function(layer) {
        if (layer instanceof L.Circle) {
            mymap.removeLayer(layer);
        }
    });
}

function changeFrequency(band) {
    const columnClass = `column-${band}`;

    if (currentFilters.lat === null || currentFilters.lng === null) {
        showToast('Please submit your location before changing the frequency.', 'error');
        return;
    }

    document.querySelectorAll('th, td').forEach(cell => {
        cell.classList.remove('highlighted-column');
    });

    document.querySelectorAll(`.${columnClass}`).forEach(cell => {
        cell.classList.add('highlighted-column');
    });

    currentBand = band;
    clearRings();
    addRingsForLocation(currentFilters.lat, currentFilters.lng, currentBand);
}

document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('.column-low').forEach(cell => {
        cell.classList.add('highlighted-column');
    });
});

function getFrequencyColorForDistance(band, distanceKm) {
    let distanceMeters = distanceKm * 1000;
    let bandKey;
    if (['5G3600', 'LTE2600', '5G2600'].includes(band)) {
        bandKey = 'high';
    } else if (['5G2100', 'LTE2100', '5G1800', 'LTE1800', 'UMTS2100'].includes(band)) {
        bandKey = 'mid';
    } else {
        // Low band: LTE900, LTE800, LTE700, UMTS900, GSM900, GSM1800, 5G700
        bandKey = 'low';
    }

    // Get the corresponding distance thresholds for this bandKey
    const thresholds = frequencyRanges[bandKey];

    // Determine the color based on where the distance falls within the thresholds
    for (let idx = 0; idx < thresholds.length; idx++) {
        if (distanceMeters <= thresholds[idx]) {
            return frequencyRangecolors[idx];
        }
    }
    
    return 'red'; // If distance exceeds all thresholds, default to red
}

function applyFrequencyColors() {
    const sidebarItems = document.querySelectorAll('.sidebar-item');

    sidebarItems.forEach((item) => {
        // Extract distance from .card-meta span (format: "X.XX km")
        let distance = null;
        const metaSpans = item.querySelectorAll('.card-meta span');
        metaSpans.forEach(span => {
            const distanceMatch = span.textContent.match(/^(\d+\.?\d*)\s*km$/);
            if (distanceMatch) {
                distance = parseFloat(distanceMatch[1]);
            }
        });

        if (distance !== null) {
            // Recolor each .band-chip in place so labels (5G:/LTE:/3G:/GSM:)
            // and per-group separators stay intact.
            item.querySelectorAll('.band-chip').forEach(chip => {
                const band = chip.textContent.trim();
                if (!band) return;
                const color = getFrequencyColorForDistance(band, distance);
                chip.className = `band-chip text-${color}-600 dark:text-${color}-400 font-medium`;
            });
        }
    });
}

function applyFrequencyColorsToTooltipContent(content, distance) {
    // Find the distance if not provided
    if (!distance) {
        const distanceMatch = content.match(/<b>Distance:<\/b>\s*(\d+\.?\d*)km/);
        if (distanceMatch) {
            distance = parseFloat(distanceMatch[1]);
        }
    }

    if (distance) {
        // Find the frequency bands substring in the content
        const bandsMatch = content.match(/<b>Frequency Bands:<\/b>\s*([^<]+)/);
        if (bandsMatch && bandsMatch[1]) {
            // Split the bands into array
            const bandsList = bandsMatch[1].split(',').map(band => band.trim());
            const coloredBandsHtml = bandsList.map(band => {
                const colorClass = getFrequencyColorForDistance(band, distance); 

                return `<span class="text-${colorClass}-600">${band}</span>`;
            }).join(', ');

            content = content.replace(bandsMatch[0], `<b>Frequency Bands:</b> ${coloredBandsHtml}`);
        }
    }

    return content;
}