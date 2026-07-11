"""Training data format for the tool-selection model.

Defines the expected structure and provides seed examples.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from paios.intelligence.tool_selector.schema import ToolSelectionExample


class ToolSelectionDataset:
    """A collection of (text, expected_tools) pairs for training tool selection."""

    def __init__(self, examples: list[ToolSelectionExample] | None = None) -> None:
        self.examples: list[ToolSelectionExample] = examples or []

    def add(self, example: ToolSelectionExample) -> None:
        self.examples.append(example)

    def __len__(self) -> int:
        return len(self.examples)

    def __getitem__(self, idx: int) -> ToolSelectionExample:
        return self.examples[idx]

    @property
    def texts(self) -> list[str]:
        return [ex.text for ex in self.examples]

    @property
    def targets(self) -> list[list[str]]:
        return [ex.expected_tools for ex in self.examples]

    @classmethod
    def generate_seed(cls) -> ToolSelectionDataset:
        """Return an expanded seed dataset based on the current tool registry and intent categories."""
        from paios.tools.registry import get_registry

        registry = get_registry()
        tool_names = registry.names()
        has_tool = {name: name in tool_names for name in ["filesystem_read", "system_monitor", "terminal", "project_analyzer"]}

        examples: list[ToolSelectionExample] = []

        if has_tool.get("filesystem_read", False):
            examples.extend([
                ToolSelectionExample(text="List all files in the current directory", expected_tools=["filesystem_read"], intent_category="file_operation", notes="needs a path argument (defaults to current dir)"),
                ToolSelectionExample(text="Read the contents of README.md", expected_tools=["filesystem_read"], intent_category="file_operation", notes="needs file_path=README.md"),
                ToolSelectionExample(text="What is the size of backend/paios/__init__.py?", expected_tools=["filesystem_read"], intent_category="file_operation", notes="needs file_path and action=stat"),
                ToolSelectionExample(text="Show me the files in the src directory", expected_tools=["filesystem_read"], intent_category="file_operation", notes="needs path=src"),
                ToolSelectionExample(text="Find all Python files in the project", expected_tools=["filesystem_read"], intent_category="file_operation", notes="needs path and pattern"),
                ToolSelectionExample(text="Count the lines in main.py", expected_tools=["filesystem_read"], intent_category="file_operation", notes="needs file_path and action=stat"),
                ToolSelectionExample(text="Does the file config.yaml exist?", expected_tools=["filesystem_read"], intent_category="file_operation", notes="needs file_path and action=stat"),
                ToolSelectionExample(text="Open the log file and show me the contents", expected_tools=["filesystem_read"], intent_category="file_operation", notes="needs file_path"),
                ToolSelectionExample(text="What's in this folder?", expected_tools=["filesystem_read"], intent_category="file_operation", notes="default path"),
                ToolSelectionExample(text="List all directories in the project root", expected_tools=["filesystem_read"], intent_category="file_operation", notes="needs action=list and path"),
            ])

        if has_tool.get("system_monitor", False):
            examples.extend([
                ToolSelectionExample(text="What is the current CPU usage?", expected_tools=["system_monitor"], intent_category="system_management", notes="needs metric=cpu"),
                ToolSelectionExample(text="How much RAM is available?", expected_tools=["system_monitor"], intent_category="system_management", notes="needs metric=memory"),
                ToolSelectionExample(text="Show me the disk usage", expected_tools=["system_monitor"], intent_category="system_management", notes="needs metric=disk"),
                ToolSelectionExample(text="Get a complete system overview: CPU, memory, disk", expected_tools=["system_monitor", "system_monitor", "system_monitor"], intent_category="system_management", notes="multi-call for different metrics"),
                ToolSelectionExample(text="Check the system health", expected_tools=["system_monitor"], intent_category="system_management", notes="needs metric=health"),
                ToolSelectionExample(text="What processes are running?", expected_tools=["system_monitor"], intent_category="system_management", notes="needs metric=processes"),
                ToolSelectionExample(text="How much disk space is free?", expected_tools=["system_monitor"], intent_category="system_management", notes="needs metric=disk"),
                ToolSelectionExample(text="Monitor the CPU temperature", expected_tools=["system_monitor"], intent_category="system_management", notes="needs metric=cpu"),
                ToolSelectionExample(text="Show me network statistics", expected_tools=["system_monitor"], intent_category="system_management", notes="needs metric=network"),
                ToolSelectionExample(text="How long has the system been running?", expected_tools=["system_monitor"], intent_category="system_management", notes="needs metric=uptime"),
            ])

        if has_tool.get("terminal", False):
            examples.extend([
                ToolSelectionExample(text="Run git status", expected_tools=["terminal"], intent_category="tool_execution", notes="needs command=git status"),
                ToolSelectionExample(text="Execute 'ls -la' and show me the output", expected_tools=["terminal"], intent_category="tool_execution", notes="needs command=ls -la"),
                ToolSelectionExample(text="Run the tests with pytest", expected_tools=["terminal"], intent_category="tool_execution", notes="needs command=pytest"),
                ToolSelectionExample(text="Build the project", expected_tools=["terminal"], intent_category="tool_execution", notes="needs build command"),
                ToolSelectionExample(text="Deploy the application", expected_tools=["terminal"], intent_category="tool_execution", notes="needs deploy command"),
                ToolSelectionExample(text="Install the dependencies", expected_tools=["terminal"], intent_category="tool_execution", notes="needs install command"),
                ToolSelectionExample(text="Start the development server", expected_tools=["terminal"], intent_category="tool_execution", notes="needs start command"),
                ToolSelectionExample(text="Run a shell command to check disk space", expected_tools=["terminal"], intent_category="tool_execution", notes="needs command"),
                ToolSelectionExample(text="Run npm install", expected_tools=["terminal"], intent_category="tool_execution", notes="needs command=npm install"),
                ToolSelectionExample(text="Check the git log", expected_tools=["terminal"], intent_category="tool_execution", notes="needs command=git log"),
            ])

        if has_tool.get("project_analyzer", False):
            examples.extend([
                ToolSelectionExample(text="Analyze the project structure", expected_tools=["project_analyzer"], intent_category="project_analysis", notes="needs path argument"),
                ToolSelectionExample(text="What dependencies does this project use?", expected_tools=["project_analyzer"], intent_category="project_analysis", notes="analyze with dependency detection"),
                ToolSelectionExample(text="Check the code quality of this project", expected_tools=["project_analyzer"], intent_category="project_analysis", notes="needs path"),
                ToolSelectionExample(text="What technologies are used in this codebase?", expected_tools=["project_analyzer"], intent_category="project_analysis", notes="tech detection"),
                ToolSelectionExample(text="Generate a summary of the repository", expected_tools=["project_analyzer"], intent_category="project_analysis", notes="needs path"),
                ToolSelectionExample(text="Find potential issues in the project", expected_tools=["project_analyzer"], intent_category="project_analysis", notes="issue detection"),
                ToolSelectionExample(text="Analyze the test coverage", expected_tools=["project_analyzer"], intent_category="project_analysis", notes="needs source path"),
                ToolSelectionExample(text="What framework does this project use?", expected_tools=["project_analyzer"], intent_category="project_analysis", notes="tech detection"),
                ToolSelectionExample(text="Find unused dependencies", expected_tools=["project_analyzer"], intent_category="project_analysis", notes="dependency analysis"),
                ToolSelectionExample(text="Generate architecture documentation", expected_tools=["project_analyzer"], intent_category="project_analysis", notes="needs path"),
            ])

        # Multi-tool examples.
        examples.extend([
            ToolSelectionExample(text="Check CPU and memory usage", expected_tools=["system_monitor", "system_monitor"], intent_category="system_management", notes="sequential calls for different metrics"),
            ToolSelectionExample(text="Read src/main.py and analyze the project", expected_tools=["filesystem_read", "project_analyzer"], intent_category="planning_task", notes="two-step: read file then analyze project"),
            ToolSelectionExample(text="First check CPU, then check disk, then summarize", expected_tools=["system_monitor", "system_monitor"], intent_category="planning_task", notes="multi-step system monitoring"),
            ToolSelectionExample(text="Read the error log and run a diagnostic", expected_tools=["filesystem_read", "terminal"], intent_category="debugging", notes="read first, then run diagnostic command"),
            ToolSelectionExample(text="List the files in src/ then analyze the codebase", expected_tools=["filesystem_read", "project_analyzer"], intent_category="planning_task", notes="sequential multi-tool"),
            ToolSelectionExample(text="Get system stats and run a health check", expected_tools=["system_monitor", "terminal"], intent_category="system_management", notes="monitor then execute health command"),
            ToolSelectionExample(text="Read the config file and validate the setup", expected_tools=["filesystem_read", "project_analyzer"], intent_category="planning_task", notes="read then validate"),
            ToolSelectionExample(text="Check disk space, then find large files, then clean up", expected_tools=["system_monitor", "filesystem_read", "terminal"], intent_category="planning_task", notes="three-step: check, find, clean"),
            ToolSelectionExample(text="Monitor system performance and save the report", expected_tools=["system_monitor", "terminal"], intent_category="system_management", notes="monitor and save"),
            ToolSelectionExample(text="Read the test file and run the tests", expected_tools=["filesystem_read", "terminal"], intent_category="debugging", notes="find tests then run them"),
        ])

        return cls(examples)

    @classmethod
    def generate_expanded(cls, target: int = 500, seed: int = 42) -> ToolSelectionDataset:
        """Generate an expanded dataset with single-tool, multi-tool, ambiguous,
        incomplete, and adversarial examples.

        Sources:
          - Seed examples (50)
          - Template variations for each tool
          - Multi-tool workflow combinations
          - Ambiguous requests
          - Incomplete requests
          - Adversarial wording
        """
        import random as _random
        rng = _random.Random(seed)

        # Start with seed examples.
        seed_dataset = cls.generate_seed()
        all_examples: list[ToolSelectionExample] = list(seed_dataset.examples)

        _PREFIXES = ["Can you", "Please", "I need you to", "Could you", "Would you", "Help me"]
        _SUFFIXES = [".", "!", " please", " for me", " now", ""]

        def _variant(text: str) -> str:
            result = text
            if rng.random() < 0.4:
                result = rng.choice(_PREFIXES) + " " + result[0].lower() + result[1:]
            if rng.random() < 0.3:
                result = result + rng.choice(_SUFFIXES)
            return result.strip()

        # ── Single-tool expansions ────────────────────────────────────────

        filesystem_base = [
            "List all Python files", "Show me the contents of config.py",
            "Read the first line of README.md", "Display the file structure",
            "Find all markdown documents", "Show me file sizes",
            "List everything in src", "Count all Python files",
            "Find recently modified files", "Show me the root directory",
            "Check if pyproject.toml exists", "What files are in the tests folder?",
            "Show the contents of the docs directory", "List all JSON configuration files",
            "Find files containing the word TODO", "Read the version from setup.py",
            "Show file permissions for all scripts", "Count lines in each Python file",
            "Find duplicate file names across directories", "List the largest files",
            "Show me the directory tree", "Check the file count in each folder",
            "Find empty directories", "Read the changelog file",
            "Show me files modified this week",
        ]

        system_base = [
            "Check the CPU load average", "Show me memory usage over time",
            "What is the disk I/O wait?", "Monitor network latency",
            "Show running processes by user", "Check the swap usage",
            "What is the system load?", "Show me the GPU status",
            "List all listening ports", "Check firewall status",
            "Monitor disk activity", "Show CPU usage per core",
            "What processes are using the most I/O?", "Check the system temperature",
            "Show active network connections", "List all cron jobs",
            "Check the kernel version", "Show system log errors",
            "Monitor file system mounts", "Check the battery status",
            "What is the memory fragmentation?", "Show the interrupt rate",
            "Check container resource usage", "Display systemd service status",
            "Monitor context switch rate",
        ]

        terminal_base = [
            "Run a Python script", "Execute the backup command",
            "Run the linter on src/", "Compile the TypeScript project",
            "Run the database seed script", "Execute the migration",
            "Start the worker process", "Run a git diff",
            "Check out the main branch", "Run the formatter",
            "Execute the setup script", "Run the end-to-end tests",
            "Start the build process", "Run a diagnostic command",
            "Execute the cleanup script", "Run git fetch --prune",
            "Check the git remote configuration", "Run the docker-compose command",
            "Execute the data export", "Run the smoke tests",
            "Run a shell script from the scripts folder", "Execute npm audit",
            "Run the benchmark suite", "Start the profiler",
            "Run git stash and pull",
        ]

        project_base = [
            "Analyze the build configuration", "Check for license compliance",
            "Generate a class diagram", "Map the module dependencies",
            "Find dead code in the project", "Analyze API surface area",
            "Generate code metrics report", "Check coding standards compliance",
            "Analyze the database schema", "Find hardcoded configuration values",
            "Generate a contributor report", "Check the project's health score",
            "Analyze the test to code ratio", "Find deprecated API usage",
            "Generate a performance profile", "Check the security posture",
            "Analyze third-party integration points", "Find architectural smells",
            "Generate a refactoring roadmap", "Check the documentation coverage",
            "Analyze the error handling patterns", "Find inconsistent naming conventions",
            "Generate a deployment topology", "Check environment configuration consistency",
            "Analyze the logging strategy",
        ]

        tool_bases = {
            "filesystem_read": (filesystem_base, "file_operation"),
            "system_monitor": (system_base, "system_management"),
            "terminal": (terminal_base, "tool_execution"),
            "project_analyzer": (project_base, "project_analysis"),
        }

        for tool_name, (bases, intent_cat) in tool_bases.items():
            for base_text in bases:
                all_examples.append(ToolSelectionExample(
                    text=base_text,
                    expected_tools=[tool_name],
                    intent_category=intent_cat,
                    notes="single-tool expansion",
                ))
                # Add 2 variations of each.
                for _ in range(2):
                    vt = _variant(base_text)
                    all_examples.append(ToolSelectionExample(
                        text=vt,
                        expected_tools=[tool_name],
                        intent_category=intent_cat,
                        notes="single-tool variant",
                    ))

        # ── Multi-tool workflow expansions ────────────────────────────────

        multi_tool_bases = [
            (["filesystem_read", "project_analyzer"], "planning_task", "Read the code then analyze it"),
            (["filesystem_read", "project_analyzer"], "planning_task", "Open the source files and examine the architecture"),
            (["filesystem_read", "project_analyzer"], "planning_task", "Load the project files and review the design"),
            (["filesystem_read", "project_analyzer"], "planning_task", "Read the module and analyze its structure"),
            (["filesystem_read", "terminal"], "debugging", "Read the error log and run a fix"),
            (["filesystem_read", "terminal"], "debugging", "Open the test output and re-run the tests"),
            (["filesystem_read", "terminal"], "debugging", "Read the crash report and execute the recovery script"),
            (["filesystem_read", "terminal"], "debugging", "Check the log file and restart the service"),
            (["system_monitor", "terminal"], "system_management", "Check the memory and run cleanup"),
            (["system_monitor", "terminal"], "system_management", "Monitor the CPU and kill the top process"),
            (["system_monitor", "terminal"], "system_management", "Check disk space and run the archiver"),
            (["system_monitor", "terminal"], "system_management", "Monitor network and restart the interface"),
            (["system_monitor", "system_monitor"], "system_management", "Check CPU then check memory"),
            (["system_monitor", "system_monitor", "system_monitor"], "system_management", "CPU, memory, disk full check"),
            (["filesystem_read", "system_monitor"], "system_management", "Read the config and check the system"),
            (["filesystem_read", "system_monitor"], "system_management", "Open the settings file and verify system state"),
            (["filesystem_read", "project_analyzer", "terminal"], "planning_task", "Read files, analyze, and run a report script"),
            (["system_monitor", "filesystem_read", "terminal"], "planning_task", "Check disk, find large files, and clean up"),
            (["filesystem_read", "terminal", "project_analyzer"], "planning_task", "List files, run analyzer, and generate report"),
            (["system_monitor", "project_analyzer"], "planning_task", "Get system stats and analyze the project"),
            (["terminal", "project_analyzer"], "planning_task", "Build the project and analyze the output"),
            (["filesystem_read", "filesystem_read"], "file_operation", "Read two files and compare them"),
            (["system_monitor", "system_monitor", "system_monitor"], "system_management", "Sequential health checks across all metrics"),
            (["terminal", "terminal"], "tool_execution", "Run the build then run the tests"),
            (["terminal", "terminal"], "tool_execution", "Execute the migration then seed the database"),
            (["filesystem_read", "project_analyzer", "terminal"], "planning_task", "Full audit: read code, analyze, generate report"),
        ]

        for tools, intent_cat, text in multi_tool_bases:
            all_examples.append(ToolSelectionExample(
                text=text, expected_tools=tools, intent_category=intent_cat, notes="multi-tool workflow",
            ))
            for _ in range(1):
                vt = _variant(text)
                all_examples.append(ToolSelectionExample(
                    text=vt, expected_tools=tools, intent_category=intent_cat, notes="multi-tool variant",
                ))

        # ── Ambiguous requests ────────────────────────────────────────────

        ambiguous_examples = [
            (["filesystem_read"], "file_operation", "Show me what's in there"),
            (["filesystem_read"], "file_operation", "Can you open that thing?"),
            (["filesystem_read"], "file_operation", "I need to see the documents"),
            (["system_monitor"], "system_management", "How's the system doing today?"),
            (["system_monitor"], "system_management", "Give me the health status"),
            (["system_monitor"], "system_management", "Is everything ok with the machine?"),
            (["terminal"], "tool_execution", "Run that process we talked about"),
            (["terminal"], "tool_execution", "Execute the thing for me"),
            (["terminal"], "tool_execution", "Go ahead and run the command"),
            (["project_analyzer"], "project_analysis", "Tell me about the project health"),
            (["project_analyzer"], "project_analysis", "What do you think of the codebase?"),
            (["project_analyzer"], "project_analysis", "Give me the project overview"),
            (["filesystem_read", "project_analyzer"], "planning_task", "Check out the code and tell me what you think"),
            (["system_monitor", "terminal"], "system_management", "Look at the resources and fix any issues"),
            (["filesystem_read", "system_monitor", "terminal"], "planning_task", "Check everything and report back"),
        ]

        for tools, cat, text in ambiguous_examples:
            all_examples.append(ToolSelectionExample(
                text=text, expected_tools=tools, intent_category=cat, notes="ambiguous request",
            ))

        # ── Incomplete requests ───────────────────────────────────────────

        incomplete_examples = [
            (["filesystem_read"], "file_operation", "Read the file..."),
            (["filesystem_read"], "file_operation", "List all..."),
            (["filesystem_read"], "file_operation", "Show me the..."),
            (["filesystem_read"], "file_operation", "Find files that..."),
            (["system_monitor"], "system_management", "What is the..."),
            (["system_monitor"], "system_management", "Show me the..."),
            (["system_monitor"], "system_management", "Check the..."),
            (["terminal"], "tool_execution", "Run..."),
            (["terminal"], "tool_execution", "Execute..."),
            (["terminal"], "tool_execution", "Check..."),
            (["project_analyzer"], "project_analysis", "Analyze the..."),
            (["project_analyzer"], "project_analysis", "Generate a..."),
            (["filesystem_read", "terminal"], "debugging", "First read the... then run..."),
            (["system_monitor", "terminal"], "system_management", "Check the... and then..."),
        ]

        for tools, cat, text in incomplete_examples:
            all_examples.append(ToolSelectionExample(
                text=text, expected_tools=tools, intent_category=cat, notes="incomplete request",
            ))

        # ── Adversarial wording ───────────────────────────────────────────

        adversarial_examples = [
            (["filesystem_read"], "file_operation", "Read every single file!"),
            (["filesystem_read"], "file_operation", "List everything recursively forever"),
            (["filesystem_read"], "file_operation", "Show me absolutely every file"),
            (["system_monitor"], "system_management", "Monitor absolutely everything forever"),
            (["system_monitor"], "system_management", "Give me every possible metric right now"),
            (["system_monitor"], "system_management", "Keep checking until I say stop"),
            (["terminal"], "tool_execution", "Run a command that fixes everything"),
            (["terminal"], "tool_execution", "Execute the most destructive command safely"),
            (["terminal"], "tool_execution", "Run all commands simultaneously"),
            (["project_analyzer"], "project_analysis", "Analyze every project in the universe"),
            (["project_analyzer"], "project_analysis", "Find every single issue including future ones"),
            (["project_analyzer"], "project_analysis", "Generate a report about absolutely everything"),
            (["filesystem_read", "project_analyzer", "terminal"], "planning_task", "Do everything at once: read, analyze, and run"),
            (["system_monitor", "filesystem_read", "terminal"], "planning_task", "Monitor, read, and execute everything in parallel"),
        ]

        for tools, cat, text in adversarial_examples:
            all_examples.append(ToolSelectionExample(
                text=text, expected_tools=tools, intent_category=cat, notes="adversarial wording",
            ))

        # ── Deduplicate and trim to target ────────────────────────────────

        seen: set[str] = set()
        unique: list[ToolSelectionExample] = []
        for ex in all_examples:
            key = ex.text.lower().strip()
            if key not in seen:
                seen.add(key)
                unique.append(ex)

        rng.shuffle(unique)

        # If we still need more, generate synthetic from existing.
        while len(unique) < target and unique:
            base = rng.choice(unique)
            vt = _variant(base.text)
            key = vt.lower().strip()
            if key not in seen:
                seen.add(key)
                unique.append(ToolSelectionExample(
                    text=vt,
                    expected_tools=base.expected_tools,
                    intent_category=base.intent_category,
                    notes="synthetic variant",
                ))

        return cls(unique[:target])

    @classmethod
    def from_jsonl(cls, path: str | Path) -> ToolSelectionDataset:
        """Load examples from a JSONL file."""
        dataset = cls()
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                dataset.add(ToolSelectionExample(**data))
        return dataset

    def to_jsonl(self, path: str | Path) -> None:
        """Serialise to JSONL."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            for ex in self.examples:
                f.write(json.dumps({
                    "text": ex.text,
                    "expected_tools": ex.expected_tools,
                    "intent_category": ex.intent_category,
                    "notes": ex.notes,
                }, ensure_ascii=False) + "\n")
