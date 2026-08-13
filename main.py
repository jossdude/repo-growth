#!/usr/bin/env python3
"""Entry point for Repo Growth.

Run with no arguments to launch the Tk GUI:

    python main.py

Or pass a repository path to run headless (for scripts and scheduled runs):

    python main.py <repo> [--detail LEVEL] [--exclude DIRS]
                          [--output PATH] [--no-static] [--no-animated]

Outputs default to <repo>/Repo Growth/ with a date-stamped filename, exactly
like the GUI. See README.md for details.
"""

import argparse
import os
import sys


def _version_banner():
    """Version plus how this copy updates itself — the first thing to ask
    when a build is misbehaving."""
    import updater
    from version import __version__

    return f"repo-growth {__version__} ({updater.update_mode()} build)"


def run_cli(argv):
    from repo_growth import (
        DETAIL_TARGETS,
        analyse_repo,
        animated_output_path,
        default_output_path,
        generate_animated_html,
        generate_html,
    )

    parser = argparse.ArgumentParser(
        prog="repo-growth",
        description="Visualise how a git repository has grown over time.",
    )
    parser.add_argument("--version", action="version", version=_version_banner())
    parser.add_argument("repo", help="path to the local git repository")
    parser.add_argument("--detail", choices=list(DETAIL_TARGETS), default="Standard",
                        help="sampling detail level (default: Standard)")
    parser.add_argument("--exclude", default="",
                        help="comma-separated folder names to leave out of every "
                             "chart, at any depth (e.g. --exclude tests,fixtures)")
    parser.add_argument("--output", default=None,
                        help="static HTML output path (default: <repo>/Repo Growth/<name>_growth_<date>.html)")
    parser.add_argument("--no-static", action="store_true",
                        help="skip the static dashboard")
    parser.add_argument("--no-animated", action="store_true",
                        help="skip the animated story")
    args = parser.parse_args(argv)

    if args.no_static and args.no_animated:
        parser.error("nothing to do: both --no-static and --no-animated given")
    if not os.path.isdir(args.repo):
        parser.error(f"not a directory: {args.repo}")

    out_static = args.output or default_output_path(args.repo)
    analysis = analyse_repo(args.repo, exclude_dirs=args.exclude,
                            target_points=DETAIL_TARGETS[args.detail])
    if not args.no_static:
        generate_html(analysis, out_static)
    if not args.no_animated:
        generate_animated_html(analysis, animated_output_path(out_static))
    return 0


def main():
    if len(sys.argv) > 1:
        sys.exit(run_cli(sys.argv[1:]))
    # Imported lazily so the CLI works on machines without tkinter.
    from gui import launch_gui
    launch_gui()


if __name__ == "__main__":
    main()
