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
// 2026-04-28: split CartoDB Dark Matter into base + label layer so we
// can brightness-boost the labels independently. The combined `dark_all`
// tiles ship with very dim labels — readable on big monitors, basically
// illegible on a phone. The split + CSS `filter: brightness(1.6)
// contrast(1.2)` on `.dark-labels-bright` (see styles.css) keeps the
// dark aesthetic but makes street names actually readable. layerGroup
// wrapping preserves single-unit addLayer/removeLayer + the existing
// `Dark` entry in the layer control.
const darkTileLayer = L.layerGroup([
    L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_nolabels/{z}/{x}/{y}{r}.png', {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
        subdomains: 'abcd',
        maxZoom: 19,
    }),
    L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_only_labels/{z}/{x}/{y}{r}.png', {
        attribution: '',
        subdomains: 'abcd',
        maxZoom: 19,
        className: 'dark-labels-bright',
    }),
]);

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
// 2026-04-28: collapse the layer control on small viewports so the
// Street/Dark/Satellite radios don't eat ~140px of map width. Desktop
// keeps the always-expanded form for instant switching.
let activeBaseLayer = lightTileLayer;
const layerSwitcher = L.control({position: 'topright'});
layerSwitcher.onAdd = function() {
    const div = L.DomUtil.create('div', 'ss-segmented');
    const order = ['Street', 'Dark', 'Satellite'];
    div.innerHTML = order.map((name, i) =>
        `<button type="button" class="ss-seg-btn${i === 0 ? ' active' : ''}" data-layer="${name}">${t(name)}</button>`
    ).join('');
    L.DomEvent.disableClickPropagation(div);
    div.querySelectorAll('.ss-seg-btn').forEach(btn => {
        L.DomEvent.on(btn, 'click', function(e) {
            L.DomEvent.stop(e);
            const layer = baseMaps[btn.getAttribute('data-layer')];
            if (!layer || layer === activeBaseLayer) return;
            mymap.removeLayer(activeBaseLayer);
            mymap.addLayer(layer);
            activeBaseLayer = layer;
            div.querySelectorAll('.ss-seg-btn').forEach(b => b.classList.toggle('active', b === btn));
        });
    });
    return div;
};
layerSwitcher.addTo(mymap);

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
let gpsMarker;
let userSubmittedLocation = null;
let countryBoundaries;
let isFirstClick = true;
let currentBand = 'low';
let connectionLine = null;
let _locationReqSeq = 0;

const frequencyRanges = {
    high: [200, 500, 1000, 1500], // high band frequency distance radius
    mid: [300, 750, 1500, 2000], //  mid band frequency
    low: [500, 1500, 3000, 5000] // low band frequency
};

// Favicon-matched signal tiers (same palette as the verdict card, legend
// and signal bars): Excellent / Good / Fair / Poor.
const frequencyRangecolors = ['#16A34A', '#FACC15', '#F97316', '#DC2626'];

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

if (!document.getElementById('ss-search-styles')) {
    const st = document.createElement('style');
    st.id = 'ss-search-styles';
    st.textContent = `
    .ss-search-box{display:flex;align-items:stretch;height:40px;background:#fff;border:1px solid #e2e8f0;border-radius:10px;box-shadow:0 1px 5px rgba(0,0,0,.14);overflow:hidden;box-sizing:border-box;transition:box-shadow .15s,border-color .15s;}
    .ss-search-box:focus-within{border-color:#3b82f6;box-shadow:0 0 0 3px rgba(59,130,246,.25);}
    .ss-search-icon{width:16px;height:16px;color:#64748b;flex:none;align-self:center;margin-left:11px;}
    #addressSearchInput{flex:1;min-width:0;width:12rem;border:none;outline:none;background:transparent;padding:0 8px;font-size:14px;color:#1f2937;}
    #addressSearchInput::placeholder{color:#94a3b8;}
    .ss-locate-btn{display:flex;align-items:center;justify-content:center;width:38px;flex:none;border:none;border-left:1px solid #e2e8f0;background:transparent;color:#475569;cursor:pointer;transition:background .15s,color .15s;}
    .ss-locate-btn:hover{background:#f0f3f7;color:#2563eb;}
    .ss-locate-btn svg{width:17px;height:17px;}
    .dark .ss-locate-btn{color:#cbd5e1;border-left-color:#374151;}
    .dark .ss-locate-btn:hover{background:#374151;color:#93c5fd;}
    @media (max-width:640px){#addressSearchInput{width:9rem;}}
    .ss-suggestions{margin-top:5px;background:#fff;border-radius:9px;box-shadow:0 6px 20px rgba(0,0,0,.2);overflow:hidden;max-height:260px;overflow-y:auto;}
    .ss-suggestion{padding:9px 12px;cursor:pointer;font-size:13px;color:#334155;border-bottom:1px solid #f1f5f9;}
    .ss-suggestion:last-child{border-bottom:none;}
    .ss-suggestion:hover{background:#eff6ff;}
    .dark .ss-search-box{background:#1f2937;border-color:#374151;}
    .dark #addressSearchInput{color:#f1f5f9;}
    .dark .ss-search-box svg{color:#94a3b8;}
    .dark .ss-suggestions{background:#1f2937;box-shadow:0 6px 20px rgba(0,0,0,.5);}
    .dark .ss-suggestion{color:#e2e8f0;border-bottom-color:#374151;}
    .dark .ss-suggestion:hover{background:#374151;}`;
    document.head.appendChild(st);
}

