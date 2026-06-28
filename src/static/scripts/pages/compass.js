// Compass/Azimuth module for pointing toward base stations
// Requires HTTPS for DeviceOrientationEvent on mobile

let compassState = {
    userLat: null,
    userLng: null,
    targetLat: null,
    targetLng: null,
    targetName: null,
    deviceHeading: null,
    bearingToTarget: null,
    isActive: false,
    hasPermission: false,
    watchId: null,
    isMobileDevice: false,
    hasOrientationData: false,
    orientationCheckTimeout: null,
    usingAbsoluteEvent: false,
    wakeLock: null,
    isArrived: false
};

const PL_MAGNETIC_DECLINATION = 6.5;

// Detect if device is mobile/tablet
function detectMobileDevice() {
    return /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent)
        || (navigator.maxTouchPoints && navigator.maxTouchPoints > 2);
}

// Calculate bearing from point A to point B (in degrees, 0 = North, clockwise)
function calculateBearing(lat1, lng1, lat2, lng2) {
    const toRad = deg => deg * Math.PI / 180;
    const toDeg = rad => rad * 180 / Math.PI;

    const dLng = toRad(lng2 - lng1);
    const lat1Rad = toRad(lat1);
    const lat2Rad = toRad(lat2);

    const x = Math.sin(dLng) * Math.cos(lat2Rad);
    const y = Math.cos(lat1Rad) * Math.sin(lat2Rad) -
              Math.sin(lat1Rad) * Math.cos(lat2Rad) * Math.cos(dLng);

    let bearing = toDeg(Math.atan2(x, y));
    return (bearing + 360) % 360; // Normalize to 0-360
}

// Calculate distance between two points (haversine formula)
function calculateDistance(lat1, lng1, lat2, lng2) {
    const R = 6371; // Earth's radius in km
    const toRad = deg => deg * Math.PI / 180;

    const dLat = toRad(lat2 - lat1);
    const dLng = toRad(lng2 - lng1);

    const a = Math.sin(dLat/2) * Math.sin(dLat/2) +
              Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) *
              Math.sin(dLng/2) * Math.sin(dLng/2);

    const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
    return R * c;
}

// Sun & moon position (condensed SunCalc). Returns azimuth in degrees from
// North clockwise (0=N, 90=E) and altitude in degrees (>0 = above horizon).
const CEL_RAD = Math.PI / 180;
const CEL_OBLIQUITY = CEL_RAD * 23.4397;

function celToDays(date) {
    return date.valueOf() / 86400000 - 0.5 + 2440588 - 2451545;
}
function celRightAscension(l, b) {
    return Math.atan2(Math.sin(l) * Math.cos(CEL_OBLIQUITY) - Math.tan(b) * Math.sin(CEL_OBLIQUITY), Math.cos(l));
}
function celDeclination(l, b) {
    return Math.asin(Math.sin(b) * Math.cos(CEL_OBLIQUITY) + Math.cos(b) * Math.sin(CEL_OBLIQUITY) * Math.sin(l));
}
function celSiderealTime(d, lw) {
    return CEL_RAD * (280.16 + 360.9856235 * d) - lw;
}
function celHorizontal(H, phi, dec) {
    const az = Math.atan2(Math.sin(H), Math.cos(H) * Math.sin(phi) - Math.tan(dec) * Math.cos(phi));
    const alt = Math.asin(Math.sin(phi) * Math.sin(dec) + Math.cos(phi) * Math.cos(dec) * Math.cos(H));
    return {
        azimuth: ((az / CEL_RAD + 180) % 360 + 360) % 360,
        altitude: alt / CEL_RAD
    };
}
function sunPosition(date, lat, lng) {
    const lw = CEL_RAD * -lng, phi = CEL_RAD * lat, d = celToDays(date);
    const M = CEL_RAD * (357.5291 + 0.98560028 * d);
    const C = CEL_RAD * (1.9148 * Math.sin(M) + 0.02 * Math.sin(2 * M) + 0.0003 * Math.sin(3 * M));
    const L = M + C + CEL_RAD * 102.9372 + Math.PI;
    return celHorizontal(celSiderealTime(d, lw) - celRightAscension(L, 0), phi, celDeclination(L, 0));
}
function moonPosition(date, lat, lng) {
    const lw = CEL_RAD * -lng, phi = CEL_RAD * lat, d = celToDays(date);
    const L = CEL_RAD * (218.316 + 13.176396 * d);
    const M = CEL_RAD * (134.963 + 13.064993 * d);
    const F = CEL_RAD * (93.272 + 13.229350 * d);
    const l = L + CEL_RAD * 6.289 * Math.sin(M);
    const b = CEL_RAD * 5.128 * Math.sin(F);
    return celHorizontal(celSiderealTime(d, lw) - celRightAscension(l, b), phi, celDeclination(l, b));
}

