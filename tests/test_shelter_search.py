import unittest

import app


class ShelterSearchFilterTests(unittest.TestCase):
    def setUp(self):
        app.shelters = [
            {
                'id': 1,
                'name': '青森駅前避難所',
                'district': '中央',
                'capacity': 250,
                'parking': True,
                'pet': True,
                'barrierFree': True,
                'senior_disability_support': True,
                'disability_consideration': True,
                'disaster_types': ['洪水', '地震'],
            },
            {
                'id': 2,
                'name': '海岸避難所',
                'district': '海岸',
                'capacity': 80,
                'parking': False,
                'pet': False,
                'barrierFree': False,
                'senior_disability_support': False,
                'disability_consideration': False,
                'disaster_types': ['津波'],
            },
        ]

    def test_free_search_and_aliases_are_applied_together(self):
        criteria = {
            'free_search': '青森駅、駐車場',
            'parking_available': True,
            'pet_friendly': True,
            'barrier_free': True,
            'senior_disability_support': True,
            'disability_consideration': True,
            'disaster_types': ['洪水', '地震'],
        }
        results = app.filter_shelters(None, criteria)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['name'], '青森駅前避難所')

    def test_capacity_condition_is_applied_with_alias_keys(self):
        criteria = {
            'evacuee_count': '100',
            'pet_allowed': True,
            'barrierFree': True,
            'disability': True,
        }
        results = app.filter_shelters(None, criteria)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['name'], '青森駅前避難所')


if __name__ == '__main__':
    unittest.main()