let addressSearch = L.control({position: 'topleft'});
addressSearch.onAdd = function(map) {
    const div = L.DomUtil.create('div', 'address-search-control');
    div.innerHTML = `
        <div class="ss-search-box">
            <svg class="ss-search-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>
            <input type="text" id="addressSearchInput" autocomplete="off" placeholder="${t('Search address or place')}">
            <button id="useMyLocationBtn" type="button" class="ss-locate-btn" title="${t('Use My Location')}" aria-label="${t('Use My Location')}">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"></circle><line x1="12" y1="2" x2="12" y2="5"></line><line x1="12" y1="19" x2="12" y2="22"></line><line x1="2" y1="12" x2="5" y2="12"></line><line x1="19" y1="12" x2="22" y2="12"></line></svg>
            </button>
        </div>
        <div id="address-suggestions" class="ss-suggestions" style="display:none;"></div>
    `;
    L.DomEvent.disableClickPropagation(div);
    L.DomEvent.disableScrollPropagation(div);
    const locateBtn = div.querySelector('#useMyLocationBtn');
    if (locateBtn) {
        L.DomEvent.on(locateBtn, 'click', function(e) {
            L.DomEvent.stop(e);
            requestAndSendGPSLocation();
        });
    }
    return div;
};
addressSearch.addTo(mymap);

(function setupAddressSearch() {
    const input = document.getElementById('addressSearchInput');
    const box = document.getElementById('address-suggestions');
    if (!input || !box) return;
    let timer = null;
    const hide = () => { box.style.display = 'none'; box.innerHTML = ''; };
    input.addEventListener('input', function() {
        const q = this.value.trim();
        clearTimeout(timer);
        if (q.length < 3) { hide(); return; }
        timer = setTimeout(() => {
            globalFetch(`/geocode?q=${encodeURIComponent(q)}`)
                .then(data => {
                    const results = (data && data.results) || [];
                    if (!results.length) { hide(); return; }
                    box.innerHTML = '';
                    results.forEach(r => {
                        const item = document.createElement('div');
                        item.className = 'ss-suggestion';
                        item.textContent = r.display;
                        item.addEventListener('click', () => {
                            input.value = r.display;
                            hide();
                            if (marker) { try { mymap.removeLayer(marker); } catch (e) {} }
                            marker = L.marker([r.lat, r.lng], { icon: greenIcon }).addTo(mymap);
                            mymap.setView([r.lat, r.lng], 14);
                            currentFilters.lat = r.lat;
                            currentFilters.lng = r.lng;
                            isFirstClick = false;
                            sendLocation(r.lat, r.lng);
                        });
                        box.appendChild(item);
                    });
                    box.style.display = 'block';
                })
                .catch(() => hide());
        }, 350);
    });
    input.addEventListener('keydown', (e) => { if (e.key === 'Escape') hide(); });
    document.addEventListener('click', (e) => {
        if (!input.parentElement.contains(e.target)) hide();
    });
})();

