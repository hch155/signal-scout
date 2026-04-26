// PASTE INTO BROWSER CONSOLE @ https://signal-scout.com/account
// (Be logged in first.)
//
// What it does:
//   - Loads 50 random PL coords from the repo's JSON fixture
//   - POSTs each to /account/locations sequentially (200ms between calls
//     to stay under rate limit)
//   - Logs progress + final summary

(async () => {
  const csrf = document.querySelector('meta[name=csrf-token]')?.content;
  if (!csrf) { console.error('No CSRF meta tag — are you on signal-scout.com and logged in?'); return; }

  // Inline fixture so you don't need to fetch raw GitHub URL
  const LOCATIONS = JSON.parse(`{"locations": [{"name": "Test spot 001", "lat": 53.15627, "lng": 14.25511, "radius_km": 15.0, "alerting_enabled": true}, {"name": "Test spot 002", "lat": 50.78769, "lng": 16.27675, "radius_km": 15.0, "alerting_enabled": true}, {"name": "Test spot 003", "lat": 53.78706, "lng": 20.90233, "radius_km": 15.0, "alerting_enabled": true}, {"name": "Test spot 004", "lat": 54.79917, "lng": 14.88678, "radius_km": 15.0, "alerting_enabled": true}, {"name": "Test spot 005", "lat": 51.74249, "lng": 14.30393, "radius_km": 15.0, "alerting_enabled": true}, {"name": "Test spot 006", "lat": 50.42115, "lng": 19.15462, "radius_km": 15.0, "alerting_enabled": true}, {"name": "Test spot 007", "lat": 49.17248, "lng": 16.02814, "radius_km": 15.0, "alerting_enabled": true}, {"name": "Test spot 008", "lat": 53.22425, "lng": 19.5584, "radius_km": 15.0, "alerting_enabled": true}, {"name": "Test spot 009", "lat": 50.43286, "lng": 20.01051, "radius_km": 15.0, "alerting_enabled": true}, {"name": "Test spot 010", "lat": 54.2613, "lng": 14.06629, "radius_km": 15.0, "alerting_enabled": true}, {"name": "Test spot 011", "lat": 54.23783, "lng": 21.12102, "radius_km": 15.0, "alerting_enabled": true}, {"name": "Test spot 012", "lat": 51.21163, "lng": 15.58589, "radius_km": 15.0, "alerting_enabled": true}, {"name": "Test spot 013", "lat": 55.22188, "lng": 17.43326, "radius_km": 15.0, "alerting_enabled": true}, {"name": "Test spot 014", "lat": 49.60285, "lng": 14.98651, "radius_km": 15.0, "alerting_enabled": true}, {"name": "Test spot 015", "lat": 54.50871, "lng": 20.15801, "radius_km": 15.0, "alerting_enabled": true}, {"name": "Test spot 016", "lat": 54.24633, "lng": 21.44326, "radius_km": 15.0, "alerting_enabled": true}, {"name": "Test spot 017", "lat": 52.48548, "lng": 23.92578, "radius_km": 15.0, "alerting_enabled": true}, {"name": "Test spot 018", "lat": 51.46047, "lng": 19.63081, "radius_km": 15.0, "alerting_enabled": true}, {"name": "Test spot 019", "lat": 54.39113, "lng": 20.3089, "radius_km": 15.0, "alerting_enabled": true}, {"name": "Test spot 020", "lat": 54.60109, "lng": 19.88899, "radius_km": 15.0, "alerting_enabled": true}, {"name": "Test spot 021", "lat": 53.57972, "lng": 14.46741, "radius_km": 15.0, "alerting_enabled": true}, {"name": "Test spot 022", "lat": 50.48134, "lng": 16.95176, "radius_km": 15.0, "alerting_enabled": true}, {"name": "Test spot 023", "lat": 49.51865, "lng": 16.37447, "radius_km": 15.0, "alerting_enabled": true}, {"name": "Test spot 024", "lat": 49.65651, "lng": 16.83533, "radius_km": 15.0, "alerting_enabled": true}, {"name": "Test spot 025", "lat": 53.13195, "lng": 17.72129, "radius_km": 15.0, "alerting_enabled": true}, {"name": "Test spot 026", "lat": 51.40618, "lng": 16.13697, "radius_km": 15.0, "alerting_enabled": true}, {"name": "Test spot 027", "lat": 50.73536, "lng": 23.55388, "radius_km": 15.0, "alerting_enabled": true}, {"name": "Test spot 028", "lat": 53.21223, "lng": 20.21314, "radius_km": 15.0, "alerting_enabled": true}, {"name": "Test spot 029", "lat": 50.1124, "lng": 21.43709, "radius_km": 15.0, "alerting_enabled": true}, {"name": "Test spot 030", "lat": 50.06212, "lng": 17.87045, "radius_km": 15.0, "alerting_enabled": true}, {"name": "Test spot 031", "lat": 55.4319, "lng": 20.528, "radius_km": 15.0, "alerting_enabled": true}, {"name": "Test spot 032", "lat": 52.62017, "lng": 20.98307, "radius_km": 15.0, "alerting_enabled": true}, {"name": "Test spot 033", "lat": 54.47854, "lng": 21.9152, "radius_km": 15.0, "alerting_enabled": true}, {"name": "Test spot 034", "lat": 50.48881, "lng": 14.32742, "radius_km": 15.0, "alerting_enabled": true}, {"name": "Test spot 035", "lat": 51.05044, "lng": 16.73096, "radius_km": 15.0, "alerting_enabled": true}, {"name": "Test spot 036", "lat": 50.37139, "lng": 23.61768, "radius_km": 15.0, "alerting_enabled": true}, {"name": "Test spot 037", "lat": 54.69639, "lng": 17.20971, "radius_km": 15.0, "alerting_enabled": true}, {"name": "Test spot 038", "lat": 53.26035, "lng": 18.03545, "radius_km": 15.0, "alerting_enabled": true}, {"name": "Test spot 039", "lat": 54.94456, "lng": 18.68029, "radius_km": 15.0, "alerting_enabled": true}, {"name": "Test spot 040", "lat": 50.72172, "lng": 16.5156, "radius_km": 15.0, "alerting_enabled": true}, {"name": "Test spot 041", "lat": 52.64889, "lng": 16.67996, "radius_km": 15.0, "alerting_enabled": true}, {"name": "Test spot 042", "lat": 52.79981, "lng": 23.15779, "radius_km": 15.0, "alerting_enabled": true}, {"name": "Test spot 043", "lat": 51.5961, "lng": 16.23707, "radius_km": 15.0, "alerting_enabled": true}, {"name": "Test spot 044", "lat": 55.48399, "lng": 19.19717, "radius_km": 15.0, "alerting_enabled": true}, {"name": "Test spot 045", "lat": 49.59091, "lng": 14.48059, "radius_km": 15.0, "alerting_enabled": true}, {"name": "Test spot 046", "lat": 49.71272, "lng": 20.39995, "radius_km": 15.0, "alerting_enabled": true}, {"name": "Test spot 047", "lat": 54.14852, "lng": 18.30603, "radius_km": 15.0, "alerting_enabled": true}, {"name": "Test spot 048", "lat": 49.41293, "lng": 17.89252, "radius_km": 15.0, "alerting_enabled": true}, {"name": "Test spot 049", "lat": 55.47479, "lng": 19.39697, "radius_km": 15.0, "alerting_enabled": true}, {"name": "Test spot 050", "lat": 55.31201, "lng": 22.77995, "radius_km": 15.0, "alerting_enabled": true}]}`).locations;

  console.log(`Seeding ${LOCATIONS.length} locations…`);
  let ok = 0, fail = 0;
  for (let i = 0; i < LOCATIONS.length; i++) {
    const loc = LOCATIONS[i];
    try {
      const r = await fetch('/account/locations', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
        body: JSON.stringify(loc),
      });
      if (r.ok) {
        ok++;
        if ((i+1) % 10 === 0) console.log(`  ${i+1}/${LOCATIONS.length}…`);
      } else {
        fail++;
        const t = await r.text();
        console.warn(`  ${loc.name}: HTTP ${r.status} — ${t.slice(0,200)}`);
      }
    } catch (e) {
      fail++;
      console.warn(`  ${loc.name}: ${e.message}`);
    }
    await new Promise(res => setTimeout(res, 200));
  }
  console.log(`✅ DONE  ok=${ok}  fail=${fail}`);
})();