const COMPASS_ACCURACY_POOR_DEG = 25;

// Update the calibration hint
function updateCalibrationHint(accuracy) {
    const hint = document.getElementById('compass-calibration');
    if (!hint) return;
    const poor = accuracy < 0 || accuracy > COMPASS_ACCURACY_POOR_DEG;
    hint.classList.toggle('hidden', !poor);
}

// Handle device orientation event
function handleOrientation(event) {
    let heading = null;

    // iOS provides webkitCompassHeading (degrees from magnetic north, 0-360)
    if (event.webkitCompassHeading !== undefined && event.webkitCompassHeading !== null) {
        heading = event.webkitCompassHeading;
        if (typeof event.webkitCompassAccuracy === 'number') {
            updateCalibrationHint(event.webkitCompassAccuracy);
        }
    }
    // Android/others: use absolute orientation if available
    else if ((event.absolute === true || event.type === 'deviceorientationabsolute') && event.alpha !== null) {
        // When absolute is true, alpha is relative to north
        // alpha = 0 means device top points north, increases counter-clockwise
        // We need clockwise heading, so: heading = (360 - alpha) % 360
        heading = (360 - event.alpha) % 360;
    }
    // Fallback for non-absolute orientation (less accurate)
    else if (event.alpha !== null && !compassState.usingAbsoluteEvent) {
        heading = (360 - event.alpha) % 360;
    }

    if (heading !== null) {
        // Mark that we're receiving real orientation data
        if (!compassState.hasOrientationData) {
            compassState.hasOrientationData = true;
            updateCompassMode();
        }

        // Smooth the heading to reduce jitter
        if (compassState.deviceHeading !== null) {
            // Simple low-pass filter
            const diff = heading - compassState.deviceHeading;
            // Handle wrap-around at 0/360
            let adjustedDiff = diff;
            if (diff > 180) adjustedDiff = diff - 360;
            if (diff < -180) adjustedDiff = diff + 360;
            heading = (compassState.deviceHeading + adjustedDiff * 0.3 + 360) % 360;
        }
        compassState.deviceHeading = heading;
        updateCompassDisplay();
    }
}

// Update compass mode (mobile vs desktop)
function updateCompassMode() {
    const mobileElements = document.querySelectorAll('.compass-mobile-only');
    const desktopNotice = document.getElementById('compass-desktop-notice');
    const compassRing = document.getElementById('compass-ring');

    if (compassState.hasOrientationData) {
        // Mobile mode - show full compass
        mobileElements.forEach(el => el.classList.remove('hidden'));
        if (desktopNotice) desktopNotice.classList.add('hidden');
    } else {
        // Desktop mode - show static view
        mobileElements.forEach(el => el.classList.add('hidden'));
        if (desktopNotice) desktopNotice.classList.remove('hidden');
        // Point compass to show bearing statically
        if (compassRing && compassState.bearingToTarget !== null) {
            compassRing.style.transform = 'rotate(0deg)';
        }
    }
}

