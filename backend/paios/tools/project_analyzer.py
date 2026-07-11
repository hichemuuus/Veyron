"""Project analysis tool.

Inspects repository structure, identifies technologies, analyzes dependencies,
detects potential issues, and generates improvement recommendations.

Used by the agent as a tool and by the /api/projects endpoint directly.
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar, Type

from pydantic import BaseModel, Field

from paios.security.command_policy import PermissionLevel
from paios.security.path_policy import PathPolicyError, validate_path
from paios.tools.base import Tool, ToolContext, ToolResult

logger = logging.getLogger(__name__)

# File patterns for technology detection.
_TECH_PATTERNS: dict[str, list[str]] = {
    "Python": ["*.py", "requirements.txt", "pyproject.toml", "setup.py", "Pipfile", "setup.cfg"],
    "JavaScript": ["*.js", "*.jsx", "package.json"],
    "TypeScript": ["*.ts", "*.tsx", "tsconfig.json"],
    "React": ["*.jsx", "*.tsx"],
    "Node.js": ["package.json", "package-lock.json"],
    "Rust": ["*.rs", "Cargo.toml"],
    "Go": ["*.go", "go.mod"],
    "Java": ["*.java", "pom.xml", "build.gradle"],
    "Docker": ["Dockerfile", "*.dockerfile", "docker-compose.yml"],
    "SQL": ["*.sql"],
    "Shell": ["*.sh", "*.bash"],
    "HTML/CSS": ["*.html", "*.css", "*.scss", "*.less"],
    "C/C++": ["*.c", "*.h", "*.cpp", "*.hpp", "Makefile", "CMakeLists.txt"],
    "Ruby": ["*.rb", "Gemfile"],
    "PHP": ["*.php", "composer.json"],
    "Swift": ["*.swift", "Package.swift"],
    "Kotlin": ["*.kt", "*.kts"],
    "C#": ["*.cs", "*.csproj", "*.sln"],
}

# Common project config files for dependency analysis.
_DEPENDENCY_FILES = {
    "package.json": "npm",
    "Cargo.toml": "cargo",
    "go.mod": "go",
    "requirements.txt": "pip",
    "pyproject.toml": "pip",
    "Gemfile": "bundler",
    "pom.xml": "maven",
    "composer.json": "composer",
    "Pipfile": "pipenv",
}


@dataclass
class ProjectAnalysis:
    """Complete project analysis result."""

    root: str
    technologies: list[dict[str, Any]] = field(default_factory=list)
    structure: dict[str, Any] = field(default_factory=dict)
    dependencies: dict[str, list[str]] = field(default_factory=dict)
    issues: list[dict[str, Any]] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    summary: str = ""
    file_count: int = 0
    total_size_bytes: int = 0


class ProjectAnalyzerInputs(BaseModel):
    path: str = Field(..., description="Project root path within sandbox.")
    max_depth: int = Field(default=5, description="Max directory depth to scan.", ge=1, le=20)
    include_hidden: bool = Field(default=False, description="Include hidden files and dirs.")


class ProjectAnalyzerTool(Tool):
    """Analyze a project directory: structure, tech stack, dependencies, issues."""

    name: ClassVar[str] = "project_analyzer"
    description: ClassVar[str] = (
        "Analyze a project directory: detect technologies, list structure, "
        "parse dependencies, flag issues, and generate recommendations. "
        "Use for understanding unfamiliar codebases."
    )
    permission: ClassVar[PermissionLevel] = PermissionLevel.FREE
    Inputs: ClassVar[Type[BaseModel]] = ProjectAnalyzerInputs

    async def run(self, ctx: ToolContext, **inputs: Any) -> ToolResult:
        path_str = inputs["path"]
        max_depth = inputs.get("max_depth", 5)
        include_hidden = inputs.get("include_hidden", False)

        try:
            root = validate_path(path_str)
        except PathPolicyError as e:
            return ToolResult(ok=False, error=str(e))

        if not root.exists():
            return ToolResult(ok=False, error=f"path not found: {root}")
        if not root.is_dir():
            return ToolResult(ok=False, error=f"not a directory: {root}")

        try:
            analysis = analyze_project(root, max_depth=max_depth, include_hidden=include_hidden)
            return ToolResult(
                output=_format_analysis(analysis),
                data={
                    "technologies": analysis.technologies,
                    "file_count": analysis.file_count,
                    "total_size_bytes": analysis.total_size_bytes,
                    "issue_count": len(analysis.issues),
                    "recommendation_count": len(analysis.recommendations),
                },
            )
        except Exception as e:
            logger.exception("project analysis failed")
            return ToolResult(ok=False, error=f"analysis failed: {e}")


def analyze_project(
    root: Path,
    max_depth: int = 5,
    include_hidden: bool = False,
) -> ProjectAnalysis:
    """Analyze a project directory and return structured results."""
    analysis = ProjectAnalysis(root=str(root.resolve()))
    tree: dict[str, Any] = {"name": root.name, "type": "dir", "children": []}
    file_extensions: Counter = Counter()
    all_files: list[Path] = []
    total_size = 0

    # Walk the tree.
    _walk_tree(root, tree, all_files, file_extensions, 0, max_depth, include_hidden)

    analysis.structure = tree
    analysis.file_count = len(all_files)
    analysis.total_size_bytes = total_size

    # Detect technologies.
    analysis.technologies = _detect_technologies(root, file_extensions, all_files, include_hidden)

    # Parse dependencies.
    analysis.dependencies = _parse_dependencies(root, all_files)

    # Detect issues.
    analysis.issues = _detect_issues(root, all_files, file_extensions, analysis.technologies)

    # Generate recommendations.
    analysis.recommendations = _generate_recommendations(analysis)

    # Build summary.
    tech_names = [t["name"] for t in analysis.technologies[:5]]
    analysis.summary = (
        f"{analysis.file_count} files, "
        f"{', '.join(tech_names) if tech_names else 'unknown tech stack'}"
    )
    if analysis.issues:
        analysis.summary += f", {len(analysis.issues)} issue(s) found"

    return analysis


def _walk_tree(
    path: Path,
    node: dict,
    files: list[Path],
    extensions: Counter,
    depth: int,
    max_depth: int,
    include_hidden: bool,
) -> int:
    """Recursively walk a directory tree. Returns total size in bytes."""
    total = 0
    try:
        entries = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except PermissionError:
        return 0

    for entry in entries:
        if not include_hidden and entry.name.startswith("."):
            continue
        if entry.name in ("node_modules", ".git", "__pycache__", ".venv", "venv", "target", "build"):
            continue

        if entry.is_dir():
            if depth < max_depth:
                child = {"name": entry.name, "type": "dir", "children": []}
                sz = _walk_tree(entry, child, files, extensions, depth + 1, max_depth, include_hidden)
                if child["children"] or include_hidden:
                    node.setdefault("children", []).append(child)
                total += sz
        else:
            try:
                sz = entry.stat().st_size
            except OSError:
                sz = 0
            node.setdefault("children", []).append({"name": entry.name, "type": "file", "size": sz})
            files.append(entry)
            ext = entry.suffix.lower()
            if ext:
                extensions[ext] += 1
            total += sz

    return total


def _detect_technologies(
    root: Path,
    extensions: Counter,
    files: list[Path],
    include_hidden: bool,
) -> list[dict[str, Any]]:
    """Detect technologies used in the project."""
    detected: list[dict[str, Any]] = []
    tech_files = set()

    for tech, patterns in _TECH_PATTERNS.items():
        score = 0
        evidence = []
        for pattern in patterns:
            if pattern.startswith("*."):
                ext = pattern[1:]
                count = extensions.get(ext, 0)
                if count > 0:
                    score += count
                    evidence.append(f"{count} {pattern} file(s)")
            else:
                for f in files:
                    if f.name == pattern or f.match(pattern):
                        score += 2
                        evidence.append(f.name)
                        break

        if score > 0:
            detected.append({
                "name": tech,
                "confidence": min(1.0, score / 5),
                "evidence": evidence[:3],
            })

    return sorted(detected, key=lambda t: t["confidence"], reverse=True)


def _parse_dependencies(root: Path, files: list[Path]) -> dict[str, list[str]]:
    """Parse dependency files to extract package names."""
    deps: dict[str, list[str]] = {}
    for dep_file, manager in _DEPENDENCY_FILES.items():
        dep_path = root / dep_file
        if dep_path in files or dep_path.exists():
            pkgs = _parse_specific(dep_path, manager)
            if pkgs:
                deps[manager] = pkgs[:30]
    return deps


def _parse_specific(path: Path, manager: str) -> list[str]:
    """Parse a specific dependency file."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    if manager == "npm":
        try:
            data = json.loads(text)
            return list(data.get("dependencies", {}).keys()) + list(data.get("devDependencies", {}).keys())
        except json.JSONDecodeError:
            return []

    if manager == "pip":
        pkgs = []
        for line in text.splitlines():
            line = line.strip()
            if line and not line.startswith(("#", "-", "//")):
                pkgs.append(re.sub(r"[<>=!~].*$", "", line).strip())
        return pkgs

    if manager == "cargo":
        pkgs = re.findall(r'^(\w[\w-]*)\s*=', text, re.MULTILINE)
        return [p for p in pkgs if p not in ("[package]", "[dependencies]")]

    if manager == "go":
        pkgs = []
        for line in text.splitlines():
            line = line.strip()
            if line and not line.startswith(("module ", "go ", "require ", ")")):
                pkgs.append(line.split()[0] if line.split() else line)
        return pkgs

    return []


