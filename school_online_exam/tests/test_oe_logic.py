# -*- coding: utf-8 -*-
"""Pure-python tests (no database needed):
    python3 -m unittest school_online_exam/tests/test_oe_logic.py  (from the addons folder)
"""
import importlib.util
import os
import random
import unittest
from datetime import datetime, timedelta

_path = os.path.join(os.path.dirname(__file__), '..', 'models', 'oe_logic.py')
_spec = importlib.util.spec_from_file_location('oe_logic', _path)
logic = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(logic)


def simulate(pool_size, n, attempts, avoid=True, seed=1):
    rng = random.Random(seed)
    pool = list(range(1, pool_size + 1))
    history = []
    for _ in range(attempts):
        seen = logic.seen_in_current_cycle(history, pool)
        history.append(logic.pick_questions(pool, seen, n, avoid, rng))
    return history


class TestPick(unittest.TestCase):

    def test_first_attempt_is_10_distinct_from_pool(self):
        for seed in range(50):
            h = simulate(50, 10, 1, seed=seed)[0]
            self.assertEqual(len(h), 10)
            self.assertEqual(len(set(h)), 10)
            self.assertTrue(set(h) <= set(range(1, 51)))

    def test_five_attempts_cover_all_50_without_repeat(self):
        for seed in range(50):
            h = simulate(50, 10, 5, seed=seed)
            flat = [q for a in h for q in a]
            self.assertEqual(sorted(flat), list(range(1, 51)))

    def test_attempts_differ(self):
        h = simulate(50, 10, 10, seed=7)
        self.assertEqual(len({tuple(sorted(a)) for a in h}), 10)

    def test_second_round_starts_fresh(self):
        h = simulate(50, 10, 10, seed=3)
        for rnd in (h[:5], h[5:]):
            flat = [q for a in rnd for q in a]
            self.assertEqual(sorted(flat), list(range(1, 51)))

    def test_pool_not_multiple_of_n_no_dup_inside_attempt(self):
        for seed in range(100):
            for a in simulate(25, 10, 12, seed=seed):
                self.assertEqual(len(a), 10)
                self.assertEqual(len(set(a)), 10)

    def test_pool_25_uses_unseen_first(self):
        h = simulate(25, 10, 3, seed=11)
        # attempt 3 must contain the 5 never-seen questions
        never = set(range(1, 26)) - set(h[0]) - set(h[1])
        self.assertTrue(never <= set(h[2]))

    def test_avoid_repeat_off_is_plain_random(self):
        h = simulate(50, 10, 200, avoid=False, seed=5)
        self.assertTrue(all(len(set(a)) == 10 for a in h))
        flat = [q for a in h[:5] for q in a]
        self.assertLess(len(set(flat)), 50)       # some repeats expected

    def test_pool_smaller_than_n(self):
        self.assertEqual(len(logic.pick_questions([1, 2, 3], set(), 10)), 3)
        self.assertEqual(logic.pick_questions([], set(), 10), [])

    def test_bank_grows_new_questions_join_unseen_pool(self):
        h = simulate(50, 10, 2, seed=2)
        seen_before = {q for a in h for q in a}
        pool = list(range(1, 56))                # 5 new questions added to the bank
        seen = logic.seen_in_current_cycle(h, pool)
        self.assertEqual(seen, seen_before)
        for seed in range(30):
            pick = logic.pick_questions(pool, seen, 10, True, random.Random(seed))
            self.assertFalse(set(pick) & seen)   # nothing already seen is repeated
            self.assertEqual(len(set(pick)), 10)


class TestOptionsAndTimer(unittest.TestCase):

    def test_shuffle_keeps_all_keys(self):
        for seed in range(20):
            k = logic.shuffled_keys('abcd', True, random.Random(seed))
            self.assertEqual(sorted(k), list('abcd'))
        self.assertEqual(logic.shuffled_keys('abcd', False), list('abcd'))

    def test_two_minute_timer(self):
        start = datetime(2026, 10, 8, 10, 0, 0)
        deadline = start + timedelta(minutes=2)
        self.assertEqual(logic.remaining_seconds(deadline, start), 120)
        # student leaves at 30s, comes back at 70s -> 50s left (timer never paused)
        self.assertEqual(logic.remaining_seconds(deadline, start + timedelta(seconds=70)), 50)
        self.assertEqual(logic.remaining_seconds(deadline, start + timedelta(minutes=5)), 0)

    def test_expiry_with_grace(self):
        deadline = datetime(2026, 10, 8, 10, 2, 0)
        self.assertFalse(logic.is_expired(deadline, deadline + timedelta(seconds=3), 5))
        self.assertTrue(logic.is_expired(deadline, deadline + timedelta(seconds=6), 5))
        self.assertFalse(logic.is_expired(deadline, deadline - timedelta(seconds=1), 5))


class TestUploadValidation(unittest.TestCase):

    def test_valid_files(self):
        self.assertEqual(logic.validate_upload('a.pdf', b'%PDF-1.7 x', 100)[1], 'application/pdf')
        self.assertEqual(logic.validate_upload('p.JPG', b'\xff\xd8\xff\xe0', 100)[1], 'image/jpeg')
        self.assertEqual(logic.validate_upload('p.png', b'\x89PNG\r\n\x1a\nx', 100)[1], 'image/png')

    def test_rejected_files(self):
        bad = [('x.exe', b'MZ'), ('x.pdf', b'MZ..'), ('x.png', b''), ('x.txt', b'hi'),
               ('noext', b'%PDF-1'), ('x.pdf', b'%PDF-' + b'0' * 200)]
        for name, data in bad:
            with self.assertRaises(ValueError):
                logic.validate_upload(name, data, 100)

    def test_filename_is_sanitised(self):
        self.assertEqual(logic.validate_upload('../../etc/pass wd.pdf', b'%PDF-1', 100)[0], 'pass wd.pdf')
        self.assertNotIn('/', logic.safe_filename('a/b\\c<>.pdf'))


if __name__ == '__main__':
    unittest.main()
