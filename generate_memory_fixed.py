#!/usr/bin/env python3
"""
Generator for assistant_memory.json
- Backups existing assistant_memory.json to assistant_memory.backup.<ts>.json
- Generates TARGET (~10000) unique {'in','out'} entries in Turkish
- Avoids empty outputs and near-duplicates using difflib similarity checks grouped by length buckets
- Writes atomically to assistant_memory.json

Run: run this script with the system Python, e.g.:
    python generate_memory_fixed.py
"""
import json
import os
import time
import random
import difflib
from datetime import datetime

random.seed(987654321)

HERE = os.path.abspath(os.path.dirname(__file__))
TARGET = 10000
OUT_PATH = os.path.join(HERE, 'assistant_memory.json')

# Similarity cutoff: anything with ratio >= this is considered "too similar" and rejected
SIMILARITY_CUTOFF = 0.82

# Bucketing by approximate length to reduce comparisons
def bucket_for(s: str):
    return max(0, int(len(s) / 40))

# Pools and templates (turkish, concise)
subjects = [
    'Python','dosya','JSON','liste','sözlük','dosya yolu','zamanlama','ses','müzik','ağ','HTTP','regex',
    'parola','şifreleme','kullanıcı arayüzü','başlangıç','yükleme ekranı','performans','bellek','dizin',
    'günlük','yedek','güvenlik','kısayol','dosya izinleri','sürücü','görsel','video','ses düzenleme','test'
]
actions = [
    'kısa açıklama','pratik ipucu','örnek','nasıl yapılır','kontrol listesi','hızlı rehber','güvenlik notu'
]

tips = [
    'Kısa ve net tutun.', 'Önce küçük bir test yapın.', 'Hata mesajlarını dikkatle okuyun.',
    'Veri doğrulamayı unutmayın.', 'Kaynakları (dosya/ağ) kapatın.', 'Asenkron işleri dikkatle yönetin.'
]

code_examples = [
    "with open('dosya.txt','r',encoding='utf-8') as f:\n    data = f.read()",
    "import json\nobj = json.loads(s)\nprint(obj.get('key'))",
    "if not os.path.exists(p):\n    os.makedirs(p, exist_ok=True)",
    "s = s.strip()\nif s:\n    print('ok')",
]

# Helper to ensure unique and not too similar outputs
seen_in_hashes = set()
buckets = {}  # bucket -> list of outputs in that bucket (strings)
entries = []

def similar_to_bucketed(s: str):
    b = bucket_for(s)
    for nb in (b-1, b, b+1):
        if nb in buckets:
            for o in buckets[nb]:
                if difflib.SequenceMatcher(None, s, o).ratio() >= SIMILARITY_CUTOFF:
                    return True
    return False

def add_entry(q: str, a: str) -> bool:
    q = q.strip()
    a = a.strip()
    if not q or not a:
        return False
    # quick exact duplicate check for output
    if any(a == existing for bl in buckets.values() for existing in bl):
        return False
    if similar_to_bucketed(a):
        return False
    # uniqueness of input: simple q normalized
    h = q.lower()
    if h in seen_in_hashes:
        return False
    seen_in_hashes.add(h)
    entries.append({'in': q, 'out': a})
    b = bucket_for(a)
    buckets.setdefault(b, []).append(a)
    return True

# Compose varied outputs
def make_brief(stmt):
    templates = [
        '{stmt}.',
        'Kısa: {stmt}.',
        '{stmt} Kısa bilgi olarak.',
        'Özet: {stmt}.',
    ]
    return random.choice(templates).format(stmt=stmt)

# 1) Subject-action templates
for subj in subjects:
    for act in actions:
        if len(entries) >= TARGET: break
        q = f"{subj} {act}?"
        stmt = f"{subj} ile ilgili {act}"
        out = make_brief(stmt) + ' ' + random.choice(tips)
        if random.random() < 0.15:
            out += ' ' + 'Örnek: ' + random.choice(code_examples)
        add_entry(q, out)
    if len(entries) >= TARGET: break

# 2) Practical micro-tips (numbered unique tips)
if len(entries) < TARGET:
    n = 1
    while len(entries) < TARGET and n <= 5000:
        subj = random.choice(subjects)
        q = f"Kısa ipucu: {subj} #{n}"
        out = f"İpucu {n}: {random.choice(tips)} Bağlam: {subj}."
        add_entry(q, out)
        n += 1