def _detect_issues(
    root: Path,
    files: list[Path],
    extensions: Counter,
    technologies: list[dict],
) -> list[dict[str, Any]]:
    """Detect potential issues in the project."""
    issues: list[dict[str, Any]] = []
    tech_names = {t["name"] for t in technologies}

    # No README.
    if not any(f.name.lower() in ("readme.md", "readme.rst", "readme.txt") for f in files):
        issues.append({
            "severity": "low",
            "category": "documentation",
            "message": "No README file found",
        })

    # Large files.
    for f in files:
        try:
            sz = f.stat().st_size
            if sz > 500_000:
                issues.append({
                    "severity": "medium",
                    "category": "size",
                    "message": f"Large file: {f.relative_to(root)} ({sz / 1024:.0f} KB)",
                })
        except OSError:
            pass

    # No package manager files.
    has_dep_file = any((root / df).exists() for df in _DEPENDENCY_FILES)
    if not has_dep_file and technologies:
        issues.append({
            "severity": "info",
            "category": "configuration",
            "message": "No dependency/package files detected",
        })

    # No tests.
    test_dirs = ["test", "tests", "__tests__"]
    test_extensions = {"*_test.py", "*.test.js", "*.spec.ts", "*_test.rs", "*_test.go"}
    has_tests = any(
        (root / td).is_dir() for td in test_dirs
    ) or any(
        any(f.match(te) for te in test_extensions) for f in files
    )
    if not has_tests and technologies:
        issues.append({
            "severity": "medium",
            "category": "testing",
            "message": "No test files or test directories found",
        })

    # Many files at root level.
    try:
        root_entries = [e for e in root.iterdir() if not e.name.startswith(".") or True]
        if len(root_entries) > 30:
            issues.append({
                "severity": "low",
                "category": "structure",
                "message": f"Root directory has {len(root_entries)} entries; consider organizing into subdirectories",
            })
    except OSError:
        pass

    return issues


