import sys
sys.path.append(r'C:\Users\User\Downloads')
from assistant_ai import AssistantAI

def run(target=2000):
    a = AssistantAI()
    initial = len(a.semantic_memory)
    added_total = 0
    attempt = 0
    # Keep trying until we reach target or no progress
    while added_total < target and attempt < 10:
        want = target - added_total
        added = a.generate_bulk_memory(want)
        print(f"attempt={attempt+1} requested={want} added={added}")
        if added <= 0:
            break
        added_total += added
        attempt += 1
    print(f"initial={initial} added_total={added_total} final={len(a.semantic_memory)}")

if __name__ == '__main__':
    run(2000)
