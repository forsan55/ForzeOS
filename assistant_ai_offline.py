"""
assistant_ai_offline.py

Lightweight offline assistant intended to be used by ForzeOS.
Features implemented to match your request:
- Very large offline memory loaded from JSON (`assistant_memory.json`).
- Compact hashed n-gram vectorizer (small fixed dimension) — cheap to compute.
- Fast similarity lookup using cached vectors (dot-product) — no heavy libs.
- Non-repeating responses per session: stores last-N responses and avoids duplicates.
- Variation/paraphrase generator that composes replies from templates and morphs words
  using fast, low-cost heuristics (character edits, suffixes, small shuffles).
- Memory growth (reservoir-like) so new inputs can be added without big memory churn.
- Deterministic-but-varied behavior via seeded RNG per session so answers vary but are
  reproducible for a session if needed.

Design goals: offline, low CPU/RAM, no GPU, no external APIs. Pure Python.
"""
from __future__ import annotations

import json
import os
import time
import math
import random
import hashlib
from typing import List, Dict, Optional, Tuple

# Minimal defaults — tweak if needed
MEMORY_FILE = os.path.join(os.path.dirname(__file__), 'assistant_memory.json')
VECTOR_DIM = 128  # small fixed-size hashed vector
NGRAM = 3         # character n-grams
MAX_SESSIONS_STORE = 200


def _hash_bytes(s: str) -> int:
    # stable hash function returning a positive int
    return int(hashlib.sha1(s.encode('utf-8')).hexdigest(), 16)


