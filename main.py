#!/usr/bin/env python3
"""Entry point for Repo Growth — launches the Tk GUI.

    python main.py

Pick a repository folder, choose a detail level, tick the outputs you want,
then click Generate. See README.md for details.
"""

from gui import launch_gui

if __name__ == "__main__":
    launch_gui()
