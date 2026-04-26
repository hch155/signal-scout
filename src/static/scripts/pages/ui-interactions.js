// map.html
updateDynamicContent()

let mymap = L.map('mapid').setView([52.231, 21.004], 7); //  default location and zoom level

// PR #48.9: switched off OSM standard tiles (tile.openstreetmap.org) —
// missing white tiles started appearing for users in PL/border regions.
// OSM Foundation's tile policy throttles heavy traffic from a single
// origin, and we don't get subdomain rotation by default. CartoDB
// Voyager mirrors the OSM look (roads colored, terrain shading) but
// rides the same `basemaps.cartocdn.com` 4-subdomain CDN as our dark
// layer — same provider, same CSP allowance, no API key, no rate-limit
// surprises. CSP `img-src` already permits basemaps.cartocdn.com (added
// for dark layer in PR #48.1).
const lightTileLayer = L.tileLayer('https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png', {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
    subdomains: 'abcd',
    maxZoom: 19,
}).addTo(mymap);

// PR #48.1: switched from Stadia Maps (returned 503 once we passed the
// no-API-key free tier) to CartoDB Dark Matter — same dark-mode vibe,
// no API key required, served via 4 subdomain CDN. Stadia would be
// fine again with a free API key (200k tiles/mo) — switch back if we
// want their richer styling later. CSP `img-src` widened in app.py to
// allow basemaps.cartocdn.com.
const darkTileLayer = L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
    subdomains: 'abcd',
    maxZoom: 19,
});

// PR #46.8: restore satellite layer (PR #46.7 misread the owner's
// instruction — the "vibe-coded" thing to drop was the empty-state
// satellite-dish icon in showEmptyState(), not this map tile layer).
const satelliteLayer = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
    attribution: 'Tiles &copy; Esri'
});

