"""hybrid_assistant.py

Hybrid assistant that combines a primary EnhancedAssistantAI (richer
session/profile behaviour) with a secondary lightweight pattern engine
(assistant_ai AssistantAI) for greetings, jokes and short teaching snippets.

Design notes:
- Prefer the primary (EnhancedAssistantAI) when it produces a non-random
  response. Otherwise fall back to the secondary pattern engine.
- Filter obvious debugging/teaching/snippet noise from the secondary engine
  using a small banned-list heuristic.
"""
from typing import Optional
import logging

logger = logging.getLogger(__name__)

# Try to import the richer embedded assistant implementation (offline)
EnhancedAssistantAI = None
try:
    # prefer the local offline enhanced assistant module if present
    import assistant_ai_offline as _a_off
    EnhancedAssistantAI = getattr(_a_off, 'EnhancedAssistantAI', None)
except Exception:
    EnhancedAssistantAI = None

# Secondary pattern engine (kept as-is; we only filter its noisy outputs)
LightweightAI = None
try:
    import assistant_ai as _ai
    LightweightAI = getattr(_ai, 'AssistantAI', None)
except Exception:
    LightweightAI = None


class HybridAssistantAI:
    def __init__(self, primary_args: Optional[dict] = None, secondary_args: Optional[dict] = None):
        primary_args = primary_args or {}
        secondary_args = secondary_args or {}

        # instantiate primary (EnhancedAssistantAI) if available
        self.primary = None
        if EnhancedAssistantAI:
            try:
                self.primary = EnhancedAssistantAI(**primary_args)
            except Exception:
                logger.exception('hybrid: failed to instantiate EnhancedAssistantAI')
                self.primary = None

        # instantiate secondary (AssistantAI) if available
        self.secondary = None
        if LightweightAI:
            try:
                self.secondary = LightweightAI(**(secondary_args or {}))
            except Exception:
                logger.exception('hybrid: failed to instantiate AssistantAI')
                self.secondary = None
        # lightweight persistent storage for small profile pieces (safest and
        # independent of primary implementation details). Stored next to this
        # module so it survives restarts.
        try:
            import os
            here = os.path.dirname(__file__)
            self._persist_path = os.path.join(here, 'hybrid_profiles.json')
        except Exception:
            self._persist_path = 'hybrid_profiles.json'

        # load persisted profiles
        self.sessions = {}
        try:
            import json
            if os.path.exists(self._persist_path):
                with open(self._persist_path, 'r', encoding='utf-8') as fh:
                    data = json.load(fh)
                    if isinstance(data, dict):
                        self.sessions = data
        except Exception:
            self.sessions = {}

    def reply(self, text: str, session_id: Optional[str] = None) -> str:
        sid = session_id or '__default__'
        # ensure session profile container exists
        if sid not in self.sessions:
            self.sessions[sid] = {'profile': {}}

        # name-declaration detection: if user tells their name, save immediately
        try:
            import re
            m = None
            txt = (text or '').strip()
            # English patterns
            m = re.search(r"\bmy name is\s+([A-Za-zÀ-ÖØ-öø-ÿ'\-\s]{1,40})\b", txt, re.I)
            if not m:
                m = re.search(r"\bi am\s+([A-Za-zÀ-ÖØ-öø-ÿ'\-\s]{1,40})\b", txt, re.I)
            # Turkish patterns
            if not m:
                m = re.search(r"\bbenim ad[iı]\s+([A-Za-zÇÖŞİÜĞçöşıüğ'\-\s]{1,40})\b", txt, re.I)
            if not m:
                m = re.search(r"\bad[iı]m\s+([A-Za-zÇÖŞİÜĞçöşıüğ'\-\s]{1,40})\b", txt, re.I)
            if m:
                name = m.group(1).strip()
                if name:
                    # save into hybrid sessions and try to mirror into primary
                    self.sessions.setdefault(sid, {}).setdefault('profile', {})['name'] = name
                    # persist
                    try:
                        import json, os
                        with open(self._persist_path + '.tmp', 'w', encoding='utf-8') as fh:
                            json.dump(self.sessions, fh, ensure_ascii=False, indent=2)
                        try:
                            os.replace(self._persist_path + '.tmp', self._persist_path)
                        except Exception:
                            import shutil
                            shutil.move(self._persist_path + '.tmp', self._persist_path)
                    except Exception:
                        pass
                    # mirror into primary if possible
                    try:
                        if self.primary and hasattr(self.primary, 'sessions'):
                            ps = self.primary.sessions.setdefault(sid, {})
                            ps.setdefault('profile', {})['name'] = name
                    except Exception:
                        pass
                    return f"Tamam, {name}. Bundan sonra seni {name} diye çağıracağım."
        except Exception:
            pass
        # Try primary first
        primary_reply = ''
        try:
            if self.primary:
                primary_reply = (self.primary.reply(text, session_id) or '').strip()
        except Exception:
            primary_reply = ''

        # If the user asked for their name, handle via hybrid persistent store
        try:
            low = (text or '').lower()
            import re
            if re.search(r"\b(what is my name|who am i)\b", low) or re.search(r"\b(ad[iı]m ne|ben kimim|benim ad[iı]m ne)\b", low):
                name = self.sessions.get(sid, {}).get('profile', {}).get('name')
                if name:
                    return f"Senin adın {name}."
                else:
                    return "Adını bilmiyorum — bana adını söyleyebilirsin. Örneğin: 'Benim adım Ahmet'."
        except Exception:
            pass

        if primary_reply and not self._looks_random(primary_reply):
            return primary_reply

        # Primary didn't give a usable answer; try the secondary (pattern) engine
        try:
            if self.secondary:
                sec = (self.secondary.reply(text, session_id) or '').strip()
            else:
                sec = ''
        except Exception:
            sec = ''

        if not sec or self._looks_random(sec):
            return "Bunu tam anlamadım, biraz daha açabilir misin?"
        return sec

    def execute_command(self, text: str, session_id: Optional[str] = None):
        # Prefer primary execute_command semantics; fall back to secondary
        try:
            if self.primary and hasattr(self.primary, 'execute_command'):
                try:
                    r = self.primary.execute_command(text, session_id)
                    if r:
                        return r
                except Exception:
                    pass
        except Exception:
            pass

        try:
            if self.secondary and hasattr(self.secondary, 'execute_command'):
                try:
                    return self.secondary.execute_command(text, session_id)
                except Exception:
                    pass
        except Exception:
            pass
        return None

    def _looks_random(self, text: str) -> bool:
        if not text:
            return True
        banned = [
            "Debugging:", "for döngüsü:", "İnsan beyni",
            "Küçük bir ipucu:", "Bugün yeni bir şey öğrendin mi",
        ]
        tl = text.lower()
        for b in banned:
            if b.lower() in tl:
                return True
        # also filter extremely short single-word outputs that look non-informative
        if len(text.strip()) < 3:
            return True
        return False


if __name__ == '__main__':
    h = HybridAssistantAI()
    print(h.reply('merhaba'))
    print(h.reply('benim adım Ahmet'))
