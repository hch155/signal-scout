// map.html
updateDynamicContent()

var mymap = L.map('mapid').setView([52.231, 21.004], 7); //  default location and zoom level

var lightTileLayer = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; <a href="www.openstreetmap.org/copyright">OpenStreetMap contributors</a>'
}).addTo(mymap);

var darkTileLayer = L.tileLayer('https://tiles.stadiamaps.com/tiles/alidade_smooth_dark/{z}/{x}/{y}{r}.png', {
    attribution: '&copy; <a href="https://www.stadiamaps.com/" target="_blank">Stadia Maps</a> &copy; <a href="https://openmaptiles.org/" target="_blank">OpenMapTiles</a> &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
});  

var greenIcon = new L.Icon({ 
iconUrl: 'static/css/images/marker-icon-green.png', shadowUrl: 'static/css/images/marker-shadow.png', iconSize: [25, 41], iconAnchor: [12, 41], popupAnchor: [1, -34], shadowSize: [41, 41]
});

var providerColors = {
    'P4 Sp. z o.o.': 'violet', // purple/violet marker for Play
    'Orange Polska S.A.': 'orange',
    'T-Mobile Polska S.A.': 'red', 
    'POLKOMTEL Sp. z o.o.': 'blue',
    'AERO 2 Sp. z o.o.': 'blue' 
};

const initialFilters = {
    lat: undefined,
    lng: undefined,
    limit: undefined,
    maxDistance: undefined,
    serviceProvider: [],
    frequencyBands: [],
    mode: 'all' // 'all', 'nearest', 'withinDistance'
};

var currentFilters = {...initialFilters};
    
var stationMarkers = [];
var marker;
var userSubmittedLocation = null;
var countryBoundaries;
var isFirstClick = true;

window.onload = hideSidebar; // Hide the sidebar initially

fetch('/static/PL-administrative-boundaries.json')
.then(response => response.json())
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
    var coord = e.latlng;
    var lat = coord.lat;
    var lng = coord.lng;
    
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
}
setupTouchInteraction(mymap);

var gpsButton = L.control({position: 'topleft'});
gpsButton.onAdd = function(map) {
    var div = L.DomUtil.create('div', 'gps-location-control');
    div.innerHTML = '<button id="useMyLocationBtn" title="Use My Location">📍</button>';
    L.DomEvent.on(div, 'click', function(e) {
        L.DomEvent.stop(e); // Prevent map click
        requestAndSendGPSLocation(); 
    });
    return div;
};
gpsButton.addTo(mymap);

var zoomButton = L.control({position: 'topleft'});
zoomButton.onAdd = function(map) {
    var div = L.DomUtil.create('div', 'zoom-control');
    div.innerHTML = '<button id="zoomOutInButton" title="Zoom out & in">🔍</button>';
    var button = div.querySelector('#zoomOutInButton');
    L.DomEvent.on(button, 'click', function(e) {
        L.DomEvent.stop(e);
        zoomOutAndIn(); 
    });
    return div;
};
zoomButton.addTo(mymap);

var btsCountControl = L.control({position: 'bottomleft'});
btsCountControl.onAdd = function(map) {
    var div = L.DomUtil.create('div', '');
    div.className = 'bg-white p-2 dark:mt-[-4rem] dark:md:mt-0 rounded shadow text-black dark:bg-gray-800 dark:hover:bg-gray-500 dark:text-white';
    div.innerHTML = 'BTS count: <span id="btsCounter">0</span>';
    return div;
}
btsCountControl.addTo(mymap);

