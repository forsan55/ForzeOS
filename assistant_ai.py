"""assistant_ai.py

Modular offline assistant wrapper that prefers a high-quality memory JSON
(`assistant_memory_highq.json`) and falls back to `assistant_memory_large.json`.

Features:
- Loads high-quality memory if present.
- Uses rapidfuzz (if installed) for fast fuzzy matching; falls back to a simple
  hashed n-gram similarity when rapidfuzz isn't available.
- Exposes `reply(text, session_id=None)` and `execute_command(text, session_id=None)`.
- Non-destructive: does not delete or overwrite existing memory files.
"""
from __future__ import annotations
import json
import os
import time
import math
import random
import hashlib
from typing import List, Tuple, Optional

BASE_DIR = os.path.dirname(__file__)
HIGHQ = os.path.join(BASE_DIR, 'assistant_memory_highq.json')
LARGE = os.path.join(BASE_DIR, 'assistant_memory_large.json')

# Try to import rapidfuzz for semantic search; if unavailable, we'll fallback.
try:
    from rapidfuzz import process, fuzz  # type: ignore
    _RAPIDFUZZ = True
except Exception:
    _RAPIDFUZZ = False


def _load_json(path: str) -> List[str]:
    if not os.path.exists(path):
        return []
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, list):
                return [str(x) for x in data]
            return []
    except Exception:
        return []