def _generate_recommendations(analysis: ProjectAnalysis) -> list[str]:
    """Generate improvement recommendations based on analysis."""
    recs: list[str] = []
    tech_names = {t["name"] for t in analysis.technologies}

    medium_issues = [i for i in analysis.issues if i["severity"] == "medium"]
    if medium_issues:
        recs.append(f"Address {len(medium_issues)} medium-severity issue(s): "
                     f"{'; '.join(i['message'] for i in medium_issues[:3])}")

    if "Docker" not in tech_names and analysis.file_count > 20:
        recs.append("Consider adding Docker support for reproducible builds")

    if "README.md" not in [i["message"] for i in analysis.issues]:
        recs.append("Add a README.md with setup and usage instructions")

    if analysis.dependencies:
        for manager, pkgs in analysis.dependencies.items():
            if pkgs:
                recs.append(f"{len(pkgs)} {manager} dependencies tracked — keep them updated")

    if not recs:
        recs.append("Project looks well-structured — no major recommendations")

    return recs


def _format_analysis(analysis: ProjectAnalysis) -> str:
    """Format a ProjectAnalysis as human-readable text."""
    lines = [f"Project Analysis: {analysis.root}", "=" * 50, ""]

    # Technologies.
    if analysis.technologies:
        lines.append("Technologies:")
        for t in analysis.technologies:
            conf = f"{t['confidence']:.0%}"
            ev = "; ".join(t["evidence"][:2])
            lines.append(f"  - {t['name']} ({conf}): {ev}")
        lines.append("")

    # Summary stats.
    lines.append(f"Files: {analysis.file_count}, Total size: {analysis.total_size_bytes / 1024:.1f} KB")
    lines.append("")

    # Issues.
    if analysis.issues:
        lines.append(f"Issues ({len(analysis.issues)}):")
        for issue in sorted(analysis.issues, key=lambda i: ("high", "medium", "low", "info").index(i["severity"])):
            lines.append(f"  [{issue['severity']}] {issue['message']}")
        lines.append("")

    # Dependencies.
    if analysis.dependencies:
        lines.append("Dependencies:")
        for manager, pkgs in analysis.dependencies.items():
            lines.append(f"  {manager}: {', '.join(pkgs[:10])}{'...' if len(pkgs) > 10 else ''}")
        lines.append("")

    # Recommendations.
    if analysis.recommendations:
        lines.append("Recommendations:")
        for r in analysis.recommendations:
            lines.append(f"  - {r}")
        lines.append("")

    lines.append("=" * 50)
    return "\n".join(lines)