// Update the compass display
function updateCompassDisplay() {
    const compassRing = document.getElementById('compass-ring');
    const compassContainer = document.getElementById('compass-container');
    const headingText = document.getElementById('compass-heading');
    const bearingText = document.getElementById('compass-bearing');
    const distanceText = document.getElementById('compass-distance');
    const directionText = document.getElementById('compass-direction');
    const arrow = document.getElementById('compass-arrow');
    const arrowPolygon = document.getElementById('compass-arrow-head');
    const arrowCenter = document.getElementById('compass-arrow-center');
    const alignmentIndicator = document.getElementById('alignment-indicator');

    if (!compassRing) return;

    if (compassState.userLat && compassState.targetLat) {
        const dist = calculateDistance(
            compassState.userLat, compassState.userLng,
            compassState.targetLat, compassState.targetLng
        );
        if (distanceText) {
            distanceText.textContent = `${dist.toFixed(2)} km`;
        }
        if (!compassState.isArrived && dist < ARRIVAL_THRESHOLD_KM) {
            compassState.isArrived = true;
        } else if (compassState.isArrived && dist > ARRIVAL_EXIT_KM) {
            compassState.isArrived = false;
        }
    }

    if (compassState.deviceHeading !== null) {
        // Rotate the entire compass (including the station arrow) so N always points to actual north
        compassRing.style.transform = `rotate(${-compassState.deviceHeading}deg)`;

        if (headingText) {
            headingText.textContent = `${t('You face:')} ${Math.round(compassState.deviceHeading)}° ${getBearingDirection(compassState.deviceHeading)}`;
        }
    }

    if (compassState.bearingToTarget !== null) {
        const bearingMagnetic = (compassState.bearingToTarget - PL_MAGNETIC_DECLINATION + 360) % 360;

        // Update the arrow rotation within the compass ring
        if (arrow && !compassState.isArrived) {
            arrow.style.transform = `rotate(${bearingMagnetic}deg)`;
        }

        if (bearingText) {
            bearingText.textContent = `${t('Station:')} ${Math.round(bearingMagnetic)}° ${getBearingDirection(bearingMagnetic)}`;
        }

        if (compassState.isArrived) {
            if (directionText) {
                directionText.textContent = t('Arrived — you\'re at the station');
                directionText.className = 'mt-3 text-lg font-bold text-green-500';
            }
            if (arrowPolygon && arrowCenter) {
                arrowPolygon.setAttribute('fill', '#22c55e');
                arrowPolygon.setAttribute('stroke', '#16a34a');
                arrowCenter.setAttribute('fill', '#16a34a');
            }
            if (alignmentIndicator) {
                alignmentIndicator.classList.add('hidden');
                alignmentIndicator.classList.remove('animate-pulse');
            }
            if (compassContainer) {
                compassContainer.classList.remove('ring-4', 'ring-green-400', 'ring-opacity-75');
            }
            lastAlignedState = false;
        }
        // Check alignment and update visuals
        else if (compassState.deviceHeading !== null) {
            const aligned = isAligned(bearingMagnetic, compassState.deviceHeading);

            // Update direction text
            if (directionText) {
                const relative = getRelativeDirection(bearingMagnetic, compassState.deviceHeading);
                directionText.textContent = relative;

                if (aligned) {
                    directionText.className = 'mt-3 text-lg font-bold text-green-500 animate-pulse';
                } else {
                    directionText.className = 'mt-3 text-base font-semibold text-blue-600 dark:text-blue-400';
                }
            }

            // Update arrow colors based on alignment
            if (arrowPolygon && arrowCenter) {
                if (aligned) {
                    arrowPolygon.setAttribute('fill', '#22c55e'); // green-500
                    arrowPolygon.setAttribute('stroke', '#16a34a'); // green-600
                    arrowCenter.setAttribute('fill', '#16a34a');
                } else {
                    arrowPolygon.setAttribute('fill', '#3b82f6'); // blue-500
                    arrowPolygon.setAttribute('stroke', '#1d4ed8'); // blue-700
                    arrowCenter.setAttribute('fill', '#1d4ed8');
                }
            }

            // Update alignment indicator
            if (alignmentIndicator) {
                if (aligned) {
                    alignmentIndicator.classList.remove('hidden');
                    alignmentIndicator.classList.add('animate-pulse');
                } else {
                    alignmentIndicator.classList.add('hidden');
                    alignmentIndicator.classList.remove('animate-pulse');
                }
            }

            // Compass container glow effect
            if (compassContainer) {
                if (aligned) {
                    compassContainer.classList.add('ring-4', 'ring-green-400', 'ring-opacity-75');
                } else {
                    compassContainer.classList.remove('ring-4', 'ring-green-400', 'ring-opacity-75');
                }
            }

            // Haptic feedback when alignment state changes to true
            if (aligned && !lastAlignedState) {
                triggerHaptic();
            }
            lastAlignedState = aligned;
        }
    }
}