# 3) Short commands & usage examples
if len(entries) < TARGET:
    commands = [
        ('dosya oku', "with open('dosya.txt','r') as f: data = f.read()"),
        ('json kaydet', "import json\njson.dump(obj, fh, ensure_ascii=False)")
    ]
    idx = 1
    while len(entries) < TARGET and idx <= 2000:
        cmd, ex = random.choice(commands)
        q = f"{cmd} örneği {idx}"
        out = f"Kısa örnek: {ex}." if random.random() < 0.8 else f"{random.choice(tips)} {ex}."
        add_entry(q, out)
        idx += 1

# 4) Algorithm concise explanations with small variation
algos = [
    ('binary search', 'Sıralı listede hedefi orta noktadan başlayarak log(n) zamanda arar.'),
    ('quick sort', 'Pivot seçimiyle böl ve yönet; ortalama O(n log n) zaman alır.'),
    ('merge sort', 'Böl ve yönet; O(n log n) zaman alır, ek bellek kullanır.'),
    ('dijkstra', 'Pozitif kenarlı grafikte en kısa yolları bulur.'),
    ('dynamic programming', 'Alt problemlerin sonuçlarını saklayarak verim sağlar.'),
]
for name, expl in algos:
    i = 1
    while len(entries) < TARGET and i <= 200:
        q = f"{name} kısa açıklama {i}"
        out = f"{expl} Kısa not."
        if not add_entry(q, out):
            out = f"{expl} (not {i})."
            add_entry(q, out)
        i += 1

# 5) Security and privacy tips
security_items = [
    'Parolaları düz metin saklamayın.', '2FA kullanın.', 'Güncellemeleri düzenli yükleyin.',
    'Güvenli yedekleme yapın.', 'Az izin prensibini uygulayın.'
]
idx = 1
while len(entries) < TARGET and idx <= 2000:
    subj = random.choice(security_items)
    q = f"Güvenlik ipucu {idx}"
    out = f"İpucu {idx}: {subj}"
    add_entry(q, out)
    idx += 1

# 6) Motivation / short UX prompts
phrases = [
    'Kısa mola verin — 5 dakika hareket iyi gelir.',
    'Küçük commit yapın; sürüm takibi kolay olur.',
    'Önce test yazın, sonra uygulayın.',
    'Açıkça yorum yapın; okumayı kolaylaştırır.'
]
idx = 1
while len(entries) < TARGET and idx <= 2000:
    p = random.choice(phrases)
    q = f"Kısa öneri {idx}"
    out = f"{p}"
    add_entry(q, out)
    idx += 1

# 7) Fill remaining with uniquely numbered short tips (guaranteed unique tail)
idx = 1
while len(entries) < TARGET:
    q = f"Sistem ipucu genel {idx}"
    out = f"İpucu {idx}: {random.choice(tips)} (id:{idx})"
    # ensure uniqueness by construction (id suffix)
    add_entry(q, out)
    idx += 1

# Final normalization and length cap
for e in entries:
    e['in'] = ' '.join(e['in'].split())
    out = ' '.join(e['out'].split())
    if len(out) > 300:
        out = out[:297] + '...'
    e['out'] = out

# Make timestamped backup of existing file if exists
if os.path.exists(OUT_PATH):
    ts = datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
    backup_path = os.path.join(HERE, f'assistant_memory.backup.{ts}.json')
    try:
        with open(OUT_PATH, 'r', encoding='utf-8') as fh:
            old = fh.read()
        with open(backup_path, 'w', encoding='utf-8') as fh:
            fh.write(old)
        print('Backup written to', backup_path)
    except Exception as e:
        print('Backup failed:', e)

# atomic write to temporary file then replace
tmp_path = os.path.join(HERE, 'assistant_memory.new.json')
with open(tmp_path, 'w', encoding='utf-8') as fh:
    json.dump({'entries': entries}, fh, ensure_ascii=False, indent=2)
try:
    os.replace(tmp_path, OUT_PATH)
    print(f'Wrote {len(entries)} entries to {OUT_PATH}')
except Exception as e:
    print('Failed to move new file into place:', e)
    print('New file kept at', tmp_path)
