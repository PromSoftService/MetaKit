from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
REQUIRED = (
    "component", "slug", "source", "kind", "title", "category", "summary",
    "description", "use_cases", "not_for", "diagram", "application",
    "parameter_groups", "example", "settings", "hmi", "optional_hmi", "common_mistakes",
)

FORBIDDEN_EDITORIAL_FRAGMENTS = (
    "Группа параметров",
    "Настройка функционального блока",
    "Значение передаётся в одноимённую",
    '%"" if',
)


def load(path: Path) -> dict[str, Any]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"{path.relative_to(ROOT)}: документ должен быть объектом")
    return document


def main() -> int:
    errors: list[str] = []
    guides: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted((ROOT / "docs/components").glob("*.yaml")):
        try:
            guides.append((path, load(path)))
        except (OSError, ValueError, yaml.YAMLError) as error:
            errors.append(str(error))

    if not guides:
        errors.append("docs/components: документация компонентов не найдена")

    seen: dict[str, dict[str, Path]] = {"component": {}, "slug": {}, "source": {}}
    documented_sources: set[str] = set()
    counts = {"Lib": 0, "Unit": 0, "Sys": 0}
    for path, guide in guides:
        relative = path.relative_to(ROOT)
        source_text = path.read_text(encoding="utf-8")
        for fragment in FORBIDDEN_EDITORIAL_FRAGMENTS:
            if fragment in source_text:
                errors.append(f"{relative}: в пользовательском тексте осталось техническое описание {fragment!r}")
        for key in REQUIRED:
            if key not in guide or guide[key] is None or guide[key] == "":
                errors.append(f"{relative}: пустое поле {key}")
        kind = str(guide.get("kind", ""))
        if kind not in counts:
            errors.append(f"{relative}: kind должен быть Lib, Unit или Sys")
        else:
            counts[kind] += 1
        slug = str(guide.get("slug", ""))
        if slug and path.stem != slug:
            errors.append(f"{relative}: имя файла должно совпадать со slug {slug!r}")
        source = str(guide.get("source", ""))
        if source:
            documented_sources.add(source)
            if not source.startswith("yaml/") or not source.endswith(".yaml"):
                errors.append(f"{relative}: source должен указывать на yaml/**/*.yaml")
            elif not (ROOT / source).is_file():
                errors.append(f"{relative}: не найден исходный компонент {source}")
        for key in seen:
            value = str(guide.get(key, ""))
            if not value:
                continue
            if value in seen[key]:
                errors.append(f"{relative}: {key} {value!r} уже используется в {seen[key][value].relative_to(ROOT)}")
            else:
                seen[key][value] = path

        groups = guide.get("parameter_groups")
        if not isinstance(groups, list) or not groups:
            errors.append(f"{relative}: parameter_groups должен быть непустым списком")
        else:
            for index, group in enumerate(groups, 1):
                if not isinstance(group, dict) or not group.get("title") or not group.get("items"):
                    errors.append(f"{relative}: некорректная группа параметров {index}")
                    continue
                if not group.get("intro"):
                    errors.append(f"{relative}: у группы параметров {index} нет пояснения перед таблицей")
                for item_index, item in enumerate(group["items"], 1):
                    if not isinstance(item, dict) or not item.get("key") or not item.get("description"):
                        errors.append(f"{relative}: некорректный параметр {index}.{item_index}")
        for table_name in ("settings", "hmi", "optional_hmi"):
            rows = guide.get(table_name)
            if not isinstance(rows, list):
                errors.append(f"{relative}: {table_name} должен быть списком")
                continue
            for index, row in enumerate(rows, 1):
                if not isinstance(row, dict) or not row.get("description"):
                    errors.append(f"{relative}: некорректная строка {table_name} {index}")

    actual_sources = {path.relative_to(ROOT).as_posix() for path in (ROOT / "yaml").rglob("*.yaml")}
    for missing in sorted(actual_sources - documented_sources):
        errors.append(f"нет документации для {missing}")
    for extra in sorted(documented_sources - actual_sources):
        errors.append(f"документация ссылается на отсутствующий {extra}")

    for required in (
        "docs/index.md", "docs/concepts/component-types.md", "docs/guides/custom-unit.md",
        "docs/guides/shared-configuration.md", "docs/guides/watchdog.md", "docs/deployment.md",
    ):
        if not (ROOT / required).is_file():
            errors.append(f"отсутствует {required}")

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        print(f"Documentation validation failed: {len(errors)} error(s)", file=sys.stderr)
        return 1
    print(f"Documentation validation passed: {len(guides)} components (Lib={counts['Lib']}, Unit={counts['Unit']}, Sys={counts['Sys']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