// Get cardinal direction from bearing
function getBearingDirection(bearing) {
    const directions = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'];
    const index = Math.round(bearing / 45) % 8;
    return directions[index];
}

// Alignment state tracking
let lastAlignedState = false;
const ALIGNMENT_THRESHOLD = 10; // degrees
const ARRIVAL_THRESHOLD_KM = 0.03;
const ARRIVAL_EXIT_KM = 0.04;

// Check if device is aligned with station
function isAligned(bearing, heading) {
    let diff = bearing - heading;
    while (diff > 180) diff -= 360;
    while (diff < -180) diff += 360;
    return Math.abs(diff) <= ALIGNMENT_THRESHOLD;
}

// Trigger haptic feedback
function triggerHaptic() {
    // Navigator.vibrate() - works on Android Chrome, not on iOS Safari
    if ('vibrate' in navigator) {
        try {
            navigator.vibrate([50, 30, 50]); // Short double pulse
        } catch (e) {
            // Vibration not available
        }
    }

    // iOS fallback: use AudioContext for a subtle "click" sound
    // This requires user interaction to have happened first
    try {
        if (window.AudioContext || window.webkitAudioContext) {
            const AudioCtx = window.AudioContext || window.webkitAudioContext;
            const audioCtx = new AudioCtx();
            const oscillator = audioCtx.createOscillator();
            const gainNode = audioCtx.createGain();

            oscillator.connect(gainNode);
            gainNode.connect(audioCtx.destination);

            oscillator.frequency.value = 200;
            oscillator.type = 'sine';
            gainNode.gain.value = 0.1;

            oscillator.start();
            oscillator.stop(audioCtx.currentTime + 0.05);
        }
    } catch (e) {
        // Audio feedback not available
    }
}

// Get relative direction instruction for equipment alignment
function getRelativeDirection(bearing, heading) {
    let diff = bearing - heading;
    // Normalize to -180 to 180
    while (diff > 180) diff -= 360;
    while (diff < -180) diff += 360;

    if (Math.abs(diff) <= ALIGNMENT_THRESHOLD) return t('ALIGNED');
    if (Math.abs(diff) < 30) return t('Almost there...');
    if (diff > 0 && diff < 60) return t('Station is to your right');
    if (diff >= 60 && diff < 120) return t('Station is on your right');
    if (diff >= 120) return t('Station is behind you');
    if (diff < 0 && diff > -60) return t('Station is to your left');
    if (diff <= -60 && diff > -120) return t('Station is on your left');
    return t('Station is behind you');
}

// Request permission for device orientation (required on iOS 13+)
async function requestOrientationPermission() {
    // Check if DeviceOrientationEvent is available
    if (typeof DeviceOrientationEvent === 'undefined') {
        showToast(t('Device orientation not supported on this device'), 'error');
        return false;
    }

    // iOS 13+ requires permission request
    if (typeof DeviceOrientationEvent.requestPermission === 'function') {
        try {
            const permission = await DeviceOrientationEvent.requestPermission();
            if (permission === 'granted') {
                compassState.hasPermission = true;
                return true;
            } else {
                showToast(t('Compass permission denied'), 'error');
                return false;
            }
        } catch (err) {
            showToast(t('Error requesting compass permission: ') + err.message, 'error');
            return false;
        }
    }

    // Non-iOS devices don't need permission
    compassState.hasPermission = true;
    return true;
}