class AssistantAI:
    def __init__(self, memory_file: Optional[str] = None, vector_dim: int = 256, ngram: int = 3):
        # Allow explicit override; otherwise prefer high-quality memory then large
        if memory_file:
            self.memory_path = memory_file
        elif os.path.exists(HIGHQ):
            self.memory_path = HIGHQ
        elif os.path.exists(LARGE):
            self.memory_path = LARGE
        else:
            self.memory_path = HIGHQ  # default path for future writes

        # Load both collections for fallback behavior
        self.highq = _load_json(HIGHQ)
        self.large = _load_json(LARGE)

        # Session bookkeeping to avoid repeating identical responses
        self.sessions = {}

        # Vectorization params used by fallback similarity
        self.vector_dim = vector_dim
        self.ngram = ngram

        # Precompute small hashed vectors for large memory for fast fallback scoring
        self._large_vectors = [self._vectorize(m) for m in self.large]

    # ----------------- small hashed n-gram vectorizer (fallback) -----------------
    def _hash_int(self, s: str) -> int:
        return int(hashlib.sha1(s.encode('utf-8')).hexdigest(), 16)

    def _vectorize(self, text: str) -> List[float]:
        v = [0.0] * self.vector_dim
        s = (text or '').lower()
        padded = ' ' + s + ' '
        L = len(padded)
        for i in range(max(0, L - self.ngram + 1)):
            gram = padded[i:i + self.ngram]
            h = self._hash_int(gram)
            idx = h % self.vector_dim
            v[idx] += 1.0
        norm = math.sqrt(sum(x * x for x in v))
        if norm > 0:
            v = [x / norm for x in v]
        return v

    def _dot(self, a: List[float], b: List[float]) -> float:
        return sum(x * y for x, y in zip(a, b))

    # ----------------- semantic search wrapper -----------------
    def find_best_memory(self, query: str, top_n: int = 1) -> List[Tuple[str, float, str]]:
        """Return list of (text, score, source) where source is 'highq' or 'large'.

        Uses rapidfuzz when available; otherwise uses simple vector dot-product on
        precomputed vectors (for large) and naive substring/overlap scoring for highq.
        """
        query = (query or '').strip()
        if not query:
            return []

        results: List[Tuple[str, float, str]] = []

        # Try high-quality memory first (rapidfuzz or substring-based)
        if self.highq:
            if _RAPIDFUZZ:
                # rapidfuzz can return score 0-100
                match = process.extract(query, self.highq, scorer=fuzz.partial_ratio, limit=top_n)
                for text, score, idx in match:
                    results.append((text, float(score) / 100.0, 'highq'))
            else:
                # simple heuristic: partial match score via substring presence + token overlap
                ql = query.lower()
                for text in self.highq:
                    tl = text.lower()
                    score = 0.0
                    if ql in tl or tl in ql:
                        score = 0.9
                    else:
                        q_tokens = set(ql.split())
                        t_tokens = set(tl.split())
                        if q_tokens:
                            overlap = len(q_tokens & t_tokens) / max(1, len(q_tokens))
                            score = overlap * 0.8
                    if score > 0:
                        results.append((text, score, 'highq'))

        # If we have rapidfuzz and results are strong, return early
        if results:
            # sort by score desc
            results.sort(key=lambda x: x[1], reverse=True)
            return results[:top_n]

        # Fallback: search large memory using vector similarity
        qv = self._vectorize(query)
        best = []
        for text, vec in zip(self.large, self._large_vectors):
            sc = self._dot(qv, vec)
            best.append((text, sc))
        best.sort(key=lambda x: x[1], reverse=True)
        for t, s in best[:top_n]:
            # convert raw dot (0..1) to a 0..1 like score
            results.append((t, float(max(0.0, s)), 'large'))
        return results

    # ----------------- Reply and command API -----------------
    def _ensure_session(self, session_id: Optional[str]) -> str:
        sid = session_id or '__default__'
        if sid not in self.sessions:
            self.sessions[sid] = {'recent': []}
        return sid

    def reply(self, text: str, session_id: Optional[str] = None) -> str:
        sid = self._ensure_session(session_id)
        # find best match
        cand = self.find_best_memory(text, top_n=3)
        reply_text = ''
        if cand:
            # pick highest scoring candidate but avoid recent repeats
            for t, score, src in cand:
                norm = ' '.join(t.split())
                if norm in self.sessions[sid]['recent']:
                    continue
                reply_text = t
                self.sessions[sid]['recent'].append(norm)
                # keep only last 12
                self.sessions[sid]['recent'] = self.sessions[sid]['recent'][-12:]
                break

        if not reply_text:
            # fallback reply when nothing found
            options = [
                "Bunu biraz daha açıklar mısın?",
                "İstersen bu konuda birkaç öneri sunabilirim.",
                "Hangi türde yardıma ihtiyacın var?"
            ]
            reply_text = random.choice(options)

        # lightweight postprocess: ensure sentence ends with punctuation
        if reply_text and reply_text[-1] not in '.!?':
            reply_text = reply_text.strip() + '.'

        return reply_text

    def execute_command(self, text: str, session_id: Optional[str] = None):
        # Simple detection: if user asked to open something, return (True, action)
        q = (text or '').lower()
        if 'open' in q or 'aç' in q or 'open' in q:
            # find likely app from hostable verbs
            # look for keywords in highq and large
            cand = self.find_best_memory(text, top_n=4)
            if cand:
                # naive mapping: return first candidate phrase and success True
                return True, cand[0][0]
        return False, ""


if __name__ == '__main__':
    a = AssistantAI()
    for q in ['merhaba', 'film öner', 'kod öğrenmek istiyorum', 'müzik aç']:
        print('Q:', q)
        print('A:', a.reply(q))
"""
assistant_ai.py

Lightweight offline assistant for ForzeOS companion.

Features:
- Eliza-like pattern responses (rule-based, no network required)
- Short-term session memory (last N messages)
- Simple utilities: enable/disable personality, set name

API:
    AssistantAI(session_size=20)
    reply(text, session_id=None) -> str
    remember(session_id, key, value)

This is intentionally small and dependency-free.
"""
from typing import Dict, List, Optional
import random
import re
import difflib