var filterControl = L.control({position: 'topright'});
filterControl.onAdd = function(map) {
    var div = L.DomUtil.create('div', 'filter-control-container');
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
                        <label><input type="checkbox" name="service_provider" value="AERO 2 Sp. z o.o."> Aero 2</label>
                    </div>
                </div>

                <div class="my-2">
                    <p class="text-gray-700 font-bold dark:text-white">Frequency:</p>
                    <div class="grid grid-cols-2 md:grid-cols-3 gap-1">
                        <label><input type="checkbox" name="frequency_bands" value="5G3600"> 5G3600</label>
                        <label><input type="checkbox" name="frequency_bands" value="5G2100"> 5G2100</label>
                        <label><input type="checkbox" name="frequency_bands" value="5G1800"> 5G1800</label>
                        <label><input type="checkbox" name="frequency_bands" value="LTE2600"> LTE2600</label>
                        <label><input type="checkbox" name="frequency_bands" value="LTE2100"> LTE2100</label>
                        <label><input type="checkbox" name="frequency_bands" value="LTE1800"> LTE1800</label>
                        <label><input type="checkbox" name="frequency_bands" value="LTE900"> LTE900</label>
                        <label><input type="checkbox" name="frequency_bands" value="LTE800"> LTE800</label>
                        <label><input type="checkbox" name="frequency_bands" value="GSM900"> GSM900</label>
                    </div>
                </div>

                <button id="apply-filters" class="apply-filters-btn mt-2 w-full text-white bg-blue-300 dark:bg-gray-700 hover:bg-blue-500 dark:hover:bg-gray-500" font-bold py-1 px-4 rounded">
                    Apply Filters
                </button>

                <div class="slider-container my-4">
                    <div class="flex justify-between items-center">
                        <button id="showNearestBtn" class="mt-2 w-48 text-white bg-blue-300 dark:bg-gray-700 hover:bg-blue-500 dark:hover:bg-gray-500" font-bold py-1 px-4 rounded">Show Nearest BTS</button>
                    </div>
                    <input type="number" id="nearestBtsRange" min="1" max="10" placeholder="" class="w-[4.25rem] mt-1 bg-blue-100 hover:bg-blue-300 dark:bg-gray-700 dark:hover:bg-gray-500">
                </div>

                <div class="slider-container my-4">
                    <div class="flex justify-between items-center">
                        <button id="showWithinDistanceBtn" class="mt-2 w-48 text-white bg-blue-300 dark:bg-gray-700 hover:bg-blue-500 dark:hover:bg-gray-500" font-bold py-1 px-4 rounded">Show BTS Within Distance</button>
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
        var filterContainer = document.getElementById('filterContainer');
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
    fetchStations();
})

setTimeout(() => {

    document.getElementById('showNearestBtn').addEventListener('click', function() {
        currentFilters.mode = 'nearest';
        const center = mymap.getCenter();
        currentFilters.lat = center.lat;
        currentFilters.lng = center.lng;
        currentFilters.limit = nearestBtsRange.value;
        fetchStations();
    });

    document.getElementById('showWithinDistanceBtn').addEventListener('click', function() {
        currentFilters.mode = 'withinDistance';
        const center = mymap.getCenter();
        currentFilters.lat = center.lat;
        currentFilters.lng = center.lng;
        currentFilters.maxDistance = withinDistanceRange.value;
        fetchStations();
    });
}, 0);

function requestAndSendGPSLocation() {
    if ("geolocation" in navigator) {
        navigator.geolocation.getCurrentPosition(
            function(position) {
                var userLat = position.coords.latitude;
                var userLng = position.coords.longitude;
                mymap.setView([userLat, userLng], 7); 
                sendLocation(userLat, userLng); 
            },
            function(error) {
                showToast('Location error: ${error.message}. Please try again.', 'error');
            },
            { 
                enableHighAccuracy: true,
                timeout: 7000,
                maximumAge: 0
            }
        );
    } else {
        showToast('Geolocation is not supported by this browser.', 'error');
    }
}

function createZoomToggleFunction(map) {
    let shouldZoomOut = true;

    return function() {
        if (shouldZoomOut) {
            map.zoomOut(3);
        } else {
            map.zoomIn(3);
        }
        shouldZoomOut = !shouldZoomOut;
    };
}

var zoomOutAndIn = createZoomToggleFunction(mymap); // Initialize the toggle function and pass the map instance

function updateBTSCount(count) {
    var btsCounter = document.getElementById('btsCounter');
    if (btsCounter) {
        btsCounter.textContent = count;
    }
}

