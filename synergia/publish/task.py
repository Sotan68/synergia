"""The daily Windows scheduled task that uploads queued videos (`main.py --upload-due`).

Registered for the current user with PowerShell's ScheduledTasks module. It runs once a day at
[autopilot] upload_time, just after YouTube's API quota resets, and catches up at the next boot or
logon if the PC was off at that time (StartWhenAvailable).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from synergia.config import CFG

TASK_NAME = "Synergia uploads"


def _ps(script: str, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                          capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=timeout)


def _q(s: str) -> str:
    """PowerShell single-quoted string."""
    return "'" + str(s).replace("'", "''") + "'"


def _pythonw() -> Path:
    exe = Path(sys.executable)
    w = exe.with_name("pythonw.exe")
    return w if w.is_file() else exe


def upload_time() -> str:
    return str(getattr(getattr(CFG, "autopilot", None), "upload_time", "10:15"))


def install() -> str:
    """Create or replace the task. Returns a short description; raises RuntimeError on failure."""
    root = CFG.root
    args = f'"{root / "main.py"}" --upload-due'
    script = f"""
$a = New-ScheduledTaskAction -Execute {_q(_pythonw())} -Argument {_q(args)} -WorkingDirectory {_q(root)}
$t = New-ScheduledTaskTrigger -Daily -At {_q(upload_time())}
$s = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 3)
Register-ScheduledTask -TaskName {_q(TASK_NAME)} -Action $a -Trigger $t -Settings $s -Force `
  -Description 'Synergia: uploads the queued autopilot videos to YouTube (daily quota permitting).' | Out-Null
"""
    r = _ps(script)
    if r.returncode != 0:
        raise RuntimeError(f"Couldn't create the scheduled task: {(r.stderr or r.stdout).strip()[:400]}")
    return f"Daily at {upload_time()} ('{TASK_NAME}' in Task Scheduler)"


def remove() -> None:
    _ps(f"Unregister-ScheduledTask -TaskName {_q(TASK_NAME)} -Confirm:$false")


def run_now() -> None:
    _ps(f"Start-ScheduledTask -TaskName {_q(TASK_NAME)}")


def status() -> dict:
    """{'installed': bool, 'next_run': str, 'last_run': str, 'last_result': int}."""
    script = f"""
$t = Get-ScheduledTask -TaskName {_q(TASK_NAME)} -ErrorAction SilentlyContinue
if (-not $t) {{ '{{"installed": false}}'; exit 0 }}
$i = $t | Get-ScheduledTaskInfo
@{{installed = $true; state = "$($t.State)";
   next_run = if ($i.NextRunTime) {{ $i.NextRunTime.ToString('yyyy-MM-dd HH:mm') }} else {{ '' }};
   last_run = if ($i.LastRunTime -and $i.LastRunTime.Year -gt 2000) {{ $i.LastRunTime.ToString('yyyy-MM-dd HH:mm') }} else {{ '' }};
   last_result = $i.LastTaskResult}} | ConvertTo-Json -Compress
"""
    try:
        r = _ps(script, timeout=30)
        return json.loads(r.stdout.strip() or "{}")
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return {"installed": False, "error": "couldn't ask Task Scheduler"}
