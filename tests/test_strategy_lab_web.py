import json
import os
import tempfile
import unittest
from unittest.mock import patch
from web_app import app

class StrategyLabWebTests(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        app.secret_key = 'test-only'
        self.client = app.test_client()

    def test_requires_login(self):
        self.assertEqual(self.client.get('/api/strategy-lab').status_code, 401)

    def test_missing_results_is_explicit(self):
        with self.client.session_transaction() as session: session['authorized']=True
        with patch.dict(os.environ, {'STRATEGY_LAB_RESULTS':'/missing/results.json'}):
            data=self.client.get('/api/strategy-lab').get_json()
        self.assertEqual(data['status'], 'NOT_RUN')

    def test_results(self):
        with tempfile.TemporaryDirectory() as folder:
            path=os.path.join(folder, 'results.json')
            with open(path,'w') as f: json.dump({'candles':1000,'strategies':[{'strategy':'TREND-01','return_pct':2,'equity_curve':[50,51]}]},f)
            with self.client.session_transaction() as session: session['authorized']=True
            with patch.dict(os.environ, {'STRATEGY_LAB_RESULTS':path}):
                data=self.client.get('/api/strategy-lab').get_json()
            self.assertEqual(data['status'],'BACKTEST')
            self.assertNotIn('equity_curve',data['strategies'][0])