async function acquireWakeLock() {
    if (!('wakeLock' in navigator)) return;
    try {
        compassState.wakeLock = await navigator.wakeLock.request('screen');
    } catch (err) {
        compassState.wakeLock = null;
    }
}

function releaseWakeLock() {
    if (!compassState.wakeLock) return;
    try {
        compassState.wakeLock.release();
    } catch (err) {
        // ignore
    }
    compassState.wakeLock = null;
}

function handleVisibilityChange() {
    if (document.visibilityState === 'visible' && compassState.isActive) {
        acquireWakeLock();
    }
}

// Start compass tracking for a target station
// Place sun & moon markers at their real azimuths + update the readout
function updateCelestial() {
    const sunEl = document.getElementById('compass-sun');
    const moonEl = document.getElementById('compass-moon');
    const readout = document.getElementById('compass-celestial');
    if (!sunEl || !moonEl) return;
    if (compassState.userLat == null || compassState.userLng == null) return;

    const now = new Date();
    const sun = sunPosition(now, compassState.userLat, compassState.userLng);
    const moon = moonPosition(now, compassState.userLat, compassState.userLng);

    sunEl.style.transform = `rotate(${sun.azimuth}deg)`;
    moonEl.style.transform = `rotate(${moon.azimuth}deg)`;
    sunEl.style.opacity = sun.altitude > 0 ? '1' : '0.3';
    moonEl.style.opacity = moon.altitude > 0 ? '1' : '0.35';
    sunEl.classList.remove('hidden');
    moonEl.classList.remove('hidden');

    if (readout) {
        readout.innerHTML = `☀️ ${getBearingDirection(sun.azimuth)} · 🌙 ${getBearingDirection(moon.azimuth)}`;
    }
}

async function startCompass(stationLat, stationLng, stationName, userLat, userLng) {
    // Update state
    compassState.targetLat = stationLat;
    compassState.targetLng = stationLng;
    compassState.targetName = stationName;
    compassState.userLat = userLat;
    compassState.userLng = userLng;
    compassState.isMobileDevice = detectMobileDevice();
    compassState.hasOrientationData = false;
    compassState.isArrived = false;

    // Calculate bearing to target
    compassState.bearingToTarget = calculateBearing(userLat, userLng, stationLat, stationLng);

    // Request permission if needed (mobile only)
    if (compassState.isMobileDevice && !compassState.hasPermission) {
        const granted = await requestOrientationPermission();
        if (!granted && compassState.isMobileDevice) {
            // On mobile, permission denied - still show static compass
        }
    }

    // Show compass UI
    showCompassUI();

    updateCelestial();
    compassState.celestialInterval = setInterval(updateCelestial, 60000);

    // Start listening to orientation events
    window.addEventListener('deviceorientation', handleOrientation, true);
    compassState.usingAbsoluteEvent = false;
    if ('ondeviceorientationabsolute' in window) {
        window.addEventListener('deviceorientationabsolute', handleOrientation, true);
        compassState.usingAbsoluteEvent = true;
    }
    compassState.isActive = true;

    acquireWakeLock();
    document.addEventListener('visibilitychange', handleVisibilityChange);

    // Set timeout to check if we receive orientation data
    // If not after 1.5 seconds, switch to desktop/static mode
    compassState.orientationCheckTimeout = setTimeout(() => {
        if (!compassState.hasOrientationData) {
            updateCompassMode();
        }
    }, 1500);

    // Also track user's GPS location for live updates (mobile)
    if ('geolocation' in navigator && compassState.isMobileDevice) {
        compassState.watchId = navigator.geolocation.watchPosition(
            (position) => {
                compassState.userLat = position.coords.latitude;
                compassState.userLng = position.coords.longitude;
                compassState.bearingToTarget = calculateBearing(
                    compassState.userLat, compassState.userLng,
                    compassState.targetLat, compassState.targetLng
                );
                updateCompassDisplay();
            },
            (error) => console.log('GPS watch error:', error.message),
            { enableHighAccuracy: true, maximumAge: 1000 }
        );
    }

    return true;
}

