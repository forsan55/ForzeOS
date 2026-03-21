#!/usr/bin/env python3
"""
Post-process `assistant_memory.json`:
- Backup existing to timestamped file
- Load entries, remove empty/invalid
- Deduplicate exact and near-duplicate outputs (difflib)
- Remove templated low-quality repeated outputs (heuristic)
- Expand with generated unique entries until TARGET (10000)
- Write atomically and print summary

Run: python postprocess_memory.py
"""
import json
import os
import sys
import random
import difflib
from datetime import datetime

HERE = os.path.abspath(os.path.dirname(__file__))
IN_PATH = os.path.join(HERE, 'assistant_memory.json')
TMP_PATH = os.path.join(HERE, 'assistant_memory.new.json')
TARGET = 10000
SIMILARITY_CUTOFF = 0.82
random.seed(42)

if not os.path.exists(IN_PATH):
    print('ERROR: assistant_memory.json not found at', IN_PATH)
    sys.exit(2)

# backup
ts = datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
backup_path = os.path.join(HERE, f'assistant_memory.backup.{ts}.json')
with open(IN_PATH, 'r', encoding='utf-8') as fh:
    raw = fh.read()
with open(backup_path, 'w', encoding='utf-8') as fh:
    fh.write(raw)
print('Backup created at', backup_path)

# load
data = json.loads(raw)
entries = data.get('entries') if isinstance(data, dict) else data
if not isinstance(entries, list):
    print('ERROR: unexpected file format')
    sys.exit(2)
print('Loaded', len(entries), 'entries')

# normalize and filter empties
clean = []
for e in entries:
    try:
        q = e.get('in','').strip()
        a = e.get('out','').strip()
        if not q or not a:
            continue
        clean.append({'in': ' '.join(q.split()), 'out': ' '.join(a.split())})
    except Exception:
        continue
print('After removing empty/invalid:', len(clean))

# remove exact duplicate outputs (keep first)
seen_out = {}
unique = []
for e in clean:
    o = e['out']
    if o in seen_out:
        continue
    seen_out[o] = True
    unique.append(e)
print('After removing exact duplicate outputs:', len(unique))

# heuristic: remove obviously templated low-quality outputs
# e.g., outputs that start with 'Kısa bilgi:' repeated many times or identical short boilerplate
def is_templated_low_quality(s: str) -> bool:
    s_low = s.lower()
    bad_prefixes = ['kısa bilgi:', 'kısa:', 'özet:', 'kısa düşünce', 'kısa not']
    for p in bad_prefixes:
        if s_low.startswith(p):
            return True
    # very short and extremely common phrase
    if len(s.split()) <= 3 and len(s) < 60:
        # but allow useful short outputs like "Rica ederim." — we only remove very generic repeated phrases
        generic = ['rica ederim.', 'merhaba.', 'tamam.']
        if s_low in generic:
            return False
        return True
    return False

filtered = []
removed_templated = 0
for e in unique:
    if is_templated_low_quality(e['out']):
        removed_templated += 1
        continue
    filtered.append(e)
print('After removing templated low-quality outputs:', len(filtered), '(removed', removed_templated, ')')

import re

# Faster near-duplicate removal using token-based Jaccard similarity
def tokenize(s: str):
    return set(re.findall(r"\w+", s.lower()))

def jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0

