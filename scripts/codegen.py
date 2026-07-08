#!/usr/bin/env python3
"""
Code generator — scaffold files from Jinja2 templates.

Usage:
    python scripts/codegen.py --model Project --template fastapi_crud --output backend/app/routes
    python scripts/codegen.py --model User --template pydantic_model --output backend/app/models
    python scripts/codegen.py --agent narrative --template agent_stub --output backend/app/agents
    python scripts/codegen.py --skill backend-fastapi-api --template skill_stub --output skills

Safety:
    - Never overwrites existing files without --force.
    - Generated files contain TODO markers and must be reviewed.
    - Does not generate files outside the project root.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = PROJECT_ROOT / "templates" / "codegen"


def load_metadata() -> dict[str, str]:
    """Load project metadata from pyproject.toml."""
    meta = {"project_name": "unknown", "generator_version": "1.0.0"}
    pyproject = PROJECT_ROOT / "pyproject.toml"
    if pyproject.exists():
        content = pyproject.read_text(encoding="utf-8")
        for line in content.splitlines():
            if line.startswith("name ="):
                meta["project_name"] = line.split("=", 1)[1].strip().strip('"')
            elif line.startswith("version ="):
                meta["generator_version"] = line.split("=", 1)[1].strip().strip('"')
    return meta


def render(template_name: str, context: dict[str, object]) -> str:
    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR), trim_blocks=True, lstrip_blocks=True)
    template = env.get_template(f"{template_name}.jinja")
    return template.render(context)


def build_context(args: argparse.Namespace) -> dict[str, object]:
    ctx = load_metadata()
    ctx["timestamp"] = datetime.now(timezone.utc).isoformat()
    ctx["module_name"] = ctx["project_name"].replace("-", "_").lower()

    if args.model:
        ctx["model"] = args.model.lower()
        ctx["Model"] = args.model
        ctx["resource"] = ctx["model"]
        ctx["Resource"] = args.model
        ctx["resource_plural"] = f"{ctx['resource']}s"
        ctx["fields"] = args.fields or []

    if args.agent:
        ctx["agent_name"] = args.agent.lower()
        ctx["AgentName"] = "".join(p.capitalize() for p in args.agent.split("_"))
        ctx["description"] = args.description or f"{ctx['AgentName']} agent analysis"

    if args.skill:
        ctx["skill_name"] = args.skill
        ctx["category"] = args.category or "general"
        ctx["stage"] = args.stage or "MVP"
        ctx["description"] = args.description or f"Skill for {args.skill}"

    if args.prompt:
        ctx["prompt_key"] = args.prompt
        ctx["agent"] = args.agent or "system"
        ctx["version"] = args.version or "v1"
        ctx["description"] = args.description or f"{ctx['prompt_key']} prompt"
        ctx["model"] = args.model or "gpt-4o-mini"
        ctx["temperature"] = 0.3
        ctx["max_tokens"] = 512
        ctx["fields"] = args.fields or []

    return ctx


def output_path(args: argparse.Namespace, ctx: dict[str, object]) -> Path:
    output_dir = PROJECT_ROOT / args.output
    output_dir.mkdir(parents=True, exist_ok=True)

    name_map = {
        "fastapi_crud": f"{ctx['resource']}_routes.py",
        "pydantic_model": f"{ctx['model']}.py",
        "agent_stub": f"{ctx['agent_name']}_agent.py",
        "skill_stub": f"{ctx['category']}-{ctx['skill_name']}.md",
        "prompt_json": f"{ctx['version']}_{ctx['prompt_key']}.json",
    }
    filename = name_map.get(args.template)
    if not filename:
        raise ValueError(f"Unknown template: {args.template}")
    return output_dir / filename


def validate_path(path: Path) -> None:
    """Ensure output path stays within project root."""
    try:
        path.relative_to(PROJECT_ROOT)
    except ValueError as exc:
        raise ValueError(f"Output path must be inside project root: {path}") from exc


def parse_fields(raw: list[str]) -> list[dict[str, str]]:
    """Parse field descriptors like 'name:str:required:description'."""
    fields = []
    for item in raw:
        parts = item.split(":", 3)
        if len(parts) < 2:
            raise ValueError(f"Invalid field descriptor: {item}")
        fields.append(
            {
                "name": parts[0],
                "type": parts[1],
                "required": parts[2] if len(parts) > 2 else "required",
                "description": parts[3] if len(parts) > 3 else parts[0],
            }
        )
    return fields


def main() -> int:
    parser = argparse.ArgumentParser(description="Project code generator")
    parser.add_argument("--template", required=True, help="Template name")
    parser.add_argument("--output", required=True, help="Output directory relative to project root")
    parser.add_argument("--model", help="Model/Resource name")
    parser.add_argument("--agent", help="Agent name")
    parser.add_argument("--skill", help="Skill name")
    parser.add_argument("--prompt", help="Prompt key")
    parser.add_argument("--category", help="Skill category")
    parser.add_argument("--stage", help="Skill stage")
    parser.add_argument("--version", help="Prompt version")
    parser.add_argument("--description", help="Description")
    parser.add_argument("--fields", nargs="+", help="Field descriptors: name:type[:required][:description]")
    parser.add_argument("--force", action="store_true", help="Overwrite existing files")
    args = parser.parse_args()

    if args.fields:
        args.fields = parse_fields(args.fields)

    ctx = build_context(args)
    path = output_path(args, ctx)
    validate_path(path)

    if path.exists() and not args.force:
        print(f"❌ File already exists (use --force): {path}", file=sys.stderr)
        return 1

    rendered = render(args.template, ctx)
    path.write_text(rendered, encoding="utf-8")
    print(f"✅ Generated: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
