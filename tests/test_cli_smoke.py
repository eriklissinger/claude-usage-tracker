"""Smoke tests for CLI shell wiring."""
import os
import subprocess
import sys


def test_help_exits_zero():
    """--help should exit 0 and list subcommands."""
    # Ensure the module is in the path for subprocess
    env = os.environ.copy()
    env["PYTHONPATH"] = "src"

    result = subprocess.run(
        [sys.executable, "-m", "claude_usage_tracker", "--help"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "render-waybar" in result.stdout
    assert "settings" in result.stdout
    assert "doctor" in result.stdout


def test_invalid_command_exits_nonzero():
    """Invalid subcommand should exit non-zero."""
    env = os.environ.copy()
    env["PYTHONPATH"] = "src"

    result = subprocess.run(
        [sys.executable, "-m", "claude_usage_tracker", "not-a-command"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode != 0


def test_no_args_shows_help():
    """No arguments should show help."""
    env = os.environ.copy()
    env["PYTHONPATH"] = "src"

    result = subprocess.run(
        [sys.executable, "-m", "claude_usage_tracker"],
        capture_output=True,
        text=True,
        env=env,
    )
    # Either exits 0 with help, or exits non-zero with usage guidance
    output = result.stdout + result.stderr
    assert "render-waybar" in output or "usage" in output.lower()