function clearBTSCount(count) {
    var btsCounter = document.getElementById('btsCounter')
    btsCounter.textContent = 0;
}

function sendLocation(lat, lng, limit = 9, max_distance = null) {
    currentFilters.lat = lat;
    currentFilters.lng = lng;
    currentFilters.limit = limit;
    currentFilters.maxDistance = max_distance;

    let url = `/submit_location`;
    const userSubmittedLocation = { lat: lat, lng: lng };
    const requestData = {
        lat: lat,
        lng: lng,
        limit: limit,
        max_distance: max_distance
    };

    const messageBox = document.getElementById('messageBox');

    fetch(url, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify(requestData)
    })
    .then(response => {
        if (!response.ok) {
            throw new Error('Network response was not ok');
        }
        return response.json(); // Ensure JSON parsing
    })
    .then(data => {
        if (!countryBoundaries.getBounds().contains(userSubmittedLocation)) {
            messageBox.classList.remove('hidden');
            setTimeout(() => {
                messageBox.classList.add('hidden')
                mymap.zoomOut(7);
            }, 7700);
        }  else {
            messageBox.classList.add('hidden');
        }
        if (data && Array.isArray(data.stations)) {
            updateBTSCount(data.count);
            showSidebar(); 
            displayStations(data.stations);
        }
    })
}

function showSidebar() {
    var sidebar = document.getElementById('sidebar');
    sidebar.classList.remove('hidden');
}

function hideSidebar() {
    var sidebar = document.getElementById('sidebar');
    sidebar.classList.add('hidden');
    
}

function clearStationMarkers() { // clearing markers when new location is submitted
    for (var i = 0; i < stationMarkers.length; i++) {
        mymap.removeLayer(stationMarkers[i]);
    }
    stationMarkers = []; // Reset the array
} 

function displayStations(data) {
    clearStationMarkers(); // Clear existing markers
    var sidebarContent = document.getElementById('sidebar');
    sidebarContent.innerHTML = ''; // Clear existing sidebar content
    let stations;
    
    var bounds = [];
    
    if (Array.isArray(data)) {
        // Data is just the list of stations
        stations = data;
    } else if (data && Array.isArray(data.stations)) {
        // Data is an object containing stations and possibly other information
        stations = data.stations;
    }

    stations.forEach((station, index) => {
        addStationMarker(station, index);
        addStationInfoToSidebar(station, index, sidebarContent);
        
    var latLng = L.latLng(station.latitude, station.longitude);
        bounds.push(latLng); 
    });

    if (bounds.length > 0) {
        mymap.fitBounds(bounds, { padding: [50, 50] }); 
        mymap.setZoom(mymap.getZoom() - 1); //
    }
}

function createCustomIcon(station, index, providerIconUrl) {
    var iconHtml = `<div style="background-image: url(${providerIconUrl}); width: 30px; height: 46px; background-size: cover; position: relative;">
                        <div style="position: absolute; bottom: 1px; width: 100%; text-align: center; color: white; font-weight: bold; font-size: 21px;">
                            ${index + 1}
                        </div>
                    </div>`;
    return L.divIcon({ 
        html: iconHtml, iconSize: [12, 41], iconAnchor: [12, 41], popupAnchor: [1, -34], className: '' 
    });
}

function addStationMarker(station, index) {
    var providerIconUrl = `static/css/images/marker-icon-${providerColors[station.service_provider]}.png` || 'grey'; // grey color if provider not found
    var customIcon = createCustomIcon(station, index, providerIconUrl);
    var stationMarker = L.marker([station.latitude, station.longitude], {icon: customIcon}).addTo(mymap);
    var popupContent = createPopupContent(station, index);
    stationMarker.bindPopup(popupContent);
    stationMarkers.push(stationMarker);

    var tooltipContent = `${index + 1}. ${station.basestation_id}`; // tooltip
    stationMarker.bindTooltip(tooltipContent);
}

