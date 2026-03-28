import unittest
import json
from app import app


class QueriesTestCase(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        self.client = app.test_client()

    def test_submit_location(self):
        location_data = {'lat': 53.19122467094173, 'lng': 23.170166015625004}
        response = self.client.post(
            '/submit_location',
            data=json.dumps(location_data),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data.decode('utf-8'))

        self.assertIsInstance(data, dict)
        self.assertGreater(len(data['stations']), 0)
        self.assertIn('count', data)
        self.assertIsInstance(data['count'], int)
        self.assertIn('stations', data)
        self.assertIsInstance(data['stations'], list)

        for station in data['stations']:
            self.assertIn('basestation_id', station)

    def test_submit_location_out_of_bounds(self):
        """Coordinates outside Poland should return 400."""
        location_data = {'lat': 0.0, 'lng': 0.0}
        response = self.client.post(
            '/submit_location',
            data=json.dumps(location_data),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 400)

    def test_submit_location_missing_data(self):
        """Missing lat/lng should return 500."""
        response = self.client.post(
            '/submit_location',
            data=json.dumps({}),
            content_type='application/json',
        )
        self.assertIn(response.status_code, [400, 500])

    def test_stations_without_location(self):
        """GET /stations without session location should return 400."""
        response = self.client.get('/stations')
        self.assertEqual(response.status_code, 400)

    def test_stations_with_valid_coords(self):
        """GET /stations with valid lat/lng params."""
        response = self.client.get('/stations?lat=52.23&lng=21.00')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertIn('stations', data)

    def test_stations_out_of_bounds(self):
        """GET /stations with coords outside Poland should return 400."""
        response = self.client.get('/stations?lat=10.0&lng=10.0')
        self.assertEqual(response.status_code, 400)

    def test_stations_invalid_limit(self):
        """Limit > 10 should return 400."""
        response = self.client.get('/stations?lat=52.23&lng=21.00&limit=100')
        self.assertEqual(response.status_code, 400)

    def test_stations_invalid_max_distance(self):
        """max_distance > 10 should return 400."""
        response = self.client.get('/stations?lat=52.23&lng=21.00&max_distance=50')
        self.assertEqual(response.status_code, 400)

    def test_find_station_valid(self):
        """Search for a station by ID."""
        response = self.client.get('/find_station?basestation_id=AAAA')
        self.assertIn(response.status_code, [200, 404])

    def test_find_station_invalid_id(self):
        """Invalid basestation_id format should return 400."""
        response = self.client.get('/find_station?basestation_id=<script>')
        self.assertEqual(response.status_code, 400)

    def test_find_station_too_long(self):
        """basestation_id > 7 chars should return 400."""
        response = self.client.get('/find_station?basestation_id=TOOLONGID')
        self.assertEqual(response.status_code, 400)

    def test_search_stations_valid(self):
        """Search autocomplete with valid query."""
        response = self.client.get('/search_stations?q=AB')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertIn('stations', data)

    def test_search_stations_too_short(self):
        """Query too short should return empty list."""
        response = self.client.get('/search_stations?q=A')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data['stations'], [])

    def test_search_stations_invalid_chars(self):
        """Special characters in search should return empty list."""
        response = self.client.get('/search_stations?q=<script>')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data['stations'], [])

    def test_session_check(self):
        """Session check should return logged_in status."""
        response = self.client.get('/session_check')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertIn('logged_in', data)
        self.assertFalse(data['logged_in'])

    def test_debug_session_removed(self):
        """Debug session endpoint should no longer exist."""
        response = self.client.get('/debug_session')
        self.assertEqual(response.status_code, 404)

    def test_register_without_csrf(self):
        """Registration without CSRF token should return 403."""
        response = self.client.post('/register', data={
            'email': 'test@test.com',
            'password': 'Test1234!',
            'confirm_password': 'Test1234!',
        })
        self.assertEqual(response.status_code, 403)

    def test_login_without_csrf(self):
        """Login without CSRF token should return 403."""
        response = self.client.post('/login', data={
            'email': 'test@test.com',
            'password': 'Test1234!',
        })
        self.assertEqual(response.status_code, 403)

    def test_security_headers(self):
        """Responses should include security headers."""
        response = self.client.get('/')
        self.assertEqual(response.headers.get('X-Content-Type-Options'), 'nosniff')
        self.assertEqual(response.headers.get('X-Frame-Options'), 'DENY')
        self.assertIn('Strict-Transport-Security', response.headers)

    def test_home_page(self):
        """Home page should return 200."""
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)

    def test_data_page(self):
        """Data page should return 200."""
        response = self.client.get('/data')
        self.assertEqual(response.status_code, 200)

    def test_tips_page(self):
        """Tips page should return 200."""
        response = self.client.get('/tips')
        self.assertEqual(response.status_code, 200)

    def test_stats_page(self):
        """Stats page should return 200."""
        response = self.client.get('/stats')
        self.assertEqual(response.status_code, 200)

    def test_logout_without_login(self):
        """Logout without being logged in should return 403 (CSRF required)."""
        response = self.client.post('/logout')
        self.assertEqual(response.status_code, 403)


if __name__ == '__main__':
    unittest.main()
