import ast

with open('backend/app/services/renderer.py') as f:
    tree = ast.parse(f.read())

funcs = [n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
slide_funcs = [f for f in funcs if 'slide' in f.lower() or 'image' in f.lower() or 'layout_mode' in f.lower()]
print("Slide-related functions:", slide_funcs)

# Check for the specific functions we added
expected = ['_resolve_slide_image', '_detect_layout_mode', '_render_slide_composited_clip']
for fn in expected:
    print(f"  {fn}: {'FOUND' if fn in funcs else 'MISSING'}")
