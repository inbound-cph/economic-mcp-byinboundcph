#!/usr/bin/env python3
"""
Install the e-conomic skills for Claude Code and Codex on this machine.

    python scripts/install_skills.py            # copy into ~/.claude/skills and ~/.agents/skills
    python scripts/install_skills.py --link     # symlink instead, so `git pull` updates the skills
    python scripts/install_skills.py --claude   # Claude Code only
    python scripts/install_skills.py --codex    # Codex only
    python scripts/install_skills.py --uninstall

Claude Code users can alternatively install the plugin:
    /plugin marketplace add inbound-cph/economic-mcp-byinboundcph
    /plugin install economic@economic-mcp
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO_ROOT / "skills"
TARGETS = {
    "claude": Path.home() / ".claude" / "skills",
    "codex": Path.home() / ".agents" / "skills",
}


def skill_dirs() -> list[Path]:
    return sorted(p for p in SKILLS_DIR.iterdir() if p.is_dir() and (p / "SKILL.md").exists())


def install(target_root: Path, link: bool) -> None:
    target_root.mkdir(parents=True, exist_ok=True)
    for skill in skill_dirs():
        destination = target_root / skill.name
        if destination.is_symlink() or destination.exists():
            if destination.is_symlink() or destination.is_file():
                destination.unlink()
            else:
                shutil.rmtree(destination)
        if link:
            destination.symlink_to(skill, target_is_directory=True)
        else:
            shutil.copytree(skill, destination)
        print(f"  {'linked' if link else 'copied'}  {destination}")


def uninstall(target_root: Path) -> None:
    for skill in skill_dirs():
        destination = target_root / skill.name
        if destination.is_symlink() or destination.is_file():
            destination.unlink()
            print(f"  removed {destination}")
        elif destination.is_dir():
            shutil.rmtree(destination)
            print(f"  removed {destination}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--claude", action="store_true", help="only Claude Code (~/.claude/skills)")
    parser.add_argument("--codex", action="store_true", help="only Codex (~/.agents/skills)")
    parser.add_argument("--link", action="store_true", help="symlink the skill folders instead of copying")
    parser.add_argument("--uninstall", action="store_true", help="remove the skills again")
    args = parser.parse_args()

    if not skill_dirs():
        print(f"No skills found in {SKILLS_DIR}")
        return 1
    selected = [name for name, flag in (("claude", args.claude), ("codex", args.codex)) if flag] or list(TARGETS)

    for name in selected:
        root = TARGETS[name]
        print(f"{'Removing from' if args.uninstall else 'Installing to'} {root} ({'Claude Code' if name == 'claude' else 'Codex'})")
        if args.uninstall:
            uninstall(root)
        else:
            install(root, link=args.link)

    if not args.uninstall:
        names = ", ".join(p.name for p in skill_dirs())
        print(f"\nInstalled skills: {names}")
        print("Claude Code: type / to see them (e.g. /economic-debitorer). Codex: type $ (e.g. $economic-debitorer).")
        print("Remember to add the e-conomic MCP server to the client first (see GUIDE.md step 4).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
