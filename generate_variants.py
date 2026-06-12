"""
generate_variants.py

Create paraphrase/variant Q->A entries from the existing assistant_memory.json
- Uses a lightweight synonym map (Turkish + English common words)
- Produces up to `variants_per` paraphrases per base entry
- Allows near-duplicates; only rejects if similarity > 0.95
- Respects a blocklist to avoid host/command-like entries

Usage (from PowerShell):
  python .\generate_variants.py 1000

This is CPU/lightweight and runs offline.
"""
import sys
import json
import random
import re
from pathlib import Path
from difflib import SequenceMatcher

MEM_PATH = Path(r"C:\Users\User\Downloads\assistant_memory.json")

# Small bilingual synonym map for lightweight paraphrasing
SYNONYM_MAP = {
    # Turkish common
    'yardım': ['destek', 'yardımcı olma', 'destek olma'],
    'nasıl': ['neyi nasıl', 'ne şekilde', 'nasıl yani'],
    'lütfen': ['rica ederim', 'lutfen', 'lütfen'],
    'merhaba': ['selam', 'günaydın', 'iyi günler'],
    'teşekkür': ['sağ ol', 'teşekkürler', 'sağolasın'],
    'sistem': ['sistemim', 'işletim', 'çalışma ortamı'],
    'dosya': ['belge', 'evrak', 'dosya(yı)'],
    'aç': ['başlat', 'açmak', 'başlatmak'],
    'kapat': ['sonlandır', 'kapatmak'],
    'renk': ['ton', 'palet', 'rengi'],
    'öğren': ['öğrenmek', 'ögren', 'öğrenme'],
    # English short ones
    'hello': ['hi', 'hey', 'greetings'],
    'how': ['in what way', 'ne şekilde'],
    'name': ['ad', 'ismin'],
}

BLOCKLIST_PATTERNS = [
    r"open\s+", r"komut", r"sudo", r"restart", r"reboot", r"shutdown", r"çıkış",
]


def sim(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def paraphrase_text(text: str, variants: int = 3) -> list:
    """Return a list of paraphrase variants for `text`."""
    variants_out = []
    # basic lower-case source for replacements, but preserve original for punctuation
    base = text.strip()
    if not base:
        return variants_out

    for i in range(variants * 2):
        t = base
        # random synonym replacements
        for word, syns in SYNONYM_MAP.items():
            # match whole words (case-insensitive)
            if re.search(r"\b" + re.escape(word) + r"\b", t, flags=re.IGNORECASE):
                if random.random() < 0.6:  # 60% chance to replace
                    choice = random.choice(syns)
                    t = re.sub(r"(?i)\b" + re.escape(word) + r"\b", choice, t)
        # light reordering for comma-separated clauses
        if ',' in t and random.random() < 0.4:
            parts = [p.strip() for p in t.split(',') if p.strip()]
            random.shuffle(parts)
            t = ', '.join(parts)
        # small punctuation tweaks
        if random.random() < 0.2:
            t = t.replace('?', '.')
        if random.random() < 0.15:
            t = t + ('?' if t.endswith('.') else '.')
        # trim
        t = re.sub(r'\s+', ' ', t).strip()
        # avoid exact base
        if t.lower() == base.lower():
            continue
        # de-duplicate in local list using a relaxed threshold
        if any(sim(t.lower(), ex.lower()) > 0.96 for ex in variants_out):
            continue
        variants_out.append(t)
        if len(variants_out) >= variants:
            break
    return variants_out


def is_blocked(text: str) -> bool:
    tl = text.lower()
    for p in BLOCKLIST_PATTERNS:
        if re.search(p, tl):
            return True
    return False


def load_memory():
    if not MEM_PATH.exists():
        print('assistant_memory.json not found at', MEM_PATH)
        return {'entries': []}
    with MEM_PATH.open('r', encoding='utf-8') as f:
        data = json.load(f)
    if 'entries' not in data:
        data = {'entries': data}
    return data


def save_memory(data):
    with MEM_PATH.open('w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def main(target: int = 1000, variants_per: int = 3, relax_dup_thresh: float = 0.95):
    data = load_memory()
    entries = data.get('entries', [])
    if not entries:
        print('No entries found to expand.')
        return
    base_inputs = [e.get('in') or '' for e in entries]
    existing = set((e.get('in','').strip().lower() + '|||' + e.get('out','').strip().lower()) for e in entries)

    added = 0
    tries = 0
    # iterate through base entries randomly to diversify
    pool = list(entries)
    random.shuffle(pool)

    while added < target and tries < target * 5:
        tries += 1
        src = random.choice(pool)
        q = (src.get('in') or '').strip()
        a = (src.get('out') or '').strip()
        if not q or is_blocked(q):
            continue
        variants = paraphrase_text(q, variants_per)
        for v in variants:
            if added >= target:
                break
            # skip if v looks blocked
            if is_blocked(v):
                continue
            # similarity to existing inputs
            too_similar = False
            for ex in base_inputs:
                if sim(v.lower(), (ex or '').lower()) > relax_dup_thresh:
                    too_similar = True
                    break
            if too_similar:
                # allow near-duplicates up to threshold, so only skip if very similar
                continue
            pair_key = v.strip().lower() + '|||' + a.strip().lower()
            if pair_key in existing:
                continue
            # append
            new_entry = {'in': v, 'out': a}
            data['entries'].append(new_entry)
            existing.add(pair_key)
            base_inputs.append(v)
            added += 1
        # end variants loop
    # end while
    save_memory(data)
    print(f'Added {added} new entries (target {target}). Total now: {len(data.get("entries",[]))}')


if __name__ == '__main__':
    tgt = 1000
    if len(sys.argv) > 1:
        try:
            tgt = int(sys.argv[1])
        except Exception:
            pass
    main(tgt, variants_per=3, relax_dup_thresh=0.95)