class AssistantAI:
    def __init__(self, session_size: int = 20, name: str = "Forzos"):
        # personality modes supported by the assistant
        # mizahi = humorous, ciddi = formal/serious, öğretici = teaching, arkadaş canlısı = friendly
        self.personality_modes = ["mizahi", "ciddi", "öğretici", "arkadaş canlısı"]
        # default personality (can be changed by host via config)
        self.personality = "mizahi"

        self.session_size = session_size
        self.name = name
        # session_id -> list of recent messages (tuples: ('user'/'bot', text))
        self.sessions: Dict[str, List[tuple]] = {}
        # simple pattern-response pairs (regex -> list of replies)
        self.patterns = [
            (r'\bhello\b|\bhi\b|\bhey\b', ["Merhaba! Nasıl yardımcı olabilirim?", "Selam! Bugün nasıl hissediyorsun?"]),
            (r'\bhow are you\b|\bnasilsin\b', ["İyiyim, teşekkürler. Sen nasılsın?", "Harika! Sana nasıl yardımcı olabilirim?"]),
            (r'\bname\b|\badın\b', [f"Ben {self.name}, senin küçük asistanın.", f"Adım {self.name}, memnun oldum."]),
            (r'\bhelp\b|\byardim\b', ["Tabii, ne hakkında yardım istersin?", "Hangi özellik hakkında bilgi almak istersin?"]),
            (r'\btime\b|\bsaat\b', ["Saat konusunda yardımcı olabilirim ama gerçek saat sistemiyle entegre değilim.", "Bilgiyi almak için sistemi sorgulayabilirim: 'saat kaç' diye sorabilirsin."]),
            (r'\bweather\b|\bhava\b', ["Hava durumunu internetten sorgulamadan tahmin edemem, ama sana yapısal bilgiler verebilirim.", "Doğrudan hava durumunu kontrol etmek için tarayıcıyı açabilirsin."]),
            (r'\bthank\b|\btesekkur\b', ["Rica ederim!", "Her zaman yardımcı olmaktan memnuniyet duyarım."]),
            (r'\bdisable ai\b|\bai off\b|\bai kapat\b|\bai kapatmak\b', ["AI modu kapatıldı." ]),
            (r'\benable ai\b|\bai on\b|\bai ac\b|\bai acmak\b', ["AI modu açıldı." ]),
        ]

        # Topics-based modules (collections of replies by topic)
        self.topics = {
            'chat': [
                "Günaydın! Bugün neler yapmayı planlıyorsun?",
                "Kısa bir mola iyi gelir — bir bardak su içmeyi düşünebilirsin.",
                "Yeni bir şey öğrendin mi bugün?"
            ],
            'jokes': [
                "Bilgisayar neden iyi bir müzisyen değil? Çünkü hep byte'lar çalıyor!",
                "İki programcı konuşuyormuş... 'Senin kodun neden böyle?' — 'Default olarak!'",
                "Neden klavye soğuktu? Çünkü Windows açıkmış."
            ],
            'teaching': [
                "Python'da değişkenler dinamik tiplidir; örn: x = 5, x şimdi int.",
                "for döngüsü: for i in range(5): işlem yapar — 0..4 arası iterasyon.",
                "Fonksiyon tanımlama: def foo(x): return x*2 — çağırınca sonucu alırsın."
            ],
            'tips': [
                "Gün içinde su içmeyi unutma — kısa hatırlatmalar performansı artırır.",
                "Küçük commit'ler yap — değişiklikleri takip etmek kolaylaşır.",
            ]
        }

        # Expanded datasets: jokes, trivia, motivational quotes, teaching topics, and a large pool of idle replies
        self.jokes = list(self.topics.get('jokes', [])) + [
            "Bir programcı karanlıkta neden mutludur? Çünkü ışığın açılıp kapanmasını kontrol eden kodu vardı!",
            "Neden bilgisayar denize girdi? Çünkü dalga yapmak istedi.",
            "İki bit konuşuyormuş, biri diğerine: 'Sen 0 mısın 1 misin?' diye sormuş. Baya ayrımcılık.",
            "Pek çok programcı kahve içer; çünkü 'çalıştır' butonu kahveyle daha hızlı basılıyor gibi geliyor.",
            "Debugging: Kod çalışıyor ama nedenini açıklayamıyorsun. İşte sihir!"
        ]

        self.trivia = [
            "İnsan beyni yaklaşık olarak 1.3 kg ağırlığındadır.",
            "Python adı Monty Python'dan ilham alır, yılanla ilgili değildir.",
            "İlk bilgisayar programcısı Ada Lovelace olarak kabul edilir.",
            "Dünyanın en eski programlama dili Fortran'dır (1950'ler).",
        ]

        self.motivational_quotes = [
            "Küçük adımlar bile ilerlemedir.",
            "Hata yapmak öğrenmenin bir parçasıdır.",
            "Azim, yetenekten daha fazlasını başarmaya yardımcı olur.",
        ]

        # teaching topics: short, bite-sized learning snippets
        self.teaching_topics = list(self.topics.get('teaching', [])) + [
            "Değişkenler: x = 10, x artık bir sayıdır ve matematikte kullanabilirsin.",
            "Listeler: mylist = [1,2,3], mylist.append(4) ile eleman ekleyebilirsin.",
            "Sözlükler: d = {'a':1}, d['a'] ile değere ulaşılır.",
            "Fonksiyon: def add(a,b): return a+b — tekrar kullanabilirsin.",
            "Dosya açma: with open('dosya.txt') as f: data = f.read() — güvenli yol budur.",
            "Hata yakalama: try/except bloğu ile beklenmeyen hataları kontrol et.",
            "Algoritma ipucu: Binary search, sıralı listede log(n) zamanda arama yapar.",
            "Güvenlik: Parolaları düz metin olarak saklama, hash fonksiyonları kullan.",
        ]

        # a large pool of idle replies (100+ short lines). Mix of jokes, small comments, prompts.
        self.random_idle_replies = [
            "Merhaba! Bir mola vermek iyi gelebilir.",
            "Küçük bir ipucu: sık sık kaydetmek işleri kurtarır.",
            "Şaka zamanı: Bilgisayar neden köpekle iyi anlaşır? Çünkü komutları iyi anlar!",
            "Bugün yeni bir şey öğrendin mi?",
            "Koduna kısa bir göz atmak ister misin?",
            "Bir kahve molası öneririm.",
            "Hava nasıl orada? Ben sadece hayal edebiliyorum.",
            "Kısa bir esneme iyi gelebilir.",
            "Unutma: küçük commit'ler büyük fark yaratır.",
            "Bazen en iyi çözüm basit olandır.",
            "Harflerin dansını görmek ister misin? Kod yaz!",
            "Haydi bir kısa görev yapalım: open gallery yaz.",
            "Günaydın! Yeni bir gün, yeni fırsatlar.",
            "Mizah modu: 'merge' yapılınca herkes barışırmış.",
            "Bilgi: Python listeleri dinamik olarak büyür.",
            "Kendine ufak hedefler belirle; gün daha verimli geçer.",
            "Şaka: Klavye neden hızlı? Çünkü tuşlara basınca hızlanıyor.",
            "Trivia: İlk bilgisayar mühendisi kadın Ada Lovelace'tir.",
            "İpucu: Dosyaları yedeklemeyi unutma.",
            "Motivasyon: Küçük adımlar, büyük sonuçlar getirir.",
            "Bazen ekran kararmadan önce bir kahve içmek en iyisidir.",
            "Bugün bir şeyler düzenlemeye ne dersin?",
            "Kısa kod tüyosu: Fonksiyonlar tekrar kullanım için mükemmeldir.",
            "Şaka: if (coffee) { code(); } else { sleep(); }",
            "Günün önerisi: 5 dakika göz dinlendirme.",
            "Meraklı bir soru: En son hangi kitabı okudun?",
            "Basit bir fikir: TODO listesi yap, sonra uygulamaya başla.",
            "Kodunla gurur duy — her hata bir ders demektir.",
            "Trivia: Python adı bir komedi grubundan gelir.",
            "Kısa bir öneri: Otomatik testler işini kolaylaştırır.",
            "Gülümse — bilgisayar hissetmese bile moralin yükselir.",
            "Şaka: Programcı neden gülmez? Çünkü her şey try/except içinde.",
            "Biraz müzik iyi gider — open music demeyi unutma.",
            "Tükenmişlik hissediyorsan kısa bir yürüyüş yap.",
            "Kısaca: Yedekle, test et, commit yap.",
            "Haydi minik bir hedef: 10 dakikada bir küçük ilerleme kaydet.",
            "Bilgisayar bilimi trivia: 'Hello, World!' ilk programdır.",
            "Motivasyon: Denemekten vazgeçme.",
            "Şaka: 'Segmentation fault' aslında ciddi bir şaka değil.",
            "Günün ipucu: Kod okunaklı olsun — gelecekteki sen teşekkür eder.",
            "Pahalı olmayan mutluluk: kodun çalıştığında yüzüne gelen gülümseme.",
            "Ufak not: Klavye kısayolları hız kazandırır.",
            "Trivia: İlk bilgisayar odası çok büyükmüş.",
            "Müşfik tavsiye: Ara sıra mola ver.",
            "Kestirme yol: Kodunu modüllere ayır.",
            "Şaka: Yazılım mühendisliği bir sanattır — ama hata ayıklamak da öyle.",
            "Kısa bilgi: Git branşları iş akışını kolaylaştırır.",
            "Motivasyon: Bugün bir şeyleri iyileştir.",
            "Kod yazarken açıklayıcı değişken isimleri kullan.",
            "Bazen en iyi optimizasyon, daha az kod yazmaktır.",
            "Şaka: 'Null' ile karşılaşınca bağırma, onu kucakla.",
            "Mini-ödev: Bugün 15 dakika yeni bir şey öğren.",
            "Günün tüyosu: README dosyası yararlı olmalı.",
            "Trivia: Bilgisayarlar ikili sayı sistemini sever.",
            "Motivasyon: Hatalar başarının bir parçasıdır.",
            "Kısa molalar üretkenliği artırır.",
            "Şaka: Loop'lar sonsuz olunca üzülürler.",
            "Küçük alışkanlıklar büyük etkiler yaratır.",
            "İyi bir commit mesajı gelecekte hayat kurtarır.",
            "Trivia: 'Bug' terimi eskiden gerçek böceklerden geliyor.",
            "Mizah: Bilgisayar neden şarkı söylemedi? Çünkü hiç ritmi yoktu.",
            "Günün planı: Bir şeyi bitir — küçük de olsa.",
            "İpucu: Otomasyon tekrarı azaltır.",
            "Şimdi kısa bir nefes al — 3 derin nefes yeter.",
            "Motivasyon: Yavaş ilerlemek de ilerlemektir.",
            "Kısaca: Read, Run, Repeat.",
            "Trivia: İlk programcı makine için notlar yazmış.",
            "Şaka: Dokümantasyon yazmayan programcı hayal kurar.",
            "Günün önerisi: Küçük hedefler belirle.",
            "Kısa hatırlatma: Otomatik testleri unutma.",
            "Mizahi not: Eğer hata bulamıyorsan, kahveni kontrol et.",
            "Trivia: Bilgisayar bilimi hızlı gelişiyor — takip et.",
            "Motivasyon: Denemeden öğrenmek zordur.",
            "Günlük mini hedeftir: 20 dakika yeni bir şey öğren.",
            "Şaka: Kod yazmak bazen bir şiir gibidir.",
            "Not: Kendine nazik ol — kodlamada herkes hata yapar.",
            "Kısa: 'print' ile başla, sonra büyü.",
            "Şaka: Eğer hata veriyorsa, 'print' ekle — her şey çözülür (çoğu zaman).",
            "Motivasyon: Bugün küçük bir başarı kutla.",
            "Trivia: Bilgisayarlar karmaşık ama onlar için basitleştirebilirsin.",
            "Kahve molası için zaman ayır — enerji gelir.",
            "Ufak bir oyun: Yeni bir kısayol öğren.",
            "Günün sözleri: İstikrar, başarı getirir.",
        ]

        # Long-term notes about the user (persistent in memory; host may choose to persist)
        self.long_term_notes: List[str] = []
        # External commands added by the host application (e.g., ForzeOS Companion)
        self.external_commands: List[str] = []

    def _ensure_session(self, session_id: Optional[str]):
        sid = session_id or 'default'
        if sid not in self.sessions:
            self.sessions[sid] = []
        return sid

    def remember(self, session_id: Optional[str], key: str, value: str):
        sid = self._ensure_session(session_id)
        self.sessions[sid].append(('mem:'+key, value))
        # trim
        if len(self.sessions[sid]) > self.session_size:
            self.sessions[sid] = self.sessions[sid][-self.session_size:]

    def _add_message(self, session_id: str, who: str, text: str):
        self.sessions.setdefault(session_id, [])
        self.sessions[session_id].append((who, text))
        if len(self.sessions[session_id]) > self.session_size:
            self.sessions[session_id] = self.sessions[session_id][-self.session_size:]

    def reply(self, text: str, session_id: Optional[str] = None) -> str:
        """Produce a reply for `text`. Purely local and rule-based."""
        sid = self._ensure_session(session_id)
        txt = text.strip().lower()
        # record user message
        self._add_message(sid, 'user', text)
        # keep light long-term notes about simple user actions
        try:
            if 'open' in txt or 'aç' in txt or 'open' in text.lower():
                self.add_long_term_note(f"user_opened:{txt}")
        except Exception:
            pass

        # Explicit help handler: provide a comprehensive, Turkish help text
        if re.search(r'\bhelp\b|\byardim\b', txt, flags=re.IGNORECASE):
            lines = [
                "Yardım — Assistant AI Komut Listesi:",
                "- Temel komutlar: hello, how are you, name, help, time, weather, thank",
                "- Komutlar: joke, teach, motivate, function art (open function art)",
                "- AI açma/kapatma: 'enable ai' / 'disable ai'",
                "",
                "Companion / Host tarafından eklenen komutlar:",
            ]
            if self.external_commands:
                for c in sorted(self.external_commands):
                    lines.append(f"- {c}")
            else:
                lines.append("(Hiç ek komut yok)")
            lines += [
                "",
                "Function ART (fonksiyon penceresi) kullanımı:",
                "- Tekil fonksiyon: f(t) = <ifade> örn: math.sin(t) veya math.sin(3*t) + 0.2*math.sin(5*t)",
                "- Parametrik (x(t); y(t)): Giriş kutusuna 'x_expr; y_expr' yazın, örn: math.cos(t); math.sin(2*t)",
                "- İzin verilen isimler: math (mutlaka), abs, min, max, np (eğer numpy yüklüyse), t değişkeni",
                "- Şablonlar: Sin, Circle, Lissajous, Spiral, Heart — Companion içinden veya Function ART düğmeleriyle ekleyin",
                "- Örnekler:",
                "  f(t): math.sin(t)",
                "  param: math.cos(t); math.sin(2*t)",
                "",
                "Daha spesifik yardım için 'help <komut>' yazabilirsiniz."
            ]
            resp = "\n".join(lines)
            self._add_message(sid, 'bot', resp)
            return resp

        # quick exact matches
        if txt in ('hi', 'hello', 'merhaba'):
            resp = random.choice(["Merhaba!", "Selam!"])
            self._add_message(sid, 'bot', resp)
            return resp

        # pattern matching
        for pat, replies in self.patterns:
            if re.search(pat, txt, flags=re.IGNORECASE):
                resp = random.choice(replies)
                self._add_message(sid, 'bot', resp)
                return resp

        # fuzzy understanding: try to match user text to known commands/keywords
        try:
            handled, resp = self._fuzzy_understand(text)
            if handled:
                self._add_message(sid, 'bot', resp)
                return resp
        except Exception:
            pass

        # If the user asked for teaching (match keywords), return a teaching topic
        if re.search(r'\bteach\b|\böğret\b|\böğretme\b|\böğretir misin\b', txt, flags=re.IGNORECASE):
            resp = random.choice(self.teaching_topics if self.teaching_topics else self.topics.get('teaching', []))
            self._add_message(sid, 'bot', resp)
            return resp

        # If the user asked for a joke or wants humor, return a joke
        if re.search(r'\bjoke\b|\bmizah\b|\bşaka\b', txt, flags=re.IGNORECASE):
            resp = random.choice(self.topics.get('jokes', []))
            self._add_message(sid, 'bot', resp)
            return resp

        # Use short-term context: if last user asked about thanks
        history = [m for who, m in self.sessions.get(sid, []) if who == 'user']
        last = history[-1] if history else ''
        if 'thank' in last or 'tesekkur' in last:
            resp = "Rica ederim! Başka bir şey?"
            self._add_message(sid, 'bot', resp)
            return resp
        # Default fallback - try to provide teaching topic or a joke or a generic fallback
        # 1) Occasionally encourage learning by offering a teaching topic
        if random.random() < 0.25 and self.topics.get('teaching'):
            resp = random.choice(self.topics['teaching'])
            self._add_message(sid, 'bot', resp)
            return resp

        # 2) Provide a light joke sometimes
        if random.random() < 0.3 and (self.jokes or self.topics.get('jokes')):
            resp = random.choice(self.jokes if self.jokes else self.topics.get('jokes'))
            self._add_message(sid, 'bot', resp)
            return resp

        # 3) generic fallback
        fallbacks = [
            "Bunu daha iyi anlamak için biraz daha bilgi verir misin?",
            "İlginç. Daha fazla detay verir misin?",
            "Hemen yardımcı olmak isterim, biraz daha açıklar mısın?",
        ]
        resp = random.choice(fallbacks)
        self._add_message(sid, 'bot', resp)
        return resp

    def _fuzzy_understand(self, text: str):
        """Try to interpret user text by fuzzy-matching against known commands and keywords.

        Returns (handled: bool, response: str). If handled is True, caller should use response.
        """
        txt = (text or '').strip()
        if not txt:
            return False, ''
        # build candidate list: known short commands + external commands + small affirmatives
        candidates = []
        try:
            # patterns -> take literal words from regex patterns if simple
            for pat, _ in self.patterns:
                # remove regex tokens and take words
                s = re.sub(r'\\b|\\s|\W+', ' ', pat)
                for w in s.split():
                    if len(w) > 2:
                        candidates.append(w.lower())
        except Exception:
            pass
        try:
            candidates.extend([c.lower() for c in (self.external_commands or [])])
        except Exception:
            pass
        # common small words
        candidates.extend(['yes', 'no', 'evet', 'hayır', 'tamam', 'ok', 'help', 'yardim', 'joke', 'şaka', 'draw', 'çiz'])

        # use difflib to find best matches
        best = difflib.get_close_matches(txt.lower(), candidates, n=1, cutoff=0.7)
        if best:
            match = best[0]
            # if match looks like a host/external command, return a descriptive response
            if match in (c.lower() for c in (self.external_commands or [])):
                return True, f"Algıladım: '{match}' komutu mevcuttur; çalıştırmak için Companion'e söyleyebilirsin."
            if match in ('help', 'yardim'):
                return True, self.reply('help')
            if match in ('joke', 'şaka'):
                return True, random.choice(self.jokes or ["Bir şaka söyleyemiyorum şimdi."])
            if match in ('yes', 'evet', 'tamam', 'ok'):
                return True, "Tamam — nasıl yardımcı olayım?"
            if match in ('no', 'hayır'):
                return True, "Anladım — başka bir şey denemek ister misin?"

        # also check token-level fuzzy match for short words inside the text
        words = re.findall(r"\w{3,}", txt.lower())
        for w in words:
            bm = difflib.get_close_matches(w, candidates, n=1, cutoff=0.85)
            if bm:
                m = bm[0]
                if m in (c.lower() for c in (self.external_commands or [])):
                    return True, f"Görünüyor ki '{m}' demek istediniz; Companion üzerinden çalıştırılabilir."
        return False, ''

    def random_idle_reply(self) -> str:
        """Return a short idle reply from chat/tips/jokes to be shown occasionally by the companion."""
        # choose content based on personality: mizahi -> jokes, öğretici -> teaching_topics, ciddi -> tips/trivia, arkadaş canlısı -> chat/motivational
        pool = []
        p = (self.personality or 'mizahi').lower()
        try:
            if p == 'mizahi':
                pool.extend(self.jokes)
                pool.extend(self.random_idle_replies[:40])
            elif p == 'öğretici' or p == 'ogretici':
                pool.extend(self.teaching_topics)
                pool.extend(self.trivia)
            elif p == 'ciddi':
                pool.extend(self.trivia)
                pool.extend(self.motivational_quotes)
                pool.extend(self.topics.get('tips', []))
            else:  # arkadaş canlısı or default
                pool.extend(self.topics.get('chat', []))
                pool.extend(self.motivational_quotes)
                pool.extend(self.random_idle_replies[:40])
        except Exception:
            pass
        # always add a few generic idle replies
        try:
            pool.extend(self.random_idle_replies[-20:])
        except Exception:
            pass
        if not pool:
            return "Hmm, bir şeyler dene — belki bir komut?"
        return random.choice(pool)

    def add_long_term_note(self, note: str):
        try:
            if not note:
                return
            self.long_term_notes.append(note)
            # keep it bounded
            if len(self.long_term_notes) > 200:
                self.long_term_notes = self.long_term_notes[-200:]
        except Exception:
            pass

    def get_long_term_notes(self) -> List[str]:
        return list(self.long_term_notes)

    def execute_command(self, text: str, session_id: Optional[str] = None):
        """Try to recognize and execute a small set of higher-level commands.

        Returns a tuple (handled: bool, result_text: str).
        If not handled, callers should fall back to reply().
        """
        try:
            sid = self._ensure_session(session_id)
            txt = (text or '').strip().lower()
            # simple command handlers
            if re.search(r'\bjoke\b|\bşaka\b', txt, flags=re.IGNORECASE):
                resp = random.choice(self.jokes) if self.jokes else "Bir şaka söyleyemiyorum şimdi."
                self._add_message(sid, 'bot', resp)
                return True, resp

            if re.search(r'\bteach python\b|\bteach\b|\böğret\b', txt, flags=re.IGNORECASE):
                topic = random.choice(self.teaching_topics) if self.teaching_topics else "Küçük bir Python dersi: print('Hello')"
                self._add_message(sid, 'bot', topic)
                return True, topic

            if re.search(r'\bmotivate\b|\bmotivate me\b|\bmotivasyon\b|\bmotivate me\b', txt, flags=re.IGNORECASE):
                q = random.choice(self.motivational_quotes) if self.motivational_quotes else "Devam et, yapabilirsin!"
                self._add_message(sid, 'bot', q)
                return True, q

            if re.search(r'function art|open function art|open functionart', txt, flags=re.IGNORECASE):
                resp = "Açıyorum: Function ART penceresi..."
                self._add_message(sid, 'bot', resp)
                return True, resp

            # quick draw commands that open Function ART with prefilled expressions
            if re.search(r'\bdraw circle\b|\bçiz daire\b', txt, flags=re.IGNORECASE):
                expr = 'math.cos(t); math.sin(t)'
                return True, f'OPEN_FUNCART:::{expr}'
            if re.search(r'\bdraw lissajous\b|\bçiz lissajous\b', txt, flags=re.IGNORECASE):
                expr = 'math.cos(3*t); math.sin(4*t)'
                return True, f'OPEN_FUNCART:::{expr}'
            if re.search(r'\bdraw spiral\b|\bçiz spiral\b', txt, flags=re.IGNORECASE):
                expr = 't*math.cos(t); t*math.sin(t)'
                return True, f'OPEN_FUNCART:::{expr}'
            if re.search(r'\bdraw heart\b|\bçiz kalp\b', txt, flags=re.IGNORECASE):
                expr = '16*math.sin(t)**3; 13*math.cos(t)-5*math.cos(2*t)-2*math.cos(3*t)-math.cos(4*t)'
                return True, f'OPEN_FUNCART:::{expr}'

            # unknown to this executor
            return False, ''
        except Exception:
            try:
                return False, ''
            except Exception:
                return False, ''


if __name__ == '__main__':
    a = AssistantAI()
    print(a.reply('Hello'))
    print(a.reply('How are you?'))
    print(a.reply('Tell me your name'))
