#!/usr/bin/env bash
# Print the path to the Inno Setup command-line compiler, or fail loudly.
#
# Installers disagree about where Inno Setup lands — Chocolatey (what CI uses)
# puts it under Program Files (x86), winget installs it per-user under
# LOCALAPPDATA — so look in all the usual places rather than hardcoding one.
set -uo pipefail

# printenv, not ${...}: "ProgramFiles(x86)" isn't a name bash can expand.
program_files_x86="$(printenv 'ProgramFiles(x86)' || echo 'C:\Program Files (x86)')"
program_files="$(printenv 'ProgramFiles' || echo 'C:\Program Files')"
local_app_data="$(printenv 'LOCALAPPDATA' || echo "$HOME/AppData/Local")"

for dir in \
    "$program_files_x86/Inno Setup 6" \
    "$program_files/Inno Setup 6" \
    "$local_app_data/Programs/Inno Setup 6"
do
    candidate="${dir//\\//}/ISCC.exe"
    if [ -f "$candidate" ]; then
        echo "$candidate"
        exit 0
    fi
done

echo "ISCC.exe not found — is Inno Setup 6 installed?" >&2
exit 1
