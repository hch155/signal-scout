import unittest, json
from app import app

class QueriesTestCase(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_submit_location(self):
        location_data = {'lat': 53.19122467094173, 'lng': 23.170166015625004}
        response = self.client.post('/submit_location', data=json.dumps(location_data), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data.decode('utf-8'))
        
        self.assertIsInstance(data, list)
        self.assertGreater(len(data), 0)
        for item in data:
            self.assertIn('basestation_id', item)
            
if __name__ == '__main__':
    unittest.main()
