import sys
import unittest
import json
import io
from datetime import datetime

# Windows encoding fix
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from database.db import (
    init_db, create_user, login_user, create_session, validate_session,
    delete_session, get_user_by_id, get_users_count,
    save_meal, get_recent_meals, get_today_summary,
    save_user_weight_and_goals, get_user_goals
)
from api.index import handler

class DummyRequest:
    def __init__(self, body_bytes=b''):
        self._body = io.BytesIO(body_bytes)
    def makefile(self, *args, **kwargs):
        return self._body
    def sendall(self, *args, **kwargs):
        pass

class TestAuth(unittest.TestCase):
    def setUp(self):
        init_db()

    def test_user_creation_and_login(self):
        ts = int(datetime.now().timestamp())
        uname = f'user_{ts}'
        pwd = 'secret_password_123'

        user = create_user(uname, pwd)
        self.assertIsNotNone(user)
        self.assertIn('user_id', user)
        self.assertEqual(user['username'], uname)

        # Duplicate username should fail
        with self.assertRaises(ValueError):
            create_user(uname, pwd)

        # Login with correct password
        logged = login_user(uname, pwd)
        self.assertIsNotNone(logged)
        self.assertEqual(logged['user_id'], user['user_id'])

        # Login with wrong password
        wrong = login_user(uname, 'wrong_pass')
        self.assertIsNone(wrong)

        # Login with non-existent user
        non_existent = login_user('nobody_xyz_123', pwd)
        self.assertIsNone(non_existent)

    def test_session_management(self):
        ts = int(datetime.now().timestamp())
        user = create_user(f'sess_user_{ts}', 'mypassword')
        user_id = user['user_id']

        # Create session
        token = create_session(user_id, device_name='TestBrowser 1.0')
        self.assertIsNotNone(token)
        self.assertGreaterEqual(len(token), 32)

        # Validate valid session
        val_user_id = validate_session(token)
        self.assertEqual(val_user_id, user_id)

        # Validate invalid token
        self.assertIsNone(validate_session('invalid_token_123456789012345678901234'))

        # Delete session (logout)
        delete_session(token)
        self.assertIsNone(validate_session(token))

    def test_data_isolation_between_users(self):
        ts = int(datetime.now().timestamp())
        u1 = create_user(f'alice_{ts}', 'pass1234')
        u2 = create_user(f'bob_{ts}', 'pass1234')

        # Alice saves a meal
        save_meal('Яичница 2 яйца', 'text', [{'product_name': 'яйцо', 'quantity_g': 100, 'calories': 150, 'protein_g': 12, 'fat_g': 10, 'carbs_g': 1}], user_id=u1['user_id'])

        # Bob saves a different meal
        save_meal('Овсянка 200г', 'text', [{'product_name': 'овсянка', 'quantity_g': 200, 'calories': 200, 'protein_g': 8, 'fat_g': 4, 'carbs_g': 36}], user_id=u2['user_id'])

        # Check Alice's meals
        alice_meals = get_recent_meals(limit=5, user_id=u1['user_id'])
        self.assertTrue(any('Яичница' in m['raw_input'] for m in alice_meals))
        self.assertFalse(any('Овсянка' in m['raw_input'] for m in alice_meals))

        # Check Bob's meals
        bob_meals = get_recent_meals(limit=5, user_id=u2['user_id'])
        self.assertTrue(any('Овсянка' in m['raw_input'] for m in bob_meals))
        self.assertFalse(any('Яичница' in m['raw_input'] for m in bob_meals))

        # Check Goals isolation
        save_user_weight_and_goals(70.0, mode='loss_400', user_id=u1['user_id'])
        save_user_weight_and_goals(95.0, mode='gain', user_id=u2['user_id'])

        alice_goals = get_user_goals(user_id=u1['user_id'])
        bob_goals = get_user_goals(user_id=u2['user_id'])

        self.assertEqual(alice_goals['weight_current'], 70.0)
        self.assertEqual(alice_goals['goal_mode'], 'loss_400')

        self.assertEqual(bob_goals['weight_current'], 95.0)
        self.assertEqual(bob_goals['goal_mode'], 'gain')

if __name__ == '__main__':
    unittest.main()
