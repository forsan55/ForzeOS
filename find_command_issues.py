import ast
from pathlib import Path
p=Path(r"C:/Users/User/Downloads/ForzeOS System.py")
s=p.read_text(encoding='utf-8')
issues=[]
class Visitor(ast.NodeVisitor):
    def visit_Call(self,node):
        # check keywords
        for kw in node.keywords:
            if kw.arg=='command':
                val=kw.value
                if isinstance(val, ast.Constant):
                    issues.append((node.lineno, ast.dump(val)))
                elif isinstance(val, ast.Name):
                    # could be variable; record name
                    issues.append((node.lineno, 'NAME:'+val.id))
                elif isinstance(val, ast.Lambda):
                    pass
                elif isinstance(val, ast.Call):
                    # command=make_cmd(...) pattern -- it's a call returning a callable; mark as maybe ok
                    issues.append((node.lineno, 'CALL:'+ast.dump(val.func)))
                else:
                    issues.append((node.lineno, type(val).__name__))
        self.generic_visit(node)

Visitor().visit(ast.parse(s))
for lineno,desc in issues:
    print(lineno, desc)
print('done')
