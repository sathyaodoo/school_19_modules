# -*- coding: utf-8 -*-
"""Pure-python helpers (no Odoo imports) so the rules can be unit-tested
without a database.

Rules implemented here
----------------------
* pick_questions       : which N questions an attempt gets
* seen_in_current_cycle: which questions the student already saw in the
                         current "round" of the bank (a round ends when every
                         question of the pool has been shown once)
* shuffled_keys        : option order for one question
* remaining_seconds / is_expired : timer maths (server clock)
"""
import random
import re

OPTION_KEYS = ('a', 'b', 'c', 'd')


def seen_in_current_cycle(history, pool_ids):
    """history: list of attempts (oldest first), each a list of question ids.

    Returns the set of pool questions already used in the current round.
    When an attempt completes the round, the questions of that attempt that
    were only re-used as "filler" start the next round.
    """
    pool = set(pool_ids)
    seen = set()
    for qids in history:
        used = set(q for q in qids if q in pool)
        unseen_before = pool - seen
        seen |= used
        if pool and not (pool - seen):
            seen = used - unseen_before      # fillers open the next round
    return seen


def pick_questions(pool_ids, seen_ids, n, avoid_repeat=True, rng=random):
    """Return n question ids (fewer only if the pool itself is smaller)."""
    pool = list(dict.fromkeys(pool_ids))
    n = min(int(n), len(pool))
    if n <= 0:
        return []
    if not avoid_repeat:
        return rng.sample(pool, n)
    seen = set(seen_ids)
    unseen = [q for q in pool if q not in seen]
    if len(unseen) >= n:
        return rng.sample(unseen, n)
    already = [q for q in pool if q in seen]
    picked = unseen + rng.sample(already, n - len(unseen))
    rng.shuffle(picked)
    return picked


def shuffled_keys(keys, shuffle=True, rng=random):
    keys = list(keys)
    if shuffle:
        rng.shuffle(keys)
    return keys


def remaining_seconds(deadline, now):
    """Seconds left (never negative). deadline / now are datetimes."""
    return max(0, int((deadline - now).total_seconds()))


def is_expired(deadline, now, grace_seconds=0):
    return (now - deadline).total_seconds() > grace_seconds


# ----------------------------------------------------------------------
# Answer-sheet / assignment upload validation (pure python)
# ----------------------------------------------------------------------
UPLOAD_MAGIC = {
    'pdf': (b'%PDF-',),
    'jpg': (b'\xff\xd8\xff',),
    'jpeg': (b'\xff\xd8\xff',),
    'png': (b'\x89PNG\r\n\x1a\n',),
}
UPLOAD_MIME = {'pdf': 'application/pdf', 'jpg': 'image/jpeg',
               'jpeg': 'image/jpeg', 'png': 'image/png'}


def safe_filename(name):
    base = re.split(r'[\\/]', name or '')[-1]
    base = re.sub(r'[^A-Za-z0-9._ -]', '_', base).strip(' .')
    return base or 'file'


def validate_upload(filename, data, max_bytes):
    """Return (safe_name, mimetype) or raise ValueError(<message for the student>).

    The extension must be pdf/jpg/jpeg/png AND the file content must really
    start like that type (a renamed .exe is refused)."""
    name = safe_filename(filename)
    ext = name.rsplit('.', 1)[-1].lower() if '.' in name else ''
    if ext not in UPLOAD_MAGIC:
        raise ValueError('Only PDF, JPG and PNG files are allowed.')
    if not data:
        raise ValueError('"%s" is empty.' % name)
    if len(data) > max_bytes:
        raise ValueError('"%s" is bigger than %s MB.' % (name, max_bytes // (1024 * 1024)))
    if not any(data.startswith(m) for m in UPLOAD_MAGIC[ext]):
        raise ValueError('"%s" is not a valid %s file.' % (name, ext.upper()))
    return name, UPLOAD_MIME[ext]
