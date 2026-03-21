import sys
sys.path.append(r'C:\Users\User\Downloads')
from assistant_ai import AssistantAI

a = AssistantAI()
print(a.reply('merhaba'))
print(a.reply('nasılsın'))
a.learn('favori renk nedir', 'Benim renk tercihim kod satırlarının maviliği!')
a.save_memory()
print('memory before query:', a.semantic_memory)
print('reply for query:', a.reply('renk tercihin ne'))
print('semantic_available=', getattr(a, 'semantic_available', False))