// Layer control for map styles
const baseMaps = {
    "Street": lightTileLayer,
    "Dark": darkTileLayer,
    "Satellite": satelliteLayer
};
// PR #47: collapsed=false avoids the toggle icon entirely. Vendored
// Leaflet's CSS expects images/layers.png + images/layers-2x.png in
// the same dir; we don't ship them (sandbox rules during the sprint
// blocked auto-vendoring), and 404s on those tiles surfaced as a
// blank white square in prod. Always-expanded list (3 radio rows)
// renders fine without the icon and is arguably better UX on
// desktop too — no extra hover step to switch base map.
L.control.layers(baseMaps, null, { position: 'topright', collapsed: false }).addTo(mymap);

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
                    <input type="number" id="withinDistanceRange" min="0.5" max="10" step="0.5" placeholder="" class="w-[4.25rem] mt-1 bg-blue-100 hover:bg-blue-300 dark:bg-gray-700 dark:hover:bg-gray-500">
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

    // Persist whatever distance/limit mode the user picked earlier instead
    // of silently resetting to 'all' (which made constructFilterURL drop
    // both `limit` and `max_distance`, leaving the backend at its default
    // limit=9 — that was the "1083 stations → 9 stations after picking
    // 5G3600" symptom user reported). Re-read the inputs so a value the
    // user typed without clicking the dedicated "Show within distance"
    // button is still respected.
    const nearest = document.getElementById('nearestBtsRange').value;
    const distance = document.getElementById('withinDistanceRange').value;
    if (distance) {
        currentFilters.mode = 'withinDistance';
        currentFilters.maxDistance = distance;
    } else if (nearest) {
        currentFilters.mode = 'nearest';
        currentFilters.limit = nearest;
    }
    // No distance and no limit value → keep whatever mode was set by the
    // last "Show nearest" / "Show within distance" click. Resetting to
    // 'all' would lose the user's earlier choice.

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
        // PR #46.7: bug — second click outside-PL was looping the
        // toast forever because each click stacked a new
        // setTimeout (zoomOut + hide), and the toast was never
        // re-shown for the new click since it was still visible
        // from the previous one. Track the timer on the
        // messageBox element so each new toast cancels the
        // previous one's auto-dismiss + re-arms a fresh 7.7s
        // window.
        if (messageBox._dismissTimer) {
            clearTimeout(messageBox._dismissTimer);
            messageBox._dismissTimer = null;
        }
        messageBox.classList.remove('hidden');
        messageBox._dismissTimer = setTimeout(() => {
            messageBox.classList.add('hidden');
            messageBox._dismissTimer = null;
            // Only zoom out if we're still further than the
            // default zoom; avoids zoom oscillation when the
            // user keeps clicking outside PL repeatedly.
            if (mymap.getZoom() > 6) {
                mymap.zoomOut(4);
            }
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
            // PR #46.9: shortcut for logged-in users — save the
            // currently-clicked spot as a saved location for alerts,
            // without driving them through /account → + Add → manual
            // lat/lng entry.
            // PR #47.2: pick a usable default name from the nearest
            // station's city (already in this payload). Beats the
            // useless "Spot 2026-04-24 13:14" the previous default
            // produced — the user can identify the saved location at a
            // glance from /account.
            const nearestCity = (data.stations[0] && data.stations[0].city) || null;
            renderSaveSpotShortcut(lat, lng, nearestCity);
            // PR #47.1: dead-areas detection is opt-in via a small CTA
            // button (logged-in users only). Auto-rendering distracted
            // from the core station list, so it's now an extra feature
            // rather than a default sidebar widget.
            renderCoverageGapsCTA(lat, lng);
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

// PR #47.1: opt-in CTA for the dead-areas check. Only logged-in users
// see it (matches Save-this-spot pattern). Renders a small button under
// the save-spot CTA; clicking it loads the full coverage widget.
// Goal: keep the main station list as the focus and offer the band-by-
// band gap analysis as an extra power-user feature, not a default
// sidebar widget.
function renderCoverageGapsCTA(lat, lng) {
    if (!window._isLoggedIn) return;
    const sidebar = document.getElementById('sidebar');
    if (!sidebar) return;
    const existing = sidebar.querySelector('#coverage-gaps-cta');
    if (existing) existing.remove();
    const existingWidget = sidebar.querySelector('#coverage-gaps-widget');
    if (existingWidget) existingWidget.remove();

    const cta = document.createElement('div');
    cta.id = 'coverage-gaps-cta';
    cta.className = 'col-span-full mb-2 p-2 rounded-lg bg-gray-50 dark:bg-gray-800/60 border border-gray-200 dark:border-gray-700 flex items-center justify-between gap-3';

    const label = document.createElement('div');
    label.className = 'text-xs text-gray-700 dark:text-gray-300';
    label.textContent = 'Check per-band coverage gaps at this spot';

    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'shrink-0 bg-gray-700 hover:bg-gray-800 dark:bg-gray-600 dark:hover:bg-gray-500 text-white text-xs font-semibold py-1 px-2.5 rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gray-400 focus-visible:ring-offset-2 dark:focus-visible:ring-offset-gray-800 transition-colors';
    btn.textContent = 'Analyse';
    btn.addEventListener('click', () => {
        cta.remove();
        renderCoverageGaps(lat, lng);
    });

    cta.appendChild(label);
    cta.appendChild(btn);
    sidebar.insertBefore(cta, sidebar.firstChild);
}

// PR #47: dead-areas widget — per-band coverage check at the clicked
// spot. Async fetch to /coverage_gaps; renders a compact list above
// the station cards: ✓ green for "covered" (nearest BTS of that band
// within the band-specific threshold), ✗ red for "dead". Includes a
// summary line ("3 of 8 bands dead at this spot"). Replaces any
// previous widget on a new click. PR #47.1: now invoked on demand
// from renderCoverageGapsCTA, not auto-rendered.
function renderCoverageGaps(lat, lng) {
    const sidebar = document.getElementById('sidebar');
    if (!sidebar) return;
    const existing = sidebar.querySelector('#coverage-gaps-widget');
    if (existing) existing.remove();

    const widget = document.createElement('div');
    widget.id = 'coverage-gaps-widget';
    widget.className = 'col-span-full mb-3 p-3 rounded-lg bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 shadow-sm';
    widget.innerHTML = '<div class="text-xs text-gray-500 dark:text-gray-400">Checking coverage at this spot…</div>';
    sidebar.insertBefore(widget, sidebar.firstChild);

    globalFetch(`/coverage_gaps?lat=${encodeURIComponent(lat)}&lng=${encodeURIComponent(lng)}`)
        .then(data => {
            if (!data || data.outside_pl || !Array.isArray(data.gaps) || data.gaps.length === 0) {
                widget.remove();
                return;
            }
            const summary = data.summary || {};
            const dead = summary.dead || 0;
            const total = summary.total_bands || data.gaps.length;
            const covered = total - dead;

            const summaryClass = dead === 0
                ? 'text-green-700 dark:text-green-300'
                : dead >= total / 2
                    ? 'text-red-700 dark:text-red-300'
                    : 'text-yellow-700 dark:text-yellow-300';
            const summaryText = dead === 0
                ? `Full coverage at this spot — all ${total} bands within reach.`
                : `${dead} of ${total} band${total > 1 ? 's' : ''} dead at this spot. ${covered} covered.`;

            // PR #47.3: build the row DOM directly (was: template
            // string) so each band can carry a click handler that
            // highlights its nearest BTS on the map.
            widget.textContent = '';
            const title = document.createElement('div');
            title.className = 'text-sm font-semibold text-gray-900 dark:text-white mb-1';
            title.textContent = 'Coverage at this spot';
            widget.appendChild(title);

            const summaryEl = document.createElement('div');
            summaryEl.className = `text-xs ${summaryClass} mb-2`;
            summaryEl.textContent = summaryText;
            widget.appendChild(summaryEl);

            const hint = document.createElement('div');
            hint.className = 'text-[10px] text-gray-500 dark:text-gray-400 mb-1';
            hint.textContent = 'Click a band to show its closest BTS on the map.';
            widget.appendChild(hint);

            const ul = document.createElement('ul');
            ul.className = 'space-y-0.5';
            data.gaps.forEach(g => {
                const ok = g.has_coverage;
                const dist = g.nearest_distance_km;
                const thresh = g.threshold_km;
                const labelText = ok
                    ? `nearest ${dist} km (within ${thresh} km)`
                    : `nearest ${dist} km (gap — threshold ${thresh} km)`;

                const li = document.createElement('li');

                const btn = document.createElement('button');
                btn.type = 'button';
                btn.dataset.band = g.band;
                btn.className = 'w-full flex items-center justify-between gap-2 py-0.5 px-1 rounded hover:bg-gray-100 dark:hover:bg-gray-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400 transition-colors text-left';

                const bandSpan = document.createElement('span');
                bandSpan.className = 'font-mono text-xs text-gray-700 dark:text-gray-200';
                bandSpan.textContent = g.band;

                const right = document.createElement('span');
                right.className = 'flex items-center gap-2 text-xs';

                const labelSpan = document.createElement('span');
                labelSpan.className = 'text-gray-500 dark:text-gray-400';
                labelSpan.textContent = labelText;

                const iconSpan = document.createElement('span');
                iconSpan.className = (ok
                    ? 'text-green-600 dark:text-green-400'
                    : 'text-red-600 dark:text-red-400') + ' font-bold text-base leading-none';
                iconSpan.textContent = ok ? '✓' : '✗';

                right.appendChild(labelSpan);
                right.appendChild(iconSpan);
                btn.appendChild(bandSpan);
                btn.appendChild(right);

                btn.addEventListener('click', () => {
                    toggleBandHighlight(btn, g, lat, lng);
                });

                li.appendChild(btn);
                ul.appendChild(li);
            });
            widget.appendChild(ul);

            const foot = document.createElement('div');
            foot.className = 'text-[10px] text-gray-400 dark:text-gray-500 mt-2 italic';
            foot.textContent = 'Thresholds: high-band ≤1.5 km · mid ≤2 km · low ≤5 km. Line-of-sight; real signal varies.';
            widget.appendChild(foot);
        })
        .catch(() => {
            widget.remove();
        });
}

// PR #47.3: ephemeral map layer holding the band-highlight ring + line.
// Keep it module-level so toggle / clear from any caller works.
const bandHighlightLayer = L.layerGroup().addTo(mymap);
let activeBandKey = null;

function clearBandHighlight() {
    bandHighlightLayer.clearLayers();
    const banner = document.getElementById('band-far-banner');
    if (banner) banner.remove();
    const card = document.getElementById('band-highlight-card');
    if (card) card.remove();
    // Drop the active styling from any previously-pressed band button.
    document.querySelectorAll('[data-band]').forEach(b => {
        b.classList.remove('bg-blue-100', 'dark:bg-blue-900/40', 'ring-2', 'ring-blue-400');
    });
    activeBandKey = null;
}

function bearingDeg(lat1, lng1, lat2, lng2) {
    const φ1 = lat1 * Math.PI / 180;
    const φ2 = lat2 * Math.PI / 180;
    const Δλ = (lng2 - lng1) * Math.PI / 180;
    const y = Math.sin(Δλ) * Math.cos(φ2);
    const x = Math.cos(φ1) * Math.sin(φ2) - Math.sin(φ1) * Math.cos(φ2) * Math.cos(Δλ);
    return (Math.atan2(y, x) * 180 / Math.PI + 360) % 360;
}

function compassDir(deg) {
    const dirs = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'];
    return dirs[Math.round(deg / 45) % 8];
}

// PR #47.3: clicking a band in the Coverage widget highlights its
// SINGLE closest BTS. Same band clicked twice = clear (toggle).
// Different band = swap. Far-away dead bands (>30 km) skip the ring
// and instead show a small banner with bearing — panning a map by
// 120 km away from the user's spot is more frustrating than helpful.
const FAR_BAND_KM = 30;

function toggleBandHighlight(btnEl, gap, userLat, userLng) {
    if (activeBandKey === gap.band) {
        clearBandHighlight();
        return;
    }
    clearBandHighlight();
    activeBandKey = gap.band;
    btnEl.classList.add('bg-blue-100', 'dark:bg-blue-900/40');

    const tLat = gap.nearest_lat;
    const tLng = gap.nearest_lng;
    if (typeof tLat !== 'number' || typeof tLng !== 'number') return;

    const isFar = gap.nearest_distance_km > FAR_BAND_KM;

    // PR #47.4: pull the rest of the BTS metadata the backend now
    // returns (provider/basestation_id/city/all bands at that loc) so
    // the popup + sidebar card show the same info as a regular station
    // pin. Falls back to whatever the backend gave if any field is
    // missing so the UI never half-renders.
    const station = {
        latitude: tLat,
        longitude: tLng,
        distance: gap.nearest_distance_km,
        service_provider: gap.nearest_service_provider || 'Unknown',
        basestation_id: gap.nearest_basestation_id || '',
        frequency_bands: Array.isArray(gap.nearest_frequency_bands)
            ? gap.nearest_frequency_bands
            : [gap.band],
        city: gap.nearest_city || '',
        location: gap.nearest_location || '',
    };

    // Marker — provider-coloured pin so it visually matches any other
    // station marker on the map. Bound to a popup with full station
    // info; opened immediately so the user sees what they clicked.
    const provColor = (typeof providerColors !== 'undefined' && providerColors[station.service_provider])
        ? providerColors[station.service_provider]
        : 'grey';
    const markerIcon = L.icon({
        iconUrl: `static/css/images/marker-icon-${provColor}.png`,
        iconSize: [25, 41],
        iconAnchor: [12, 41],
        popupAnchor: [1, -34],
    });
    const marker = L.marker([tLat, tLng], { icon: markerIcon })
        .bindPopup(buildBandHighlightPopup(station, gap));

    // Dashed line from the user's clicked spot to the BTS — same purple
    // hue used for the band-highlight, distinct from the regular
    // currentLine drawn by other flows.
    const line = L.polyline([[userLat, userLng], [tLat, tLng]], {
        color: '#7c3aed',
        weight: 2,
        dashArray: '6 6',
        opacity: 0.85,
        interactive: false,
    });

    bandHighlightLayer.addLayer(line);
    bandHighlightLayer.addLayer(marker);

    // Coverage ring is only meaningful when the user can actually see
    // it — for far-away dead bands the ring would dominate the whole
    // viewport. Keep it for in-range only.
    if (!isFar) {
        const ring = L.circle([tLat, tLng], {
            radius: (gap.threshold_km || 3) * 1000,
            color: '#7c3aed',
            weight: 2,
            fillColor: '#7c3aed',
            fillOpacity: 0.08,
            interactive: false,
        });
        bandHighlightLayer.addLayer(ring);
    }

    addBandHighlightSidebarCard(station, gap, userLat, userLng);

    if (!isFar) {
        const bounds = L.latLngBounds([userLat, userLng], [tLat, tLng]).pad(0.25);
        mymap.fitBounds(bounds, { maxZoom: 14, animate: true });
        marker.openPopup();
    } else {
        // Far case: don't auto-pan — that'd tear the map away from the
        // user's clicked spot. Show a small banner telling the user the
        // direction; the sidebar card has a "Navigate" button that does
        // pan/zoom on demand if they want to actually go look.
        const dir = compassDir(bearingDeg(userLat, userLng, tLat, tLng));
        showFarBandBanner(`Nearest ${gap.band} is ${gap.nearest_distance_km} km ${dir} — click "Navigate" in the sidebar to jump there.`);
    }
}

function showFarBandBanner(text) {
    const banner = document.createElement('div');
    banner.id = 'band-far-banner';
    banner.className = 'absolute top-3 left-1/2 -translate-x-1/2 z-[1000] bg-yellow-100 dark:bg-yellow-900/80 text-yellow-900 dark:text-yellow-100 text-xs px-3 py-1.5 rounded-full shadow border border-yellow-300 dark:border-yellow-700 pointer-events-auto flex items-center gap-2';
    banner.textContent = text;
    const close = document.createElement('button');
    close.type = 'button';
    close.className = 'font-bold opacity-70 hover:opacity-100';
    close.textContent = '×';
    close.addEventListener('click', clearBandHighlight);
    banner.appendChild(close);
    const mapEl = document.getElementById('mapid');
    if (mapEl && mapEl.parentElement) {
        mapEl.parentElement.style.position = mapEl.parentElement.style.position || 'relative';
        mapEl.parentElement.appendChild(banner);
    }
}

function buildBandHighlightPopup(station, gap) {
    const lat = station.latitude.toFixed(5);
    const lng = station.longitude.toFixed(5);
    const bands = (station.frequency_bands || []).join(', ');
    const gmaps = `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(station.latitude)},${encodeURIComponent(station.longitude)}`;
    return `
        <div class="bg-blue-50 dark:bg-gray-800 dark:text-white p-1 rounded-lg text-sm">
            <div class="font-semibold mb-1">Nearest ${escapeHtml(gap.band)} · ${gap.nearest_distance_km} km</div>
            <b>Service Provider:</b> ${escapeHtml(station.service_provider)}<br>
            <b>Base Station ID:</b> ${escapeHtml(station.basestation_id)}<br>
            <b>Frequency Bands:</b> ${escapeHtml(bands)}<br>
            <b>City:</b> ${escapeHtml(station.city)}<br>
            <b>Location:</b> ${escapeHtml(station.location)}<br>
            <b>Coordinates:</b> ${lat}°N, ${lng}°E<br>
            <a href="${escapeHtml(gmaps)}" target="_blank" rel="noopener noreferrer" class="no-underline hover:underline text-blue-500 hover:text-blue-700 dark:text-blue-300 dark:hover:text-blue-400 font-semibold">View on Google Maps</a>
        </div>`;
}

function addBandHighlightSidebarCard(station, gap, userLat, userLng) {
    const sidebar = document.getElementById('sidebar');
    if (!sidebar) return;
    const old = document.getElementById('band-highlight-card');
    if (old) old.remove();

    const card = document.createElement('div');
    card.id = 'band-highlight-card';
    card.className = 'col-span-full mb-3 p-3 rounded-lg bg-violet-50 dark:bg-violet-900/30 border border-violet-200 dark:border-violet-800';

    const head = document.createElement('div');
    head.className = 'flex items-center justify-between gap-2 mb-2';
    const title = document.createElement('div');
    title.className = 'text-sm font-semibold text-violet-900 dark:text-violet-100';
    title.textContent = `Nearest ${gap.band} · ${gap.nearest_distance_km} km`;
    const closeBtn = document.createElement('button');
    closeBtn.type = 'button';
    closeBtn.className = 'text-violet-700 dark:text-violet-200 opacity-70 hover:opacity-100 text-lg leading-none';
    closeBtn.textContent = '×';
    closeBtn.setAttribute('aria-label', 'Clear band highlight');
    closeBtn.addEventListener('click', clearBandHighlight);
    head.appendChild(title);
    head.appendChild(closeBtn);
    card.appendChild(head);

    const lines = [
        ['Provider', station.service_provider || '—'],
        ['BTS ID', station.basestation_id || '—'],
        ['City', station.city || '—'],
        ['Bands', (station.frequency_bands || []).join(', ') || '—'],
    ];
    lines.forEach(([k, v]) => {
        const row = document.createElement('div');
        row.className = 'text-xs text-gray-700 dark:text-gray-200 leading-tight';
        const key = document.createElement('span');
        key.className = 'font-mono text-gray-500 dark:text-gray-400 mr-1';
        key.textContent = `${k}:`;
        const val = document.createElement('span');
        val.textContent = String(v);
        row.appendChild(key);
        row.appendChild(val);
        card.appendChild(row);
    });

    const navBtn = document.createElement('button');
    navBtn.type = 'button';
    navBtn.className = 'mt-2 w-full bg-violet-600 hover:bg-violet-700 text-white text-sm font-semibold py-1.5 px-3 rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-300 focus-visible:ring-offset-2 dark:focus-visible:ring-offset-gray-800 transition-colors';
    navBtn.textContent = 'Navigate to station';
    navBtn.addEventListener('click', () => {
        const bounds = L.latLngBounds(
            [userLat, userLng],
            [station.latitude, station.longitude]
        ).pad(0.25);
        mymap.fitBounds(bounds, { maxZoom: 14, animate: true });
        // Re-open the popup in case the user closed it.
        bandHighlightLayer.eachLayer(l => {
            if (l instanceof L.Marker) l.openPopup();
        });
        // Far-band: drop the banner once the user has actually taken
        // the navigate step — they're now looking at the BTS.
        const banner = document.getElementById('band-far-banner');
        if (banner) banner.remove();
    });
    card.appendChild(navBtn);

    sidebar.insertBefore(card, sidebar.firstChild);
}

// PR #46.9: "Save this spot" CTA at the top of the sidebar after a
// click. Visible only for logged-in users (window._isLoggedIn cached
// from /session_check). One-click POST to /account/locations with the
// click coordinates + radius=0 ("exact spot" alert, configurable
// later from /account). The default name uses the current date so
// users get something sensible without typing — they can rename from
// /account whenever.
function renderSaveSpotShortcut(lat, lng, nearestCity) {
    if (!window._isLoggedIn) return;
    const sidebar = document.getElementById('sidebar');
    if (!sidebar) return;
    // Don't double-stack if user clicked twice in a row.
    const existing = sidebar.querySelector('#save-spot-cta');
    if (existing) existing.remove();

    // PR #47.2: build a recognisable default name. Prefer the nearest
    // station's city; fall back to coords. Both beat the date+time
    // string which told the user nothing about *where* the pin is.
    const defaultName = nearestCity
        ? `Near ${nearestCity}`
        : `Pin ${lat.toFixed(4)}, ${lng.toFixed(4)}`;

    const cta = document.createElement('div');
    cta.id = 'save-spot-cta';
    cta.className = 'col-span-full mb-2 p-3 rounded-lg bg-blue-50 dark:bg-blue-900/30 border border-blue-200 dark:border-blue-800 flex flex-col gap-2';

    const label = document.createElement('div');
    label.className = 'text-sm text-gray-800 dark:text-gray-100';
    label.textContent = 'Save this spot — we\'ll email you after our monthly UKE data refresh if coverage here changes.';

    const row = document.createElement('div');
    row.className = 'flex items-center gap-2';

    const nameInput = document.createElement('input');
    nameInput.type = 'text';
    nameInput.value = defaultName;
    nameInput.maxLength = 80;
    nameInput.className = 'flex-1 min-w-0 text-sm px-2 py-1.5 rounded border border-blue-300 dark:border-blue-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-400';
    nameInput.setAttribute('aria-label', 'Name for this saved spot');

    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'shrink-0 bg-blue-600 hover:bg-blue-700 text-white text-sm font-semibold py-1.5 px-3 rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-300 focus-visible:ring-offset-2 dark:focus-visible:ring-offset-gray-800 transition-colors';
    btn.textContent = 'Save';

    row.appendChild(nameInput);
    row.appendChild(btn);

    btn.addEventListener('click', () => {
        const chosenName = (nameInput.value || '').trim() || defaultName;
        btn.disabled = true;
        nameInput.disabled = true;
        btn.textContent = 'Saving…';
        globalFetch('/account/locations', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRF-Token': getCsrfToken(),
            },
            body: JSON.stringify({
                name: chosenName,
                lat: lat,
                lng: lng,
                radius_km: 0,
                alerting_enabled: true,
            }),
        }).then(resp => {
            if (resp && resp.success) {
                cta.classList.remove('bg-blue-50', 'dark:bg-blue-900/30', 'border-blue-200', 'dark:border-blue-800');
                cta.classList.add('bg-green-50', 'dark:bg-green-900/30', 'border-green-200', 'dark:border-green-800');
                label.textContent = `Saved as "${chosenName}". Rename or edit alerts in `;
                const acctLink = document.createElement('a');
                acctLink.href = '/account';
                acctLink.textContent = 'your account';
                acctLink.className = 'underline hover:no-underline font-medium';
                label.appendChild(acctLink);
                label.appendChild(document.createTextNode('.'));
                row.remove();
            } else {
                btn.disabled = false;
                nameInput.disabled = false;
                btn.textContent = 'Save';
                label.textContent = (resp && resp.error) || 'Save failed — try again from /account.';
            }
        }).catch(() => {
            btn.disabled = false;
            nameInput.disabled = false;
            btn.textContent = 'Save';
            label.textContent = 'Save failed — check your session, then try again.';
        });
    });
    cta.appendChild(label);
    cta.appendChild(row);
    sidebar.insertBefore(cta, sidebar.firstChild);
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

// Show empty state when no stations found.
// PR #46.8: dropped the 📡 icon — looked AI-generated next to the
// professional "No stations found" copy and didn't add real signal.
function showEmptyState() {
    let sidebarContent = document.getElementById('sidebar');
    sidebarContent.innerHTML = `
        <div class="empty-state col-span-full">
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
    // Audit fix (Low — frontend XSS): match the rel='noopener noreferrer'
    // already on the two string-template variants in the same file.
    // Without it, the popup window inherits window.opener and could
    // navigate this tab via opener.location = '...'.
    googleMapsLink.rel = 'noopener noreferrer';
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
    const sidebar = document.getElementById('sidebar');
    const messageBox = document.getElementById('messageBox');
    globalFetch(filterURL)
    .then(data => {
        // Assuming data is already the parsed JSON object
        if (!data || typeof data !== 'object') {
            console.error('Invalid data received:', data);
            return;  // Early return if data is invalid or not an object
        }
        // PR #46.5 follow-up: backend signals outside-PL with
        // outside_pl=true on /stations too (matches /submit_location
        // contract). Show the easter egg + clear skeleton instead of
        // rendering 0 results into a confused sidebar.
        if (data.outside_pl === true) {
            sidebar.innerHTML = '';
            updateBTSCount(0);
            if (messageBox) {
                messageBox.classList.remove('hidden');
                setTimeout(() => messageBox.classList.add('hidden'), 7700);
            }
            return;
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
        // PR #45: regex bumped from `^\d*\.?\d?$` (single digit before dot,
        // single digit after) to allow 1-2 digits before + 1 after. Old
        // pattern silently rejected the trailing zero in "10.0" so users
        // typing the boundary value got truncated to "10" → toFixed(1)
        // produced "10.0" again → infinite oscillation in some flows.
        const validValue = this.value.match(isInteger ? /^\d+$/ : /^\d{1,2}(\.\d?)?$/);

        if (validValue) {
            let value = isInteger ? parseInt(this.value, 10) : parseFloat(this.value);
            const max = parseFloat(this.max);

            if (value > max) {
                this.value = max.toString();
            } else if ((!isInteger && value <= 0) || (isInteger && value < 1)) {
                this.value = isInteger ? "1" : "0.5"; // matches step="0.5" min
            }
            // Don't reformat to toFixed(1) on every keystroke — it fights
            // the user's typing (e.g. typing "5" → toFixed → "5.0" →
            // cursor jumps). Browser already enforces step + max on blur.
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
        // PR #46.9: cache for renderSaveSpotShortcut() so it can decide
        // whether to show the "Save this spot" CTA without re-hitting
        // /session_check on every map click.
        window._isLoggedIn = isLoggedIn;
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