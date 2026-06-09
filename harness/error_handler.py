"""Error handler — matches stderr against knowledge.yaml patterns."""

import re
import time
from pathlib import Path
from typing import Optional

import yaml

_KNOWLEDGE_PATH = Path(__file__).parent / "knowledge.yaml"


class ErrorMatch:
    def __init__(self, level: str, solution: Optional[str], params: dict = None, pattern: str = ""):
        self.level = level
        self.solution = solution
        self.params = params or {}
        self.pattern = pattern


class ErrorHandler:
    def __init__(self, knowledge_path: str = None):
        self._path = Path(knowledge_path) if knowledge_path else _KNOWLEDGE_PATH
        with open(self._path) as f:
            data = yaml.safe_load(f)
        self.rules = data.get("known_issues", [])
        self._compiled = [(re.compile(r["pattern"], re.IGNORECASE), r) for r in self.rules]

    def classify(self, stderr: str) -> ErrorMatch:
        """Match stderr against known patterns. Returns ErrorMatch with level and solution."""
        for regex, rule in self._compiled:
            if regex.search(stderr):
                return ErrorMatch(
                    level=rule["level"],
                    solution=rule.get("solution"),
                    params=rule.get("params", {}),
                    pattern=rule["pattern"],
                )
        return ErrorMatch(level="L3", solution=None)

    def learn(self, stderr: str, solution: str, confidence: str = "medium", source: str = "auto"):
        """Append a new pattern to knowledge.yaml if not already covered."""
        # Extract distinguishing line from stderr
        pattern = self._extract_pattern(stderr)
        if not pattern or len(pattern) < 15:
            return

        # Check if already covered
        for regex, _ in self._compiled:
            if regex.search(stderr):
                return  # Already covered, skip

        # Append to knowledge.yaml
        new_entry = {
            "pattern": pattern,
            "level": "L1",
            "solution": solution,
            "confidence": confidence,
            "source": source,
            "learned_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        # Append as text to preserve hand-written formatting
        entry_text = (
            f'\n  - pattern: "{pattern}"\n'
            f'    level: L1\n'
            f'    solution: "{solution}"\n'
            f'    confidence: {confidence}\n'
            f'    source: {source}\n'
            f'    learned_at: "{new_entry["learned_at"]}"\n'
            f'    desc: "自动学习: {solution}"\n'
        )
        with open(self._path, "a") as f:
            f.write(entry_text)

        # Update in-memory rules
        self.rules.append(new_entry)
        self._compiled.append((re.compile(pattern, re.IGNORECASE), new_entry))

    def _extract_pattern(self, stderr: str) -> str:
        """Extract the most distinguishing line from stderr as a regex pattern."""
        lines = [l.strip() for l in stderr.strip().split("\n") if l.strip()]
        # Prefer lines with error keywords
        for line in lines:
            if any(kw in line.lower() for kw in ["error", "failed", "cannot", "not found", "timeout"]):
                # Escape regex special chars, keep key words
                clean = re.sub(r"[0-9.]+\.[0-9.]+", r"[\\d.]+", line[:80])
                clean = re.escape(clean).replace(r"\ ", " ").replace(r"\[\\d\.\]\+", r"[\d.]+")
                return clean
        # Fallback: last non-empty line
        if lines:
            return re.escape(lines[-1][:60])
        return ""