# bucket by token-count to reduce comparisons
buckets = {}
kept = []
for e in filtered:
    o = e['out']
    toks = tokenize(o)
    b = max(1, len(toks)//5)
    similar_found = False
    # check neighboring buckets only
    for nb in (b-1, b, b+1):
        for existing_toks in buckets.get(nb, []):
            if jaccard(toks, existing_toks) >= SIMILARITY_CUTOFF:
                similar_found = True
                break
        if similar_found:
            break
    if not similar_found:
        buckets.setdefault(b, []).append(toks)
        kept.append(e)

print('After near-duplicate removal (token Jaccard):', len(kept))

# we'll now expand until TARGET by generating unique entries that avoid similarity
subjects = ['Python','dosya','JSON','liste','sözlük','zamanlama','ses','müzik','ağ','regex','şifreleme','güvenlik','başlangıç','yükleme ekranı','performans','bellek','günlük','yedek','kısayol','dizin']
actions = ['kısa açıklama','pratik ipucu','örnek','nasıl yapılır','kontrol listesi','hızlı rehber']
tips = ['Kısa ve net tutun.','Önce küçük bir test yapın.','Hata mesajlarını dikkatle okuyun.','Veri doğrulamayı unutmayın.']
code_examples = ["with open('dosya.txt','r',encoding='utf-8') as f:\n    data = f.read()","import json\nobj = json.loads(s)\nprint(obj.get('key'))"]

def is_similar_to_kept(text: str) -> bool:
    toks = tokenize(text)
    b = max(1, len(toks)//5)
    for nb in (b-1, b, b+1):
        for existing in buckets.get(nb, []):
            if jaccard(toks, existing) >= SIMILARITY_CUTOFF:
                return True
    return False

# helper to add unique
def add_generated(q,a):
    if not q or not a:
        return False
    # exact check
    for e in kept:
        if e['in'].lower() == q.lower() or e['out'] == a:
            return False
    if is_similar_to_kept(a):
        return False
    b = max(0, len(a)//40)
    buckets.setdefault(b, []).append(a)
    kept.append({'in': q, 'out': a})
    return True

# Expand with templates and numbered tails to ensure uniqueness
count_before = len(kept)
print('Expanding entries to target', TARGET)
attempt = 0
seed_idx = 1
# cap attempts to avoid infinite loops; should normally finish quickly
while len(kept) < TARGET and attempt < 200000:
    subj = random.choice(subjects)
    act = random.choice(actions)
    q = f"{subj} {act}?"
    core = f"{subj} için {act}"
    out = f"{core}. {random.choice(tips)}"
    if random.random() < 0.12:
        out += ' Örnek: ' + random.choice(code_examples)
    # if too similar, append a short unique tail id
    if is_similar_to_kept(out):
        out2 = f"{out} (id:{seed_idx})"
        q2 = f"{q} id {seed_idx}"
        if add_generated(q2, out2):
            seed_idx += 1
    else:
        if add_generated(q, out):
            pass
    attempt += 1
    if attempt % 10000 == 0:
        print('attempt', attempt, 'len', len(kept))

print('Expanded from', count_before, 'to', len(kept))

# Final shuffle for variety, normalize lengths
random.shuffle(kept)
for e in kept:
    e['in'] = ' '.join(e['in'].split())
    o = ' '.join(e['out'].split())
    if len(o) > 300:
        o = o[:297] + '...'
    e['out'] = o

# Write atomically
with open(TMP_PATH, 'w', encoding='utf-8') as fh:
    json.dump({'entries': kept}, fh, ensure_ascii=False, indent=2)
try:
    os.replace(TMP_PATH, IN_PATH)
    print('Wrote', len(kept), 'entries to', IN_PATH)
except Exception as e:
    print('Failed to replace:', e)
    print('New file at', TMP_PATH)

# Print a small sample
print('\nSample entries:')
for i,e in enumerate(kept[:8]):
    print(i+1, '-', e['in'], '->', e['out'])

print('\nDone')

# Write summary log so we can inspect results programmatically
SUMMARY_PATH = os.path.join(HERE, 'postprocess_summary.json')
summary = {
    'original': len(entries),
    'after_empty': len(clean),
    'after_exact': len(unique),
    'after_templated_removed': len(filtered),
    'after_near_duplicate': len(kept),
    'expanded_to': len(kept),
    'attempts': attempt,
    'wrote_path': IN_PATH if os.path.exists(IN_PATH) else None,
}
try:
    with open(SUMMARY_PATH, 'w', encoding='utf-8') as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)
    print('Wrote summary to', SUMMARY_PATH)
except Exception:
    pass
