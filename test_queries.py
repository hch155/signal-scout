import unittest
from app import app
from queries import get_all_stations

class QueriesTestCase(unittest.TestCase):
    def setUp(self):
        self.app = app.test_client()

    def test_get_all_stations(self):
        response = self.app.get('/stations')
        self.assertEqual(response.status_code, 200)
       
if __name__ == '__main__':
    unittest.main()