let frequencyRangeLegend = L.control({position: 'topleft'});

    frequencyRangeLegend.onAdd = function(map) {
        let div = L.DomUtil.create('div', 'gps-location-control');
        div.style.cursor = 'grab';
        div.style.userSelect = "none";

        let toggleBtn = L.DomUtil.create('button', 'map-control-btn', div);
        toggleBtn.id = 'toggleFrequencyRangeLegendBtn';
        toggleBtn.title = 'Signal Range Legend';
        toggleBtn.innerHTML = `
            <svg class="control-icon" viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"></circle><circle cx="12" cy="12" r="4.5"></circle><circle cx="12" cy="12" r="1" fill="currentColor"></circle></svg>
            <span class="control-label">${t('Range')}</span>
        `;

        // 2026-04-28: legend is HIDDEN by default on mobile (was always
        // open and covered ~half the map on iPhone 16 Pro). Toggle
        // button at top-left opens it. Desktop unchanged.
        const legendInitiallyHidden = true;
        let legendDiv = L.DomUtil.create(
            'div',
            'frequency-range-container bg-white p-1 rounded shadow text-black dark:bg-black dark:text-white accent-blue-500 dark:accent-gray-400'
            + (legendInitiallyHidden ? ' hidden' : ''),
            div,
        );
        legendDiv.innerHTML = `
            <table class="frequency-table min-w-full divide-y divide-gray-200">
                <thead class="text-gray-700 font-bold dark:text-white">
                    <tr>
                        <th>${t('Signal Strength')}</th>
                        <th class="column-high" data-band="high">${t('High Band Frequency')}<br>(5G3600, L2600) (km)</th>
                        <th class="column-mid" data-band="mid">${t('Mid Band Frequency')} <br>(5G/L2100, L1800) (km)</th>
                        <th class="column-low" data-band="low">${t('Low Band Frequency')}<br>(L900, L800, G900) (km)</th>
                    </tr>
                </thead>
                <tbody class="text-gray-700 font-bold dark:text-white divide-y divide-gray-200">
                    <tr style="background-color:#16A34A;color:#ffffff"><td>${t('Excellent')}</td><td>0.2</td><td>0.3</td><td>0.5</td></tr>
                    <tr style="background-color:#FACC15;color:#1f2937"><td>${t('Good')}</td><td>0.5</td><td>0.75</td><td>1.5</td></tr>
                    <tr style="background-color:#F97316;color:#1f2937"><td>${t('Fair')}</td><td>1.0</td><td>1.5</td><td>3.0</td></tr>
                    <tr style="background-color:#DC2626;color:#ffffff"><td>${t('Poor')}</td><td>1.5</td><td>2.0</td><td>5.0</td></tr>
                </tbody>
            </table>
            <p class="freq-legend-hint">${t('Tap a band column to change the ring range on the map')}</p>
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
        let offsetX = 0;
        let offsetY = 0;
        const onDragStart = function(e) {
            startPos = { x: e.clientX, y: e.clientY };
            div.style.cursor = 'grabbing';
            document.addEventListener('mousemove', onDragMove);
            document.addEventListener('mouseup', onDragEnd);
        };

        const onDragMove = function(e) {
            if (startPos) {
                offsetX += e.clientX - startPos.x;
                offsetY += e.clientY - startPos.y;

                let mapContainer = mymap.getContainer();
                let base = div.getBoundingClientRect();
                let mapRect = mapContainer.getBoundingClientRect();
                let homeLeft = base.left - offsetX - mapRect.left;
                let homeTop = base.top - offsetY - mapRect.top;
                let maxOffsetX = mapContainer.offsetWidth - div.offsetWidth - homeLeft;
                let maxOffsetY = mapContainer.offsetHeight - div.offsetHeight - homeTop;

                offsetX = Math.max(-homeLeft, Math.min(offsetX, maxOffsetX));
                offsetY = Math.max(-homeTop, Math.min(offsetY, maxOffsetY));

                div.style.transform = `translate(${offsetX}px, ${offsetY}px)`;

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
    div.innerHTML = `${t('BTS count:')} <span id="btsCounter">0</span>`;
    return div;
}
btsCountControl.addTo(mymap);

let filterControl = L.control({position: 'topright'});
filterControl.onAdd = function(map) {
    let div = L.DomUtil.create('div', 'filter-control-container');
    div.innerHTML = `
        <button id="toggle-filters-btn" class="inline-flex items-center gap-1.5 bg-white hover:bg-gray-50 dark:bg-gray-800 dark:hover:bg-gray-700 text-slate-700 dark:text-gray-200 border border-gray-200 dark:border-gray-600 text-xs font-medium py-1.5 px-3 rounded-lg shadow-sm">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"></polygon></svg>
        ${t('Filters')}
        </button>

        <div id="filterContainer" class="bg-white p-1 rounded shadow text-black dark:bg-black dark:text-white w-76 accent-blue-500 dark:accent-gray-400 hidden">
            <div class="static-content">
                <div class="my-2">
                    <p class="text-gray-700 font-bold dark:text-white">${t('Service Provider:')}</p>
                    <div class="flex flex-wrap label-container gap-1">    
                        <label><input type="checkbox" name="service_provider" value="P4 Sp. z o.o.'"> Play</label>
                        <label><input type="checkbox" name="service_provider" value="Orange Polska S.A."> Orange</label>
                        <label><input type="checkbox" name="service_provider" value="T-Mobile Polska S.A."> T-Mobile</label>
                        <label><input type="checkbox" name="service_provider" value="POLKOMTEL Sp. z o.o."> Plus</label>
                    </div>
                </div>

                <div class="my-2">
                    <p class="text-gray-700 font-bold dark:text-white">${t('Frequency:')}</p>
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

                <div class="flex gap-2 mt-2">
                    <button id="apply-filters" class="apply-filters-btn flex-1 text-white bg-blue-300 dark:bg-gray-700 hover:bg-blue-500 dark:hover:bg-gray-500 rounded">
                        ${t('Apply Filters')}
                    </button>
                    <button id="clear-filters-btn" class="px-3 text-gray-700 bg-gray-200 hover:bg-gray-300 dark:bg-gray-600 dark:text-white dark:hover:bg-gray-500 rounded">
                        ${t('Clear')}
                    </button>
                </div>

                <div class="slider-container my-2">
                    <div class="flex justify-between items-center">
                        <button id="showNearestBtn" class="mt-2 w-48 text-white bg-blue-300 dark:bg-gray-700 hover:bg-blue-500 dark:hover:bg-gray-500 rounded">${t('Show Nearest BTS')}</button>
                    </div>
                    <input type="number" id="nearestBtsRange" min="1" max="10" placeholder="" class="w-[4.25rem] mt-1 bg-blue-100 hover:bg-blue-300 dark:bg-gray-700 dark:hover:bg-gray-500">
                </div>

                <div class="slider-container my-2">
                    <div class="flex justify-between items-center">
                        <button id="showWithinDistanceBtn" class="mt-2 w-48 text-white bg-blue-300 dark:bg-gray-700 hover:bg-blue-500 dark:hover:bg-gray-500 rounded">${t('Show BTS Within Distance')}</button>
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

document.getElementById('clear-filters-btn').addEventListener('click', resetFiltersUI);

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
    // Leaflet's locate to find the user's position. Handlers are bound once
    // below — re-binding here stacked a new locationerror listener per click,
    // so every denied tap fired one extra toast.
    mymap.locate({ setView: true, maxZoom: 13, enableHighAccuracy: true, timeout: 10000, maximumAge: 0 });
}

