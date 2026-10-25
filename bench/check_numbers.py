"""DoD #4: zero unbacked numbers in README / paper / resume bullets / final review.

Every result number must come from a claim (bench/claims.py) via a `{{id}}` placeholder (Markdown templates in
docs/*.md.in) or `\\claim{id}` (paper). Any other numeric literal must match the STRUCTURAL allowlist (distances,
milestone ids, years, tool/standard names, small counting integers, ...). Exits non-zero listing offenders.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bench import claims  # noqa: E402

NUM = re.compile(r"(?<![A-Za-z_\\])[-+]?\d+(?:[.,]\d+)*(?:[eE][-+]?\d+)?%?")
STRUCTURAL = [
    r"\bd\s*[=∈]\s*\{?[\d, ]+\}?", r"\bd\s*≤\s*\d+", r"\bM\d+\b", r"\b(?:19|20)\d\d\b", r"\bv?\d+\.\d+(?:\.\d+)+\b",
    r"LFE5U-\d+F", r"CABGA\d+", r"SIMD\d+", r"AES-\d+", r"Ed\d+", r"X\d+", r"SHA-\d+", r"TLS\s*1\.3", r"ECP\d",
    r"iCE\d+", r"Artix-\d", r"\bP\d\b", r"\bC\d\b", r"\bI\d\b", r"\bD\d\b", r"\bB\d\b", r"2\^\d+", r"\b[0-9]-bit",
    r"\b(?:32|64)-bit", r"\bfloat\d+", r"\buint\d+", r"\bint\d+", r"\bq\d+(?:m\d+)?\b", r"\bp\s*=\s*0\.00[1-9]\b",
    r"\bK\s*=\s*\d\b", r"\bN\s*=\s*\d\b", r"\bL\s*=\s*\d\b", r"\bLANES\$?\s*=\s*\$?\d+\b", r"\bPIPE\s*=\s*\d\b",
    r"\b\d+\s*(?:rounds?|layers?|sites?|lanes?)\b", r"arm64|x86[_-]64|aarch64", r"\b10\^\d\b|10⁶|10⁵",
    r"\bNBUF\s*=\s*\d\b", r"\bTB\s*=\s*\d\b", r"\bW\s*=\s*\d\b", r"\[\d+(?:,\s*\d+)*\]",
    r"\b(?:sec|Section|Table|Fig\.?|Figure)\s*\d+",
    r"\bGF\(2\)", r"\bstep\s+\d+\b", r"\bL\d\b", r"\bO\(\w+\)",
    # structural constants (not results): confidence level, field/beat/block widths, experiment-grid set notation,
    # xcolor mixes, ceil(V/32) beat counts
    r"\b95\s*\\?%", r"\b\d+-(?:bit|byte)\b", r"\\in\s*\\?\{[\d.,\s]+\\?\}", r"\\in\s*\[[\d.,\s]+\]", r"!\d+!",
    r"\\lceil\s*[VE]\s*/\s*\d+\s*\\rceil",
    r"(?:Verilator|Yosys|nextpnr\S*|Stim|PyMatching|Emscripten|emcc|Chrome|TLC|Z3|Python|PyTorch|torch|Opacus|"
    r"Node(?:\.js)?|clang|OpenJDK|Java|Bitwuzla|SymbiYosys|cryptography|macOS|V8)\s+v?\d+(?:\.\d+)*",
]
STRUCT_RE = re.compile("|".join(f"(?:{p})" for p in STRUCTURAL))


def offenders(text: str) -> list[str]:
    masked = STRUCT_RE.sub(lambda m: "§" * len(m.group(0)), text)
    bad = []
    for m in NUM.finditer(masked):
        tok = m.group(0)
        digits = tok.strip("+-%")
        try:
            if "." not in digits and "e" not in digits.lower() and "," not in digits and abs(int(digits)) <= 10:
                continue  # small counting integers ("two sites", "3 lanes" ...)
        except ValueError:
            pass
        ctx = masked[max(0, m.start() - 30): m.end() + 30].replace("\n", " ")
        bad.append(f"{tok!r} in ...{ctx}...")
    return bad


def main() -> int:
    used = claims.render()
    problems = []
    for tpl in sorted((ROOT / "docs").glob("*.md.in")):
        raw = re.sub(r"\{\{[A-Za-z0-9_]+(?::(?:stage|src))?\}\}", "", tpl.read_text())
        raw = re.sub(r"`[^`]*`", "", raw)  # code spans: commands / paths / identifiers
        raw = re.sub(r"```.*?```", "", raw, flags=re.S)
        raw = re.sub(r"\]\([^)]*\)", "]", raw)  # link targets
        for b in offenders(raw):
            problems.append(f"{tpl.relative_to(ROOT)}: unbacked number {b}")
    for tex in sorted((ROOT / "paper").glob("*.tex")):
        if tex.name == "numbers.tex":
            continue
        t = tex.read_text()
        for cid in re.findall(r"\\claim\{([^}]*)\}", t):
            if cid not in claims.CLAIMS:
                problems.append(f"{tex.relative_to(ROOT)}: \\claim{{{cid}}} is not registered in bench/claims.py")
        t = re.sub(r"(?<!\\)%.*", "", t)
        t = re.sub(r"\\claim\{[^}]*\}", "", t)
        t = re.sub(r"\\(?:cite|ref|label|eqref|includegraphics|input|usepackage|documentclass|begin|end|url|href)"
                   r"(?:\[[^\]]*\])?\{[^}]*\}", "", t)
        t = re.sub(r"\\(?:vspace|hspace|setlength|addtolength)\{[^}]*\}(?:\{[^}]*\})?", "", t)
        t = re.sub(r"\\texttt\{[^}]*\}", "", t)
        t = re.sub(r"\[[\d.]+(?:pt|em|cm|in|mm|ex)\]|[\d.]+\\(?:linewidth|textwidth|columnwidth)", "", t)
        for b in offenders(t):
            problems.append(f"{tex.relative_to(ROOT)}: unbacked number {b}")
    for name, ids in used.items():
        print(f"{name}: {len(ids)} claims")
    if problems:
        print("\n".join(problems))
        print(f"FAIL: {len(problems)} unbacked numbers")
        return 1
    print(f"OK: all numbers backed ({len(claims.CLAIMS)} registered claims)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