function addStationInfoToSidebar(station, index, sidebarContent) {
    var stationInfo = createSidebarContent(station, index);
    var stationInfoDiv = document.createElement('div');
    stationInfoDiv.className = 'sidebar-item';
    stationInfoDiv.innerHTML = stationInfo;
    sidebarContent.appendChild(stationInfoDiv);
    
    var googleMapsLink = document.createElement('a');
    googleMapsLink.href = `https://www.google.com/maps/search/?api=1&query=${station.latitude},${station.longitude}`;
    googleMapsLink.target = '_blank';
    googleMapsLink.textContent = 'View on Google Maps';
    googleMapsLink.className = 'no-underline hover:underline text-blue-500 hover:text-blue-700 dark:text-blue-300 dark:hover:text-blue-400 font-semibold';
    stationInfoDiv.appendChild(googleMapsLink);
}

function createPopupContent(station, index) {
    var formattedLat = station.latitude.toFixed(5);
    var formattedLng = station.longitude.toFixed(5);
    var formattedDistance = station.distance.toFixed(2);
    var latHemisphere = station.latitude >= 0 ? 'N' : 'S';
    var lngHemisphere = station.longitude >= 0 ? 'E' : 'W';
    var googleMapsLink = `https://www.google.com/maps/search/?api=1&query=${station.latitude},${station.longitude}`;
    
    return `
        <b>${index + 1}. Service Provider:</b> ${station.service_provider}<br>
        <b>Distance:</b> ${formattedDistance}km<br>
        <b>Base Station ID:</b> ${station.basestation_id}<br>
        <b>Frequency Bands:</b> ${station.frequency_bands.join(", ")}<br>
        <b>City:</b> ${station.city}<br>
        <b>Location:</b> ${station.location}<br>
        <b>Coordinates:</b> ${formattedLat}°${latHemisphere}, ${formattedLng}°${lngHemisphere}<br>
        <a href="${googleMapsLink}" target="_blank" class="no-underline hover:underline text-blue-500 hover:text-blue-700 dark:text-blue-300 dark:hover:text-blue-400 font-semibold">View on Google Maps</a>`;
}

function createSidebarContent(station, index) {
    var formattedLat = station.latitude.toFixed(5);
    var formattedLng = station.longitude.toFixed(5);
    var formattedDistance = station.distance.toFixed(2);
    var latHemisphere = station.latitude >= 0 ? 'N' : 'S';
    var lngHemisphere = station.longitude >= 0 ? 'E' : 'W';
    return `
        <div class="sidebar-item dark:text-white">
            <h4>${index + 1}. ${station.basestation_id}</h4>
            <p><b>Service Provider:</b> ${station.service_provider}</p>
            <p><b>Distance:</b> ${formattedDistance}km</p>
            <p><b>Frequency Bands:</b> ${station.frequency_bands.join(", ")}</p>
            <p><b>City:</b> ${station.city}</p>
            <p><b>Location:</b> ${station.location}</p>
            <p><b>Coordinates:</b> ${formattedLat}°${latHemisphere}, ${formattedLng}°${lngHemisphere}</p>
        </div>`;
}

function constructFilterURL() {
    let params = new URLSearchParams();

    const lat = currentFilters.lat !== undefined ? currentFilters.lat : mymap.getCenter().lat;
    const lng = currentFilters.lng !== undefined ? currentFilters.lng : mymap.getCenter().lng;
    
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
    let filterURL = constructFilterURL();
    fetch(filterURL)
    .then(response => response.json())
    .then(data => {
        updateBTSCount(data.count);
        showSidebar();
        displayStations(data.stations);
    })
}