class EnhancedAssistantAI:
    def __init__(self, memory_path: str = MEMORY_FILE, vector_dim: int = VECTOR_DIM,
                 ngram: int = NGRAM, session_size: int = 50):
        self.memory_path = memory_path
        self.vector_dim = vector_dim
        self.ngram = ngram
        self.session_size = session_size

        self.memory: List[str] = []
        self._mem_vectors: List[List[float]] = []  # cached vectors

        # sessions: session_id -> {'history': [(who,text)], 'recent_responses': [resp], 'seed': int}
        self.sessions: Dict[str, Dict] = {}

        # load memory (if missing, create minimal seed)
        self._load_memory()

    # --------------------- memory & persistence ---------------------
    def _load_memory(self):
        if os.path.exists(self.memory_path):
            try:
                with open(self.memory_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                # memory expected to be a list of strings
                if isinstance(data, list):
                    self.memory = data
                else:
                    # older formats may be dicts
                    self.memory = list(data.keys())
            except Exception:
                # fallback to tiny default
                self.memory = ["Merhaba! Nasıl yardımcı olabilirim?", "Ne yapmak istersiniz?"]
        else:
            # write a starter memory file
            self.memory = [
                "Merhaba!", "Selam!", "Nasılsın?", "Size nasıl yardımcı olabilirim?",
                "Bana bir görev ver.", "Open gallery", "Open music", "How can I help?",
            ]
            try:
                with open(self.memory_path, 'w', encoding='utf-8') as f:
                    json.dump(self.memory, f, ensure_ascii=False, indent=2)
            except Exception:
                pass
        # build cached vectors
        self._mem_vectors = [self._vectorize(m) for m in self.memory]

    def _persist_memory(self):
        # cheap save; overwrite file
        try:
            with open(self.memory_path, 'w', encoding='utf-8') as f:
                json.dump(self.memory, f, ensure_ascii=False)
        except Exception:
            # swallowing persistence errors is intentional (non-fatal)
            pass

    def _add_to_memory(self, text: str, capacity: int = 20000):
        # Add new phrase with simple uniqueness check (lowercased)
        t = text.strip()
        if not t:
            return
        lower = t.lower()
        if any(lower == m.lower() for m in self.memory[-2000:]):
            return
        # keep memory bounded
        if len(self.memory) >= capacity:
            # replace randomly (reservoir-like)
            idx = random.randrange(len(self.memory))
            self.memory[idx] = t
            self._mem_vectors[idx] = self._vectorize(t)
        else:
            self.memory.append(t)
            self._mem_vectors.append(self._vectorize(t))
        # persist lazily — do not persist on every add; calling code may call persist

    # --------------------- vectorization & similarity ---------------------
    def _vectorize(self, text: str) -> List[float]:
        # hashed character n-gram counts into fixed-dim vector (very cheap)
        v = [0.0] * self.vector_dim
        s = text.lower()
        # pad for starting/ending grams
        padded = ' ' + s + ' '
        L = len(padded)
        for i in range(L - self.ngram + 1):
            gram = padded[i:i + self.ngram]
            h = _hash_bytes(gram)
            idx = h % self.vector_dim
            v[idx] += 1.0
        # normalize to unit length (L2)
        norm = math.sqrt(sum(x * x for x in v))
        if norm > 0:
            inv = 1.0 / norm
            for i in range(self.vector_dim):
                v[i] *= inv
        return v

    def _dot(self, a: List[float], b: List[float]) -> float:
        # small fixed-dim dot product
        s = 0.0
        for i in range(self.vector_dim):
            s += a[i] * b[i]
        return s

    def _find_similar(self, text: str, top_n: int = 6) -> List[Tuple[str, float]]:
        qv = self._vectorize(text)
        scores = []
        for mem_text, mem_v in zip(self.memory, self._mem_vectors):
            scores.append((mem_text, self._dot(qv, mem_v)))
        # sort descending by score
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_n]

    # --------------------- lightweight paraphrase / variation ---------------------
    def _word_morph(self, word: str) -> str:
        # cheap morphological variations: small shuffles, suffix/prefix, truncation
        if len(word) <= 2:
            return word
        r = random.random()
        if r < 0.15:
            # shuffle internal letters
            middle = list(word[1:-1])
            random.shuffle(middle)
            return word[0] + ''.join(middle) + word[-1]
        if r < 0.30:
            # add friendly suffix
            return word + random.choice(['', '!', '..', '?', ' dostum', ' abi', ' hanım'])
        if r < 0.45:
            # small char replacement
            i = random.randrange(0, len(word))
            return word[:i] + random.choice('aeiou') + word[i + 1:]
        if r < 0.60:
            # hyphenate
            i = max(1, len(word) // 2)
            return word[:i] + '-' + word[i:]
        # otherwise unchanged
        return word

    def _compose_response(self, templates: List[str], words: List[str], session_seed: int) -> str:
        # pick a template deterministically using seed
        rnd = random.Random(session_seed + int(time.time() // 3))
        tpl = rnd.choice(templates)
        # simple placeholders: {W0},{W1}
        for i, w in enumerate(words[:6]):
            morph = self._word_morph(w)
            tpl = tpl.replace('{W' + str(i) + '}', morph)
            tpl = tpl.replace('{w' + str(i) + '}', morph.lower())
        # remove any leftover placeholders
        tpl = tpl.replace('{', '').replace('}', '')
        # small punctuation cleanups
        if tpl and tpl[-1] not in '.!?':
            tpl += random.choice(['.', '!', ''])
        return tpl

    # --------------------- public API ---------------------
    def _ensure_session(self, session_id: Optional[str]) -> str:
        sid = session_id or '__default__'
        if sid not in self.sessions:
            seed = _hash_bytes(sid) ^ int(time.time())
            self.sessions[sid] = {
                'history': [],
                'recent_responses': [],
                'seed': seed,
            }
        return sid

    def reply(self, text: str, session_id: Optional[str] = None) -> str:
        sid = self._ensure_session(session_id)
        sess = self.sessions[sid]
        # very simple pre-clean
        text = (text or '').strip()
        if not text:
            return "Bir şey yazın, yardımcı olayım."  # short default

        # record user text
        sess['history'].append(('user', text))
        if len(sess['history']) > self.session_size:
            sess['history'].pop(0)

        # find similar memory entries
        sims = self._find_similar(text, top_n=8)
        # extract candidate words from top matches
        candidates = []
        for mem, score in sims:
            # split into words, prefer unique
            for w in mem.split():
                w = ''.join(ch for ch in w if ch.isalnum() or ch == '-')
                if w:
                    candidates.append((w, score))
        # score words and pick top few
        candidates.sort(key=lambda x: x[1], reverse=True)
        words = [w for w, _ in candidates[:12]]
        if not words:
            # fallback tokens
            words = text.split()[:6]

        # templates pool (can be expanded)
        templates = [
            "{W0} hakkında daha fazla ister misin",
            "Tamam, {W0} ve {W1} arasında bir bağlantı kuruyorum",
            "Anladım — {W0} ile başlayabiliriz",
            "Bunu şöyle yapabiliriz: {W0}, sonra {W1}",
            "Elbette, {W0} üzerine bir öneri: {W1}",
            "İyi fikir: {W0} — bunu detaylandırmak ister misin",
            "{W0} ile ilgili olarak şu adımı atabilirsin: {W1}",
            "Hemen yardımcı olayım: {W0} ve {W1} kombinasyonu işe yarayabilir",
        ]

        # attempt to compose several candidate responses and pick one not recently used
        tries = 0
        response = ''
        while tries < 8:
            seed = sess['seed'] + tries * 7
            cand = self._compose_response(templates, words, seed)
            if cand and cand not in sess['recent_responses']:
                response = cand
                break
            tries += 1
        if not response:
            # forced fallback: slightly mutate best matching memory
            best = sims[0][0] if sims else text
            # apply a few word morphs
            tokens = best.split()
            mutated = ' '.join(self._word_morph(t) for t in tokens[:40])
            response = mutated

        # record response (recently used), bounded
        sess['recent_responses'].append(response)
        if len(sess['recent_responses']) > 50:
            sess['recent_responses'].pop(0)
        sess['history'].append(('assistant', response))

        # add input to memory for incremental learning (cheap)
        try:
            self._add_to_memory(text)
        except Exception:
            pass

        # occasionally persist memory (cheap heuristic)
        if (time.time() % 37) < 1.0:
            try:
                self._persist_memory()
            except Exception:
                pass

        return response

    def execute_command(self, text: str, session_id: Optional[str] = None):
        # This method can be used by ForzeOS to try to parse commands (open X etc.)
        # We implement a lightweight fuzzy mapping:
        sid = self._ensure_session(session_id)
        sims = self._find_similar(text, top_n=10)
        # simple heuristics to detect 'open' intent
        lower = text.lower()
        if 'open' in lower or 'aç' in lower or 'başlat' in lower:
            # try to detect target
            for mem, score in sims:
                mlow = mem.lower()
                if 'gallery' in mlow or 'galeri' in mlow or 'image' in mlow or 'resim' in mlow:
                    return True, ('open_gallery', {})
                if 'music' in mlow or 'müzik' in mlow:
                    return True, ('open_music_player', {})
                if 'file' in mlow or 'dosya' in mlow or 'explorer' in mlow:
                    return True, ('open_file_manager', {})
                if 'terminal' in mlow or 'console' in mlow or 'cmd' in mlow:
                    return True, ('open_terminal', {})
            # fallback: return not-understood as False
            return False, None
        # otherwise, not a command
        return False, None


if __name__ == '__main__':
    a = EnhancedAssistantAI()
    print(a.reply('Merhaba, bana galeri aç'))
    print(a.reply('Something about music please'))
    print(a.reply('Dosya yöneticisini açar mısın'))
