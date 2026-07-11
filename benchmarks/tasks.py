"""Phase 6 benchmark task definitions covering basic, intermediate, and advanced scenarios."""

from __future__ import annotations

from paios.core.evaluator import EvalTask

# ── Basic tasks ─────────────────────────────────────────────────────────────

TASK_READ_CURDIR = EvalTask(
    id="basic_read_cwd",
    prompt="List all files in the current directory",
    category="basic",
    expected_tools=["filesystem_read"],
    min_steps=1,
    max_steps=5,
)

TASK_CHECK_CPU = EvalTask(
    id="basic_cpu_check",
    prompt="What is the current CPU usage percentage?",
    category="basic",
    expected_tools=["system_monitor"],
    min_steps=1,
    max_steps=5,
)

TASK_CHECK_RAM = EvalTask(
    id="basic_ram_check",
    prompt="How much RAM is currently in use?",
    category="basic",
    expected_tools=["system_monitor"],
    min_steps=1,
    max_steps=5,
)

TASK_ECHO = EvalTask(
    id="basic_echo",
    prompt='Run the command: echo "hello world"',
    category="basic",
    expected_tools=["terminal"],
    min_steps=1,
    max_steps=3,
)

TASK_FILE_STAT = EvalTask(
    id="basic_file_stat",
    prompt="What is the size of the file at backend/paios/__init__.py?",
    category="basic",
    expected_tools=["filesystem_read"],
    min_steps=1,
    max_steps=5,
)

BASIC_TASKS = [TASK_READ_CURDIR, TASK_CHECK_CPU, TASK_CHECK_RAM, TASK_ECHO, TASK_FILE_STAT]

# ── Intermediate tasks ──────────────────────────────────────────────────────

TASK_MULTI_STEP_SYSTEM = EvalTask(
    id="intermediate_system_overview",
    prompt="Get a complete system overview: CPU, memory, and disk usage",
    category="intermediate",
    expected_tools=["system_monitor", "system_monitor", "system_monitor"],
    min_steps=1,
    max_steps=8,
)

TASK_FILE_ANALYSIS = EvalTask(
    id="intermediate_file_analysis",
    prompt="Read the file backend/paios/__init__.py and tell me what version it says",
    category="intermediate",
    expected_tools=["filesystem_read"],
    min_steps=1,
    max_steps=5,
)

TASK_PLAN_DEP = EvalTask(
    id="intermediate_plan_deps",
    prompt="First check the CPU usage, then check memory usage, then tell me which is more heavily utilized",
    category="intermediate",
    expected_tools=["system_monitor", "system_monitor"],
    min_steps=2,
    max_steps=10,
)

TASK_TOOL_RECOVERY = EvalTask(
    id="intermediate_tool_recovery",
    prompt="Read the file /nonexistent/path/foo.txt, and if it fails, read the file backend/paios/__init__.py instead",
    category="intermediate",
    expected_tools=["filesystem_read", "filesystem_read"],
    min_steps=1,
    max_steps=8,
)

INTERMEDIATE_TASKS = [TASK_MULTI_STEP_SYSTEM, TASK_FILE_ANALYSIS, TASK_PLAN_DEP, TASK_TOOL_RECOVERY]

# ── Advanced tasks ──────────────────────────────────────────────────────────

TASK_LONG_RUNNING = EvalTask(
    id="advanced_long_running",
    prompt="Run system_monitor three times with a short delay between each and tell me if the values changed",
    category="advanced",
    expected_tools=["system_monitor", "system_monitor", "system_monitor"],
    min_steps=3,
    max_steps=15,
)

TASK_MEMORY_DEPENDENT = EvalTask(
    id="advanced_memory_dependent",
    prompt="Remember that the project name is PAIOS. Then later in the conversation, tell me what the project name is.",
    category="advanced",
    expected_tools=[],
    min_steps=1,
    max_steps=10,
)

TASK_PERMISSION_CONTROLLED = EvalTask(
    id="advanced_permission_controlled",
    prompt="Run a git status command in the current directory",
    category="advanced",
    expected_tools=["terminal"],
    min_steps=1,
    max_steps=5,
)

TASK_COMPLEX_REPLAN = EvalTask(
    id="advanced_complex_replan",
    prompt="List the files in the current directory, then check CPU usage, then read backend/paios/__init__.py, "
    "then summarize all findings. If any step fails, try a different approach.",
    category="advanced",
    expected_tools=["filesystem_read", "system_monitor", "filesystem_read"],
    min_steps=3,
    max_steps=15,
)

ADVANCED_TASKS = [TASK_LONG_RUNNING, TASK_MEMORY_DEPENDENT, TASK_PERMISSION_CONTROLLED, TASK_COMPLEX_REPLAN]

# ── Combined ────────────────────────────────────────────────────────────────

ALL_TASKS = BASIC_TASKS + INTERMEDIATE_TASKS + ADVANCED_TASKS