function resetFiltersUI() {
    document.querySelectorAll('input[type="range"]').forEach(slider => {
        document.getElementById('nearestBtsRange').value = 6;
        document.getElementById('withinDistanceRange').value = 3;
        document.getElementById('nearestBtsValue').textContent = 6;
        document.getElementById('withinDistanceValue').textContent = 3;
    });

    document.querySelectorAll('input[type="checkbox"]').forEach(checkbox => {
        checkbox.checked = false;
    });
    clearBTSCount()
    clearStationMarkers()
    hideSidebar()
    currentFilters = {...initialFilters}; // spread
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
    fetch('/session_check')
    .then(response => response.json())
    .then(data => {
        const dynamicContent = document.getElementById('dynamicContent');
        const isLoggedIn = data.logged_in;
        if (isLoggedIn) {
            dynamicContent.innerHTML = `
                <div id="latLngContainer" class="flex flex-col space-y-0.5">
                <button id="submitCoords" class="w-48 bg-blue-300 dark:bg-gray-700 hover:bg-blue-500 dark:hover:bg-gray-500 text-white rounded">Search</button>
                    <div class="flex space-x-2">
                    <input type="number" id="latitudeInput" placeholder="52.230 (°N)" class="w-[5.5rem] mt-0.5 bg-blue-100 hover:bg-blue-300 dark:bg-gray-700 dark:hover:bg-gray-500" min="48" max="58" step="0.1">
                    <input type="number" id="longitudeInput" placeholder="21.003 (°E)" class="w-[5.5rem] mt-0.5 bg-blue-100 hover:bg-blue-300 dark:bg-gray-700 dark:hover:bg-gray-500" min="13.5" max="24.5" step="0.1">
                    </div>
                </div>
                <div id="searchByBtsContainer" class="my-4 flex flex-col space-y-0.5">    
                    <button id="submitfilteredstation" class="w-48 bg-blue-300 dark:bg-gray-700 hover:bg-blue-500 dark:hover:bg-gray-500 text-white rounded">Search</button>
                    <div class="flex space-x-2">
                        <input type="text" id="baseStationIdInput" placeholder="Enter Base Station ID" class="w-[8rem] mt-0.5 bg-blue-100 hover:bg-blue-300 dark:bg-gray-700 dark:hover:bg-gray-500">
                    </div>
                </div>`;
        } else {
            dynamicContent.innerHTML = `
                <div id="latLngContainer" class="opacity-50 cursor-not-allowed flex flex-col space-y-0.5 title="Register or log in to use this feature.">
                    <button id="submitCoords" class="w-48 bg-blue-300 dark:bg-gray-700 hover:bg-blue-500 dark:hover:bg-gray-500 text-white rounded cursor-not-allowed" disabled title="Register or log in to use this feature.">Search</button>
                    <div class="flex space-x-2">
                        <input type="number" id="latitudeInput" placeholder="52.230 (°N)" class="w-[5.5rem] mt-0.5 bg-blue-100 hover:bg-blue-300 dark:bg-gray-700 dark:hover:bg-gray-500 cursor-not-allowed" min="48" max="58" step="0.1" disabled title="Register or log in to use this feature.">
                        <input type="number" id="longitudeInput" placeholder="21.003 (°E)" class="w-[5.5rem] mt-0.5 bg-blue-100 hover:bg-blue-300 dark:bg-gray-700 dark:hover:bg-gray-500 cursor-not-allowed" min="13.5" max="24.5" step="0.1" disabled title="Register or log in to use this feature.">
                    </div>
                </div>
                <div id="searchByBtsContainer" class="my-4 opacity-50 cursor-not-allowed flex flex-col space-y-0.5 title="Register or log in to use this feature.">
                    <button id="submitfilteredstation" class="w-48 bg-blue-300 dark:bg-gray-700 hover:bg-blue-500 dark:hover:bg-gray-500 text-white rounded cursor-not-allowed" disabled title="Register or log in to use this feature.">Search</button>
                    <div class="flex space-x-2">
                        <input type="text" id="baseStationIdInput" placeholder="Enter Base Station ID" class="w-[8rem] mt-0.5 bg-blue-100 hover:bg-blue-300 dark:bg-gray-700 dark:hover:bg-gray-500 cursor-not-allowed" disabled title="Register or log in to use this feature.">
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

    fetch(`/find_station?basestation_id=${basestation_id}`)
        .then(response => {
            if (!response.ok) {
                showToast('Base Station ID not found', 'error');
                throw new Error('Base Station ID not found');
            }
            return response.json();
        })
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