mymap.on('locationfound', function(e) {
    let userLat = e.latlng.lat;
    let userLng = e.latlng.lng;
    if (gpsMarker) { try { mymap.removeLayer(gpsMarker); } catch (err) {} }
    gpsMarker = L.marker([userLat, userLng], {icon: greenIcon}).addTo(mymap).bindPopup(`<div class=" dark:text-white">${t('Your Location')}</div>`).openPopup();
    sendLocation(userLat, userLng);
});

mymap.on('locationerror', function(e) {
    if (e.message.includes("denied")) {
        showToast(t('Location permission was denied. Please enable it to use this feature.'), 'error');
    } else if (e.message.includes("unavailable")) {
        showToast(t('Location information is currently unavailable.'), 'error');
    } else if (e.message.includes("timeout")) {
        showToast(t('The request to get your location timed out. Please try again.'), 'error');
    } else {
        showToast(t('An unknown location error occurred.') + ' ' + e.message, 'error');
    }
});

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

    const reqSeq = ++_locationReqSeq;
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
        if (reqSeq !== _locationReqSeq) return;
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
            isFirstClick = false;
            updateBTSCount(data.count);
            showSidebar();
            displayStations(data.stations);
            clearRings();
            addRingsForLocation(lat, lng);
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
        if (reqSeq !== _locationReqSeq) return;
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
    label.textContent = t('Check per-band coverage gaps at this spot');

    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'shrink-0 bg-gray-700 hover:bg-gray-800 dark:bg-gray-600 dark:hover:bg-gray-500 text-white text-xs font-semibold py-1 px-2.5 rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gray-400 focus-visible:ring-offset-2 dark:focus-visible:ring-offset-gray-800 transition-colors';
    btn.textContent = t('Analyse');
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
    widget.innerHTML = `<div class="text-xs text-gray-500 dark:text-gray-400">${t('Checking coverage at this spot…')}</div>`;
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
            title.textContent = t('Coverage at this spot');
            widget.appendChild(title);

            const summaryEl = document.createElement('div');
            summaryEl.className = `text-xs ${summaryClass} mb-2`;
            summaryEl.textContent = summaryText;
            widget.appendChild(summaryEl);

            const hint = document.createElement('div');
            hint.className = 'text-[10px] text-gray-500 dark:text-gray-400 mb-1';
            hint.textContent = t('Click a band to show its closest BTS on the map.');
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
            foot.textContent = t('Thresholds: high-band ≤1.5 km · mid ≤2 km · low ≤5 km. Line-of-sight; real signal varies.');
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
            <div class="font-semibold mb-1">${t('Nearest')} ${escapeHtml(gap.band)} · ${gap.nearest_distance_km} km</div>
            <b>${t('Service Provider:')}</b> ${escapeHtml(station.service_provider)}<br>
            <b>${t('Base Station ID:')}</b> ${escapeHtml(station.basestation_id)}<br>
            <b>${t('Frequency Bands:')}</b> ${escapeHtml(bands)}<br>
            <b>${t('City:')}</b> ${escapeHtml(station.city)}<br>
            <b>${t('Location:')}</b> ${escapeHtml(station.location)}<br>
            <b>${t('Coordinates:')}</b> ${lat}°N, ${lng}°E<br>
            <a href="${escapeHtml(gmaps)}" target="_blank" rel="noopener noreferrer" class="no-underline hover:underline text-blue-500 hover:text-blue-700 dark:text-blue-300 dark:hover:text-blue-400 font-semibold">${t('View on Google Maps')}</a>
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
    title.textContent = `${t('Nearest')} ${gap.band} · ${gap.nearest_distance_km} km`;
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
    navBtn.className = 'mt-2 w-full inline-flex items-center justify-center gap-2 bg-gray-50 hover:bg-gray-100 dark:bg-gray-700/50 dark:hover:bg-gray-700 text-slate-700 dark:text-slate-200 border border-gray-200 dark:border-gray-600 text-sm font-medium py-2 px-3 rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 focus-visible:ring-offset-2 dark:focus-visible:ring-offset-gray-800 transition-colors';
    navBtn.innerHTML = `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="3 11 22 2 13 21 11 13 3 11"></polygon></svg> ${t('Navigate to station')}`;
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
    label.textContent = t('Save this spot — we\'ll email you after our monthly UKE data refresh if coverage here changes.');

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
    btn.textContent = t('Save');

    row.appendChild(nameInput);
    row.appendChild(btn);

    btn.addEventListener('click', () => {
        const chosenName = (nameInput.value || '').trim() || defaultName;
        btn.disabled = true;
        nameInput.disabled = true;
        btn.textContent = t('Saving…');
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
                label.textContent = `${t('Saved as')} "${chosenName}". ${t('Rename or edit alerts in')} `;
                const acctLink = document.createElement('a');
                acctLink.href = '/account';
                acctLink.textContent = t('your account');
                acctLink.className = 'underline hover:no-underline font-medium';
                label.appendChild(acctLink);
                label.appendChild(document.createTextNode('.'));
                row.remove();
            } else {
                btn.disabled = false;
                nameInput.disabled = false;
                btn.textContent = t('Save');
                label.textContent = (resp && resp.error) || t('Save failed — try again from /account.');
            }
        }).catch(() => {
            btn.disabled = false;
            nameInput.disabled = false;
            btn.textContent = t('Save');
            label.textContent = t('Save failed — check your session, then try again.');
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

    if (distanceMeters <= thresholds[0]) return { level: 'excellent', bars: 4, label: t('Excellent'), dbm: -70 };
    if (distanceMeters <= thresholds[1]) return { level: 'good', bars: 3, label: t('Good'), dbm: -85 };
    if (distanceMeters <= thresholds[2]) return { level: 'fair', bars: 2, label: t('Fair'), dbm: -95 };
    return { level: 'poor', bars: 1, label: t('Poor'), dbm: -110 };
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

// Clean inline copy/check icons (feather, currentColor) — no emoji glyph.
const COPY_ICON_SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>';
const CHECK_ICON_SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="20 6 9 17 4 12"></polyline></svg>';

// Copy to clipboard helper
function copyToClipboard(text, button) {
    navigator.clipboard.writeText(text).then(() => {
        button.innerHTML = CHECK_ICON_SVG;
        button.style.color = '#16a34a';
        setTimeout(() => {
            button.innerHTML = COPY_ICON_SVG;
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
            <div class="empty-state-title">${t('No stations found')}</div>
            <div class="empty-state-text">${t('Try adjusting your filters or clicking a different location on the map.')}</div>
        </div>
    `;
    sidebarContent.classList.remove('hidden');
}


const VERDICT_HEADLINES = {
    excellent: 'Strong signal',
    good: 'Good signal',
    fair: 'Patchy signal',
    poor: 'Weak signal',
};
const VERDICT_PROVIDERS = [
    ['Orange', 'orange'],
    ['Play', 'play'],
    ['Plus', 'plus'],
    ['T-Mobile', 'tmobile'],
];

function formatVerdictDistance(km) {
    return km < 1 ? `${Math.round(km * 1000)} m` : `${km.toFixed(1)} km`;
}

function createVerdictCard(stations) {
    currentStations = stations;
    const total = stations.length;
    const avgDistance = (stations.reduce((sum, st) => sum + st.distance, 0) / total).toFixed(2);
    const nearest = stations.reduce((min, st) => st.distance < min.distance ? st : min, stations[0]);
    const signal = getSignalStrength(nearest.distance);
    const has5G = stations.some(st => (st.frequency_bands || []).some(b => String(b).toUpperCase().includes('5G')));
    const provider = providerShortNames[nearest.service_provider] || nearest.service_provider;

    const byProvider = {};
    stations.forEach(st => {
        const name = providerShortNames[st.service_provider] || st.service_provider;
        if (!(name in byProvider) || st.distance < byProvider[name]) byProvider[name] = st.distance;
    });
    const providerSummary = VERDICT_PROVIDERS.map(([name, cls]) => {
        if (name in byProvider) {
            return `<span class="op-chip"><span class="provider-dot ${cls}"></span>${escapeHtml(name)} · ${formatVerdictDistance(byProvider[name])}</span>`;
        }
        return `<span class="op-chip text-gray-400 dark:text-gray-500">${escapeHtml(name)} · ${t('none in range')}</span>`;
    }).join('');

    const subline = `${t('Nearest mast:')} ${formatVerdictDistance(nearest.distance)} (${escapeHtml(provider)})${has5G ? ' · ' + escapeHtml(t('5G in range')) : ''}`;

    const card = document.createElement('div');
    card.id = 'verdict-card';
    card.className = 'stats-panel col-span-full';
    card.innerHTML = `
        <div class="result-summary">
            <div class="result-verdict">
                <span class="verdict-glyph">${createSignalBars(signal)}</span>
                <div class="result-verdict-text">
                    <div class="verdict-headline">${t(VERDICT_HEADLINES[signal.level])}</div>
                    <div class="verdict-subline">${subline}</div>
                </div>
            </div>
            <div class="result-stats">
                <div class="rstat"><span class="rstat-value">${Number(total)}</span><span class="rstat-label">${t('Stations')}</span></div>
                <div class="rstat"><span class="rstat-value">${escapeHtml(avgDistance)}</span><span class="rstat-label">${t('Avg Dist')}</span></div>
                <div class="rstat"><span class="rstat-value">${nearest.distance.toFixed(2)}</span><span class="rstat-label">${t('Nearest')}</span></div>
            </div>
        </div>
        <div class="result-legend">
            <div class="result-operators">${providerSummary}</div>
            <div class="result-disclaimer">${t('Estimated from mast distance and UKE data. Not a measured signal.')}</div>
        </div>
    `;
    return card;
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

    sidebarContent.appendChild(createVerdictCard(stations));

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

// Store stations for quick access (set by createVerdictCard on each render)
let currentStations = [];

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
    linksDiv.className = 'mt-2 pt-2 border-t border-gray-200 dark:border-gray-700';

    let googleMapsLink = document.createElement('a');
    googleMapsLink.href = `https://www.google.com/maps/search/?api=1&query=${station.latitude},${station.longitude}`;
    googleMapsLink.target = '_blank';
    // Audit fix (Low — frontend XSS): match the rel='noopener noreferrer'
    // already on the two string-template variants in the same file.
    // Without it, the popup window inherits window.opener and could
    // navigate this tab via opener.location = '...'.
    googleMapsLink.rel = 'noopener noreferrer';
    googleMapsLink.textContent = `${t('Open in Google Maps')} ↗`;
    googleMapsLink.className = 'inline-block mb-2 text-xs no-underline hover:underline text-blue-600 hover:text-blue-700 dark:text-blue-300 dark:hover:text-blue-400 font-semibold';
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
            <b>${Number(index) + 1}. ${t('Service Provider:')}</b> ${escapeHtml(station.service_provider)}<br>
            <b>${t('Distance:')}</b> ${formattedDistance}km<br>
            <b>${t('Base Station ID:')}</b> ${escapeHtml(station.basestation_id)}<br>
            <b>${t('Frequency Bands:')}</b> ${escapeHtml(bands)}<br>
            <b>${t('City:')}</b> ${escapeHtml(station.city)}<br>
            <b>${t('Location:')}</b> ${escapeHtml(station.location)}<br>
            <b>${t('Coordinates:')}</b> ${formattedLat}°${latHemisphere}, ${formattedLng}°${lngHemisphere}<br>
            <a href="${escapeHtml(googleMapsLink)}" target="_blank" rel="noopener noreferrer" class="no-underline hover:underline text-blue-500 hover:text-blue-700 dark:text-blue-300 dark:hover:text-blue-400 font-semibold">${t('View on Google Maps')}</a>
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

    // Group frequency bands by type. Labels (5G:/LTE:/3G:/GSM:) stay bold;
    // band values render as neutral text — the per-station signal tier is
    // already carried by the signal bars, so bands aren't colour-coded.
    const bandsArr = Array.isArray(station.frequency_bands) ? station.frequency_bands : [];
    const bands5G = bandsArr.filter(b => b.startsWith('5G'));
    const bandsLTE = bandsArr.filter(b => b.startsWith('LTE'));
    const bandsUMTS = bandsArr.filter(b => b.startsWith('UMTS'));
    const bandsGSM = bandsArr.filter(b => b.startsWith('GSM'));

    function bandGroup(gen, bands) {
        if (bands.length === 0) return '';
        // Per-band colour by THIS band's reach at the station distance — the
        // actual signal: a far low-band can be "good" while a high-band at the
        // same spot is "poor". This is data, not decoration.
        const chips = bands.map(b =>
            `<span class="band-chip" style="color:${getFrequencyColorForDistance(b, station.distance)}">${escapeHtml(b)}</span>`
        ).join('');
        return `<div class="band-row"><span class="gen-tag">${gen}</span><span class="band-chips">${chips}</span></div>`;
    }

    const bandsHtml =
        bandGroup('5G', bands5G) +
        bandGroup('LTE', bandsLTE) +
        bandGroup('3G', bandsUMTS) +
        bandGroup('GSM', bandsGSM);

    const cityLocation = station.location
        ? `${escapeHtml(station.city)} • ${escapeHtml(station.location)}`
        : escapeHtml(station.city);

    return `
        <div class="dark:text-white">
            <div class="card-header">
                <h4>${Number(index) + 1}. ${escapeHtml(station.basestation_id)}</h4>
                <span class="signal-label" title="${escapeHtml(signal.label)} · ≈ ${signal.dbm} dBm">
                    ${createSignalBars(signal)}
                    <span class="signal-${signal.level} font-semibold hidden sm:inline">${escapeHtml(signal.label)}</span>
                </span>
            </div>
            <div class="card-meta">
                <span class="provider-dot ${escapeHtml(providerClass)}"></span>
                <span class="font-medium">${escapeHtml(providerShort)}</span>
                <span class="text-gray-500 dark:text-gray-400">•</span>
                <span>${formattedDistance} km</span>
                ${bearingHtml}
            </div>
            <div class="bands-block">${bandsHtml}</div>
            <p class="text-xs md:text-sm mb-1 text-gray-600 dark:text-gray-300">${cityLocation}</p>
            <p class="text-xs md:text-sm mb-0 text-gray-500 dark:text-gray-400">
                ${coordsText}
                <button data-copy-coords="${formattedLat}, ${formattedLng}" class="copy-btn" title="${t('Copy coordinates')}" aria-label="${t('Copy coordinates')}">${COPY_ICON_SVG}</button>
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
    const reqSeq = ++_locationReqSeq;
    showLoadingSkeleton();
    let filterURL = constructFilterURL();
    const sidebar = document.getElementById('sidebar');
    const messageBox = document.getElementById('messageBox');
    globalFetch(filterURL)
    .then(data => {
        if (reqSeq !== _locationReqSeq) return;
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
            clearRings();
            addRingsForLocation(currentFilters.lat, currentFilters.lng);
        }
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
                <button id="submitCoords" class="mt-2 w-48 bg-blue-300 dark:bg-gray-700 hover:bg-blue-500 dark:hover:bg-gray-500 text-white rounded">${t('Search')}</button>
                    <div class="flex space-x-2">
                    <input type="number" id="latitudeInput" placeholder="52.230 (°N)" class="w-[5.5rem] mt-0.5 bg-blue-100 hover:bg-blue-300 dark:bg-gray-700 dark:hover:bg-gray-500" min="48" max="58" step="0.1">
                    <input type="number" id="longitudeInput" placeholder="21.003 (°E)" class="w-[5.5rem] mt-0.5 bg-blue-100 hover:bg-blue-300 dark:bg-gray-700 dark:hover:bg-gray-500" min="13.5" max="24.5" step="0.1">
                    </div>
                </div>
                <div id="searchByBtsContainer" class="mt-4 flex flex-col space-y-0.5">
                    <button id="submitfilteredstation" class="w-48 bg-blue-300 dark:bg-gray-700 hover:bg-blue-500 dark:hover:bg-gray-500 text-white rounded">${t('Search')}</button>
                    <div class="flex space-x-2">
                        <input type="text" id="baseStationIdInput" placeholder="${t('Enter Base Station ID')}" class="w-[8rem] mt-0.5 bg-blue-100 hover:bg-blue-300 dark:bg-gray-700 dark:hover:bg-gray-500">
                    </div>
                </div>`;
        } else {
            dynamicContent.innerHTML = `
                <div id="latLngContainer" class="opacity-50 cursor-not-allowed flex flex-col space-y-0.5 title="${t('Log in to use this feature.')}">
                    <button id="submitCoords" class="mt-2 w-48 bg-blue-300 dark:bg-gray-700 hover:bg-blue-500 dark:hover:bg-gray-500 text-white rounded cursor-not-allowed" disabled title="${t('Log in to use this feature.')}">${t('Search')}</button>
                    <div class="flex space-x-2">
                        <input type="number" id="latitudeInput" placeholder="52.230 (°N)" class="w-[5.5rem] mt-0.5 bg-blue-100 hover:bg-blue-300 dark:bg-gray-700 dark:hover:bg-gray-500 cursor-not-allowed" min="48" max="58" step="0.1" disabled title="${t('Log in to use this feature.')}">
                        <input type="number" id="longitudeInput" placeholder="21.003 (°E)" class="w-[5.5rem] mt-0.5 bg-blue-100 hover:bg-blue-300 dark:bg-gray-700 dark:hover:bg-gray-500 cursor-not-allowed" min="13.5" max="24.5" step="0.1" disabled title="${t('Log in to use this feature.')}">
                    </div>
                </div>
                <div id="searchByBtsContainer" class="mt-4 opacity-50 cursor-not-allowed flex flex-col space-y-0.5 title="${t('Log in to use this feature.')}">
                    <button id="submitfilteredstation" class="w-48 bg-blue-300 dark:bg-gray-700 hover:bg-blue-500 dark:hover:bg-gray-500 text-white rounded cursor-not-allowed" disabled title="${t('Log in to use this feature.')}">${t('Search')}</button>
                    <div class="flex space-x-2">
                        <input type="text" id="baseStationIdInput" placeholder="${t('Enter Base Station ID')}" class="w-[8rem] mt-0.5 bg-blue-100 hover:bg-blue-300 dark:bg-gray-700 dark:hover:bg-gray-500 cursor-not-allowed" disabled title="${t('Log in to use this feature.')}">
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
        showToast(t('Both latitude and longitude must be filled out to proceed.'), 'error');
        return;
    }

    let lat = parseFloat(latitudeInput.value);
    let lng = parseFloat(longitudeInput.value);
    let validationPassed = true;

    if (isNaN(lat) || lat < 48 || lat > 58) {
        showToast(t('Latitude is out of range. Please enter a value between 48 and 58.'), 'error');
        validationPassed = false;
    }

    if (isNaN(lng) || lng < 13.5 || lng > 24.5) {
        showToast(t('Longitude is out of range. Please enter a value between 13 and 25.'), 'error');
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
        showToast(t('Base Station ID must be up to 7 letters or digits.'), 'error');
        return;
    }
    if (!basestation_id) {
        showToast(t('Base Station ID is required'), 'error');
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
        showToast(t('Please submit your location before changing the frequency.'), 'error');
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

// 2026-04-29: deep-link support — when the URL has ?lat=X&lng=Y query
// params (e.g. clicked "Open on Signal-Scout" from a coverage-alert
// email), auto-trigger the same flow as if the user had clicked the
// map at that spot: re-center, fire submit_location, populate sidebar.
// Without this the email link landed on the bare home page and the
// reader had to manually click again.
document.addEventListener('DOMContentLoaded', function () {
    var params;
    try { params = new URLSearchParams(window.location.search); }
    catch (e) { return; }
    var latStr = params.get('lat');
    var lngStr = params.get('lng');
    if (!latStr || !lngStr) return;
    var lat = parseFloat(latStr), lng = parseFloat(lngStr);
    if (isNaN(lat) || isNaN(lng)) return;
    // Polish bounds sanity — backend rejects out-of-bounds anyway, but
    // skip the round-trip if the params are obviously wrong.
    if (lat < 49.0 || lat > 55.5 || lng < 14.0 || lng > 24.2) return;

    // Wait one tick so mymap, sendLocation, CSRF token meta etc. are
    // wired before we call them. 350 ms is enough for tile preload too.
    setTimeout(function () {
        try {
            if (typeof mymap !== 'undefined' && mymap.setView) {
                mymap.setView([lat, lng], 13);
            }
            // Mirror the on-click handler: drop a green pin at the spot
            // BEFORE firing sendLocation. The click handler does this on
            // line ~167; without replicating it, the deep-link path
            // populated stations + rings but no user marker.
            if (typeof marker !== 'undefined') {
                if (marker) { try { mymap.removeLayer(marker); } catch (e) {} }
                marker = L.marker([lat, lng], { icon: greenIcon }).addTo(mymap);
            }
            // Mark first-click consumed so subsequent map clicks fall
            // into fetchStations() path (matching click-handler behaviour).
            if (typeof isFirstClick !== 'undefined') {
                isFirstClick = false;
            }
            if (typeof sendLocation === 'function') {
                sendLocation(lat, lng);
            }
            // Strip the params so a refresh / share doesn't keep
            // re-triggering — the spot is already loaded in state.
            try {
                params.delete('lat'); params.delete('lng');
                var rest = params.toString();
                var newUrl = window.location.pathname
                    + (rest ? '?' + rest : '')
                    + window.location.hash;
                window.history.replaceState({}, document.title, newUrl);
            } catch (e) { /* noop */ }
        } catch (e) { /* noop */ }
    }, 350);
});

// Language switch is a ?lang= reload; carry the active spot so it isn't lost.
document.addEventListener('DOMContentLoaded', function () {
    var toggle = document.getElementById('langToggle');
    if (!toggle) return;
    toggle.addEventListener('click', function (e) {
        if (currentFilters.lat == null || currentFilters.lng == null) return;
        try {
            var url = new URL(toggle.href, window.location.origin);
            url.searchParams.set('lat', currentFilters.lat);
            url.searchParams.set('lng', currentFilters.lng);
            e.preventDefault();
            window.location.href = url.toString();
        } catch (err) { /* keep default href */ }
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

function applyFrequencyColorsToTooltipContent(content, distance) {
    // Find the distance if not provided
    if (!distance) {
        const distanceMatch = content.match(new RegExp(`<b>${t('Distance:')}<\\/b>\\s*(\\d+\\.?\\d*)km`));
        if (distanceMatch) {
            distance = parseFloat(distanceMatch[1]);
        }
    }

    if (distance) {
        // Find the frequency bands substring in the content
        const bandsMatch = content.match(new RegExp(`<b>${t('Frequency Bands:')}<\\/b>\\s*([^<]+)`));
        if (bandsMatch && bandsMatch[1]) {
            // Split the bands into array
            const bandsList = bandsMatch[1].split(',').map(band => band.trim());
            const coloredBandsHtml = bandsList.map(band => {
                const colorClass = getFrequencyColorForDistance(band, distance);

                return `<span class="text-${colorClass}-600">${band}</span>`;
            }).join(', ');

            content = content.replace(bandsMatch[0], `<b>${t('Frequency Bands:')}</b> ${coloredBandsHtml}`);
        }
    }

    return content;
}