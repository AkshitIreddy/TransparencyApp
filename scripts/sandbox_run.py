"""Run a command inside an invisible Windows desktop, with a hard watchdog.

Usage:  python scripts/sandbox_run.py TIMEOUT_SECONDS -- <command line...>

The child process (and every window it creates) lives on a hidden desktop
object, so nothing is ever visible on the user's screen or taskbar, and
EnumWindows inside the sandbox only sees sandbox windows. On timeout the
whole process tree is force-killed. Exit code mirrors the child's.
"""

import os
import subprocess
import sys

import win32con
import win32event
import win32process
import win32service

DESKTOP_NAME = "TA_TEST_SANDBOX"


def main():
    if "--" not in sys.argv:
        print(__doc__)
        return 2
    sep = sys.argv.index("--")
    timeout_s = int(sys.argv[1])
    command = subprocess.list2cmdline(sys.argv[sep + 1:])

    # Keep an open handle for the lifetime of the child, otherwise the
    # desktop object would be destroyed under it.
    hdesk = win32service.CreateDesktop(
        DESKTOP_NAME, 0, win32con.GENERIC_ALL, None)

    si = win32process.STARTUPINFO()
    si.lpDesktop = DESKTOP_NAME

    proc_info = win32process.CreateProcess(
        None,
        f'cmd.exe /s /c "{command}"',
        None, None, False,
        win32con.CREATE_NO_WINDOW,
        None,
        os.getcwd(),
        si,
    )
    hproc, hthread, pid, _tid = proc_info
    hthread.Close()

    rc = win32event.WaitForSingleObject(hproc, timeout_s * 1000)
    if rc == win32event.WAIT_TIMEOUT:
        print(f"SANDBOX TIMEOUT after {timeout_s}s - killing process tree",
              flush=True)
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)],
                       capture_output=True,
                       creationflags=subprocess.CREATE_NO_WINDOW)
        win32event.WaitForSingleObject(hproc, 5000)
        exit_code = 124
    else:
        exit_code = win32process.GetExitCodeProcess(hproc)

    hproc.Close()
    hdesk.CloseDesktop()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
