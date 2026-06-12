import sys
p=r'c:\Users\User\Downloads\ForzeOS System.py'
with open(p,'r',encoding='utf-8') as f:
    lines=f.readlines()
start=1190-1
end=1226
for i in range(start,end):
    if i < len(lines):
        print(f"{i+1}: {lines[i].rstrip()}\nREPR: {repr(lines[i])}")
    else:
        print(f"{i+1}: <no line>")