// Stop compass tracking
function stopCompass() {
    window.removeEventListener('deviceorientation', handleOrientation, true);
    if (compassState.usingAbsoluteEvent) {
        window.removeEventListener('deviceorientationabsolute', handleOrientation, true);
        compassState.usingAbsoluteEvent = false;
    }

    document.removeEventListener('visibilitychange', handleVisibilityChange);
    releaseWakeLock();

    if (compassState.watchId !== null) {
        navigator.geolocation.clearWatch(compassState.watchId);
        compassState.watchId = null;
    }

    if (compassState.orientationCheckTimeout) {
        clearTimeout(compassState.orientationCheckTimeout);
        compassState.orientationCheckTimeout = null;
    }

    if (compassState.celestialInterval) {
        clearInterval(compassState.celestialInterval);
        compassState.celestialInterval = null;
    }

    compassState.isActive = false;
    compassState.hasOrientationData = false;
    compassState.isArrived = false;
    lastAlignedState = false;
    hideCompassUI();
}

// Create and show compass UI
function showCompassUI() {
    let compassContainer = document.getElementById('compass-container');

    if (!compassContainer) {
        compassContainer = document.createElement('div');
        compassContainer.id = 'compass-container';
        compassContainer.className = 'fixed bottom-4 right-4 z-[1000] bg-white dark:bg-gray-800 rounded-2xl shadow-2xl p-4 flex flex-col items-center border border-gray-200 dark:border-gray-700';
        compassContainer.innerHTML = `
            <button id="compass-close" aria-label="${t('Close')}" class="absolute top-2 right-3 text-gray-400 hover:text-gray-600 dark:text-gray-500 dark:hover:text-gray-300 text-2xl font-light">&times;</button>
            <div class="text-sm font-semibold text-gray-700 dark:text-white mb-3 text-center max-w-[160px] truncate" id="compass-target-name"></div>

            <!-- Compass container -->
            <div class="relative w-44 h-44">
                <!-- Outer bezel (static) -->
                <div class="absolute inset-0 rounded-full border-4 border-gray-300 dark:border-gray-600 bg-gray-50 dark:bg-gray-900"></div>

                <!-- Phone direction indicator at top (static - shows where phone points) -->
                <div class="absolute top-0 left-1/2 -translate-x-1/2 z-10">
                    <div class="w-0 h-0 border-l-[10px] border-l-transparent border-r-[10px] border-r-transparent border-b-[14px] border-b-orange-500 drop-shadow-md"></div>
                </div>

                <!-- Rotating compass ring - contains BOTH cardinal directions AND station arrow -->
                <div id="compass-ring" class="absolute inset-2 rounded-full">
                    <!-- Compass rose SVG with cardinal directions and station arrow -->
                    <svg class="w-full h-full" viewBox="0 0 100 100" aria-hidden="true">
                        <!-- Compass circle -->
                        <circle cx="50" cy="50" r="48" fill="none" stroke="currentColor" stroke-width="1" class="text-gray-300 dark:text-gray-600"/>

                        <!-- Cardinal direction ticks and labels -->
                        <!-- North (red) -->
                        <line x1="50" y1="4" x2="50" y2="14" stroke="#ef4444" stroke-width="3"/>
                        <text x="50" y="24" text-anchor="middle" font-size="10" font-weight="bold" fill="#ef4444">N</text>

                        <!-- South -->
                        <line x1="50" y1="86" x2="50" y2="96" stroke="currentColor" stroke-width="2" class="text-gray-400"/>
                        <text x="50" y="84" text-anchor="middle" font-size="9" font-weight="bold" fill="currentColor" class="text-gray-400">S</text>

                        <!-- East -->
                        <line x1="86" y1="50" x2="96" y2="50" stroke="currentColor" stroke-width="2" class="text-gray-400"/>
                        <text x="82" y="53" text-anchor="middle" font-size="9" font-weight="bold" fill="currentColor" class="text-gray-400">E</text>

                        <!-- West -->
                        <line x1="4" y1="50" x2="14" y2="50" stroke="currentColor" stroke-width="2" class="text-gray-400"/>
                        <text x="18" y="53" text-anchor="middle" font-size="9" font-weight="bold" fill="currentColor" class="text-gray-400">W</text>

                        <!-- Minor ticks (every 30 degrees) -->
                        <g class="text-gray-300 dark:text-gray-600">
                            <!-- 30° / NE area -->
                            <line x1="75" y1="6.7" x2="71.7" y2="13.4" stroke="currentColor" stroke-width="1"/>
                            <!-- 60° -->
                            <line x1="93.3" y1="25" x2="86.6" y2="28.3" stroke="currentColor" stroke-width="1"/>
                            <!-- 120° -->
                            <line x1="93.3" y1="75" x2="86.6" y2="71.7" stroke="currentColor" stroke-width="1"/>
                            <!-- 150° -->
                            <line x1="75" y1="93.3" x2="71.7" y2="86.6" stroke="currentColor" stroke-width="1"/>
                            <!-- 210° -->
                            <line x1="25" y1="93.3" x2="28.3" y2="86.6" stroke="currentColor" stroke-width="1"/>
                            <!-- 240° -->
                            <line x1="6.7" y1="75" x2="13.4" y2="71.7" stroke="currentColor" stroke-width="1"/>
                            <!-- 300° -->
                            <line x1="6.7" y1="25" x2="13.4" y2="28.3" stroke="currentColor" stroke-width="1"/>
                            <!-- 330° -->
                            <line x1="25" y1="6.7" x2="28.3" y2="13.4" stroke="currentColor" stroke-width="1"/>
                        </g>

                        <!-- Center point -->
                        <circle cx="50" cy="50" r="3" fill="#6b7280"/>
                    </svg>

                    <!-- Station direction arrow (INSIDE the rotating ring) -->
                    <div id="compass-arrow" class="absolute inset-0 flex items-center justify-center transition-all duration-200">
                        <svg width="100%" height="100%" viewBox="0 0 100 100" class="drop-shadow-lg" aria-hidden="true">
                            <!-- Arrow pointing to station (color changes on alignment) -->
                            <polygon id="compass-arrow-head" points="50,8 56,42 50,38 44,42" fill="#3b82f6" stroke="#1d4ed8" stroke-width="1"/>
                            <!-- Arrow tail (opposite direction, subtle) -->
                            <polygon points="50,92 53,58 50,62 47,58" fill="#cbd5e1" stroke="#94a3b8" stroke-width="0.5"/>
                            <!-- Center circle (color changes on alignment) -->
                            <circle id="compass-arrow-center" cx="50" cy="50" r="6" fill="#1d4ed8" stroke="white" stroke-width="2"/>
                        </svg>
                    </div>

                    <!-- Celestial markers (sun & moon) at their real azimuths -->
                    <div id="compass-sun" aria-hidden="true" class="hidden absolute inset-0 flex items-start justify-center transition-opacity duration-500 pointer-events-none">
                        <span class="text-sm leading-none mt-0.5" style="filter: drop-shadow(0 0 1.5px rgba(0,0,0,.5))">☀️</span>
                    </div>
                    <div id="compass-moon" aria-hidden="true" class="hidden absolute inset-0 flex items-start justify-center transition-opacity duration-500 pointer-events-none">
                        <span class="text-sm leading-none mt-0.5" style="filter: drop-shadow(0 0 1.5px rgba(0,0,0,.5))">🌙</span>
                    </div>
                </div>

                <!-- Alignment success indicator (hidden by default) -->
                <div id="alignment-indicator" class="hidden absolute inset-0 flex items-center justify-center pointer-events-none">
                    <div class="w-32 h-32 rounded-full border-4 border-green-400 opacity-50"></div>
                </div>
            </div>

            <!-- Direction instruction (mobile only) -->
            <div id="compass-direction" role="status" aria-live="polite" class="compass-mobile-only mt-3 text-base font-semibold text-blue-600 dark:text-blue-400">${t('Rotate until arrow points up')}</div>

            <!-- Calibration hint (mobile only) -->
            <div id="compass-calibration" role="status" aria-live="polite" class="hidden compass-mobile-only mt-2 px-2 py-1 rounded-md bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-300 text-xs text-center max-w-[170px]">${t('Wave your phone in a figure-8 to calibrate the compass')}</div>

            <!-- Desktop notice (shown when no orientation data) -->
            <div id="compass-desktop-notice" class="hidden mt-3 text-center">
                <div class="text-sm font-semibold text-amber-600 dark:text-amber-400 mb-1">${t('Desktop Mode')}</div>
                <div class="text-xs text-gray-500 dark:text-gray-400">${t('Compass sensors not available.')}<br>${t('Use on mobile for live tracking.')}</div>
            </div>

            <!-- Distance -->
            <div id="compass-distance" class="text-2xl font-bold text-gray-800 dark:text-white mt-1">-- km</div>

            <!-- Details -->
            <div class="text-xs text-gray-500 dark:text-gray-400 mt-2 space-y-0.5 text-center">
                <div id="compass-heading" class="compass-mobile-only">${t('You face:')} --°</div>
                <div id="compass-bearing">${t('Station:')} --°</div>
                <div id="compass-celestial" class="compass-mobile-only">☀️ -- · 🌙 --</div>
            </div>

            <!-- Help text (mobile only) -->
            <div class="compass-mobile-only text-xs text-gray-400 dark:text-gray-500 mt-3 text-center leading-relaxed">
                <span class="text-blue-500 font-medium">${t('Blue')}</span> → ${t('Station')}<br>
                <span class="text-orange-500 font-medium">${t('Orange')}</span> → ${t('You')}<br>
                ☀️ 🌙 → ${t('Match the real sky to trust the arrow')}
            </div>
            <div class="compass-mobile-only text-[11px] text-gray-400 dark:text-gray-500 mt-2 text-center">${t('Hold your phone flat')}</div>
        `;
        document.body.appendChild(compassContainer);

        // Close button handler
        document.getElementById('compass-close').addEventListener('click', stopCompass);
    }

    // Update target name
    document.getElementById('compass-target-name').textContent = compassState.targetName || t('Station');

    compassContainer.classList.remove('hidden');
    updateCompassDisplay();
}

