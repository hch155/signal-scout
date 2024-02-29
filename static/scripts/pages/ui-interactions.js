// base.html

function adjustFooterPosition() {
    const footer = document.querySelector('footer'); 
    const bodyHeight = document.body.offsetHeight;
    const viewportHeight = window.innerHeight;

   if (bodyHeight <= viewportHeight) {
       footer.classList.add('mt-auto');
   } else {
       footer.classList.remove('mt-auto');
   }
}

// map.html

function requestAndSendGPSLocation() {
    // Stop event propagation if called from an event listener
    if (event) event.stopPropagation();

    if ("geolocation" in navigator) {
        navigator.geolocation.getCurrentPosition(function(position) {
            var userLat = position.coords.latitude;
            var userLng = position.coords.longitude;
            mymap.setView([userLat, userLng], 7); 
            sendLocation(userLat, userLng);
        }, function(error) {
            console.error('Geolocation error:', error);
            alert('Error getting location. Please try again.');
        }, {
            enableHighAccuracy: true,
            timeout: 5000,
            maximumAge: 0
        });
    } else {
        console.log("Geolocation is not supported by this browser.");
    }
}

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
        console.log('Parsed data:', data);    // verification of the parsed data  
        if (!countryBoundaries.getBounds().contains(userSubmittedLocation)) {
            const viewportHeight = window.innerHeight;
            const bodyHeight = document.body.offsetHeight;
            messageBox.classList.remove('hidden');
            setTimeout(() => {
                messageBox.classList.add('hidden');
            }, 7700);
        }  else {
            messageBox.classList.add('hidden');
        }
        if (data && Array.isArray(data.stations)) {
            updateBTSCount(data.count);
            showSidebar(); 
            displayStations(data.stations);
        } else {
            console.error('Unexpected data structure:', data);
        }
})
    .catch((error) => {
        console.error('Error:', error);
    });
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
    } else {
        console.error('Invalid data format for displayStations', data);
        return; // Exit the function if the data format is not recognized
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
    googleMapsLink.className = 'google-maps-link dark:text-white';
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
        <a href="${googleMapsLink}" target="_blank">View on Google Maps</a>`;
}

function createSidebarContent(station, index) {
    var formattedLat = station.latitude.toFixed(5);
    var formattedLng = station.longitude.toFixed(5);
    var formattedDistance = station.distance.toFixed(2);
    var latHemisphere = station.latitude >= 0 ? 'N' : 'S';
    var lngHemisphere = station.longitude >= 0 ? 'E' : 'W';
    var googleMapsLink = `https://www.google.com/maps/search/?api=1&query=${station.latitude},${station.longitude}`;
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

    params.append('lat', lat);
    params.append('lng', lng);
   
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
    console.log(`Fetching stations with URL: ${filterURL}`);
    fetch(filterURL)
    .then(response => response.json())
    .then(data => {
        updateBTSCount(data.count);
        showSidebar();
        displayStations(data.stations);
    })
    .catch(error => console.error('Error fetching stations:', error));
}

function resetFiltersUI() {
    document.querySelectorAll('input[type="range"]').forEach(slider => {
        document.getElementById('nearestBtsRange').value = 6; // sliders
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