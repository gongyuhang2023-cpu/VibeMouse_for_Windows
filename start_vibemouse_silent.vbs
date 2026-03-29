Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "python -m vibemouse.cli.main run", 0, False
