"""
Static cross-check that cannot be done by py_compile:

  1. every `from app.x import name` actually exists in app/x.py
  2. every `settings.<attr>` reference exists on the Settings class / .env keys
  3. no fabricated-success patterns are left in the generate/publish paths

Runs purely on the AST, so it needs none of the third-party deps (the VM has no
network and cannot install fastapi/sqlalchemy/playwright).
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # project root, works on any machine
fails: list[str] = []

py_files = sorted(p for p in (ROOT / "app").rglob("*.py")) + \
           sorted(p for p in (ROOT / "scripts").rglob("*.py"))
trees = {p: ast.parse(p.read_text(encoding="utf-8"), filename=str(p)) for p in py_files}


def module_path(mod: str) -> Path | None:
    rel = Path(*mod.split(".")).with_suffix(".py")
    cand = ROOT / rel
    if cand.exists():
        return cand
    pkg = ROOT / Path(*mod.split(".")) / "__init__.py"
    return pkg if pkg.exists() else None


def toplevel_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    names.add(t.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for a in node.names:
                names.add(a.asname or a.name.split(".")[0])
        elif isinstance(node, (ast.If, ast.Try)):
            for sub in ast.walk(node):
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    names.add(sub.name)
                elif isinstance(sub, ast.Assign):
                    for t in sub.targets:
                        if isinstance(t, ast.Name):
                            names.add(t.id)
    return names


# ── 1. intra-project imports resolve ────────────────
checked = 0
for path, tree in trees.items():
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("app."):
            target = module_path(node.module)
            if target is None:
                fails.append(f"{path.name}: imports missing module {node.module}")
                continue
            available = toplevel_names(trees.get(target) or ast.parse(target.read_text(encoding='utf-8')))
            for alias in node.names:
                if alias.name == "*":
                    continue
                checked += 1
                if alias.name not in available and module_path(f"{node.module}.{alias.name}") is None:
                    fails.append(f"{path.name}: `from {node.module} import {alias.name}` — not defined there")
print(f"checked {checked} intra-project imported names")

# ── 2. settings.<attr> all exist ────────────────────
cfg_tree = trees[ROOT / "app" / "config.py"]
settings_attrs: set[str] = set()
for node in ast.walk(cfg_tree):
    if isinstance(node, ast.ClassDef):
        for item in node.body:
            if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                settings_attrs.add(item.target.id)
            elif isinstance(item, ast.Assign):
                for t in item.targets:
                    if isinstance(t, ast.Name):
                        settings_attrs.add(t.id)
            elif isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                settings_attrs.add(item.name)  # @property
used = 0
for path, tree in trees.items():
    for node in ast.walk(tree):
        if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                and node.value.id == "settings"):
            used += 1
            if node.attr not in settings_attrs:
                fails.append(f"{path.name}:{node.lineno}: settings.{node.attr} does not exist")
print(f"checked {used} settings.* references against {len(settings_attrs)} declared fields")

# ── 3. no fabricated-success patterns left ──────────
# Scan executable code only. Comments and docstrings legitimately *describe* the
# removed behaviour ("this used to fabricate a pin_live_<ts> record"), so a naive
# text grep flags its own changelog.
import io
import tokenize


def code_only_lines(text: str) -> dict[int, str]:
    """Source lines with comments and string literals blanked out."""
    lines = text.splitlines()
    blanked = {i + 1: list(line) for i, line in enumerate(lines)}
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except tokenize.TokenError:
        return {n: "".join(c) for n, c in blanked.items()}
    for tok in toks:
        if tok.type not in (tokenize.COMMENT, tokenize.STRING):
            continue
        (r1, c1), (r2, c2) = tok.start, tok.end
        for row in range(r1, r2 + 1):
            if row not in blanked:
                continue
            chars = blanked[row]
            start = c1 if row == r1 else 0
            end = c2 if row == r2 else len(chars)
            for i in range(start, min(end, len(chars))):
                chars[i] = " "
    return {n: "".join(c) for n, c in blanked.items()}


BAD = {
    "pin_live_": "synthesised Pinterest pin id",
    "(using fallback)": "silent fallback",
    'current_state = "PASS"': "writing PASS without running the critic",
    "🎃": "hardcoded seasonal content in app code",
    'lstrip("data/")': "lstrip strips characters, not the 'data/' prefix",
    "lstrip('data/')": "lstrip strips characters, not the 'data/' prefix",
}
scanned = 0
for path in sorted((ROOT / "app").rglob("*.py")):
    for lineno, line in code_only_lines(path.read_text(encoding="utf-8")).items():
        scanned += 1
        for needle, why in BAD.items():
            if needle in line:
                fails.append(f"{path.relative_to(ROOT)}:{lineno}: {why} -> {line.strip()[:90]}")
print(f"scanned {scanned} code lines for fabricated-success patterns")

# ── 4. fabricated string literals still deserve a look, but only where they are
# live values rather than docstrings describing the removed behaviour.
suspect_literals = (
    "pin_live_",
    "Look at this cute",
    "Seasonal Trends & Aesthetic Finds",
    "/pin/published-",  # the publisher used to synthesise this when a toast had no link
    "Aesthetic Product",
)
for path in sorted((ROOT / "app").rglob("*.py")):
    tree = trees[path]
    docstrings = set()
    for scope in ast.walk(tree):
        if isinstance(scope, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(scope, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                docstrings.add(id(body[0].value))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            for lit in suspect_literals:
                if lit in node.value:
                    fails.append(f"{path.relative_to(ROOT)}:{node.lineno}: live string literal {lit!r} in code")

print("\n" + "=" * 60)

# ── 5. the frontend can fabricate success too. No TS parser here, so this is a
# text scan that skips comment lines (the fixes deliberately document what they
# replaced, and that changelog must not trip its own check).
FRONTEND_BAD = {
    "Published to Pinterest live!": "success message not backed by a live_url",
    "Pin is now active": "success message printed without calling the API",
    "Seasonal Trends & Aesthetic Finds": "invented Pinterest board name",
    "Fall Halloween 2026": "hardcoded campaign in the UI",
    "🎃": "hardcoded seasonal content in the UI",
    "amzn.to/example": "fake affiliate link shown as if real",
    "'Halloween'": "hardcoded trend label default",
}
fe_scanned = 0
fe_root = ROOT / "frontend" / "src"
for path in sorted(fe_root.rglob("*.ts*")) if fe_root.is_dir() else []:
    in_block = False  # inside a /* ... */ or {/* ... */} comment, possibly multi-line
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = raw.strip()
        if in_block:
            if "*/" in stripped:
                in_block = False
            continue
        if stripped.startswith(("//",)):
            continue
        if stripped.startswith(("/*", "{/*")):
            if "*/" not in stripped:
                in_block = True
            continue
        fe_scanned += 1
        for needle, why in FRONTEND_BAD.items():
            if needle in raw:
                fails.append(f"{path.relative_to(ROOT)}:{lineno}: {why} -> {stripped[:90]}")
print(f"scanned {fe_scanned} frontend lines for fabricated-success patterns")

print("\nFAILURES:")
if fails:
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("  none")