// Hide compass UI
function hideCompassUI() {
    const compassContainer = document.getElementById('compass-container');
    if (compassContainer) {
        compassContainer.classList.add('hidden');
    }
}

// Add compass button to station info (called from main code)
function addCompassButton(stationLat, stationLng, stationName, userLat, userLng) {
    const btn = document.createElement('button');
    btn.className = 'compass-btn mt-2 w-full inline-flex items-center justify-center gap-2 bg-gray-50 hover:bg-gray-100 dark:bg-gray-700/50 dark:hover:bg-gray-700 text-slate-700 dark:text-slate-200 border border-gray-200 dark:border-gray-600 text-sm font-medium py-2 px-3 rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 focus-visible:ring-offset-2 dark:focus-visible:ring-offset-gray-800 transition-colors';
    btn.innerHTML = `
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polygon points="3 11 22 2 13 21 11 13 3 11"></polygon>
        </svg>
        ${t('Navigate to Station')}
    `;
    btn.addEventListener('click', async (e) => {
        e.preventDefault();
        e.stopPropagation();
        await startCompass(stationLat, stationLng, stationName, userLat, userLng);
    });
    return btn;
}

// Check if compass is supported
function isCompassSupported() {
    return typeof DeviceOrientationEvent !== 'undefined';
}

// Export for use in other modules
window.CompassModule = {
    start: startCompass,
    stop: stopCompass,
    addButton: addCompassButton,
    isSupported: isCompassSupported,
    isMobile: detectMobileDevice,
    isActive: () => compassState.isActive
};
