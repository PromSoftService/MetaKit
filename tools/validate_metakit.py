from __future__ import annotations

import sys
import uuid
from pathlib import Path
from typing import Any

import yaml

from metakitlib import (
    DATA_COLUMNS,
    REPOSITORY_ROOT,
    discover_components,
    is_blank_row,
    iter_strings,
    load_catalog,
    load_config,
    parameter_groups,
    parameter_keys,
    referenced_parameter_keys,
)


class Validation:
    def __init__(self) -> None:
        self.errors: list[str] = []

    def require(self, condition: bool, message: str) -> None:
        if not condition:
            self.errors.append(message)


def validate_component(validation: Validation, component: Any) -> None:
    path = component.relative_path
    document = component.document
    validation.require(document.get("kind") == "metagen.component", f"{path}: неверный kind")
    validation.require(document.get("version") == 1, f"{path}: поддерживается version: 1")

    metadata = document.get("component")
    validation.require(isinstance(metadata, dict), f"{path}: отсутствует component")
    if not isinstance(metadata, dict):
        return
    for key in ("id", "name", "type", "module", "description"):
        validation.require(bool(str(metadata.get(key) or "").strip()), f"{path}: component.{key} пуст")
    try:
        uuid.UUID(str(metadata.get("id")))
    except (ValueError, TypeError, AttributeError):
        validation.errors.append(f"{path}: component.id не является UUID")

    params = document.get("params")
    validation.require(isinstance(params, dict), f"{path}: отсутствует params")
    if isinstance(params, dict):
        validation.require(
            params.get("format") in {"header-plus-rows", "table"},
            f"{path}: неверный params.format",
        )
        validation.require(isinstance(params.get("header"), list), f"{path}: params.header должен быть списком")
        validation.require(isinstance(params.get("rows"), list), f"{path}: params.rows должен быть списком")
        for group_index, group in enumerate(parameter_groups(document), start=1):
            width = len(group[0])
            validation.require(width > 0, f"{path}: пустой заголовок группы Params {group_index}")
            for row_index, row in enumerate(group[1:], start=1):
                validation.require(
                    len(row) <= width,
                    f"{path}: строка {row_index} группы Params {group_index} шире заголовка",
                )

    data = document.get("data")
    validation.require(isinstance(data, dict), f"{path}: отсутствует data")
    if isinstance(data, dict):
        validation.require(data.get("format") == "table", f"{path}: неверный data.format")
        columns = data.get("columns")
        validation.require(columns == DATA_COLUMNS, f"{path}: неверный состав или порядок столбцов Data")
        rows = data.get("rows")
        validation.require(isinstance(rows, list), f"{path}: data.rows должен быть списком")
        if isinstance(rows, list) and columns == DATA_COLUMNS:
            for index, row in enumerate(rows, start=1):
                if is_blank_row(row):
                    continue
                validation.require(isinstance(row, list), f"{path}: Data, строка {index} не является списком")
                if not isinstance(row, list):
                    continue
                validation.require(
                    len(row) == len(columns),
                    f"{path}: Data, строка {index}: {len(row)} ячеек вместо {len(columns)}",
                )
                if len(row) == len(columns):
                    values = dict(zip(columns, row))
                    conf = str(values.get("Conf") or "").strip()
                    hmi = str(values.get("HMI") or "").strip()
                    validation.require(
                        not conf or hmi == conf,
                        f"{path}: Data, строка {index}: Conf={conf!r}, но HMI={hmi!r}",
                    )

    instances = document.get("instances")
    validation.require(isinstance(instances, dict), f"{path}: отсутствует instances")
    if isinstance(instances, dict):
        validation.require(instances.get("format") == "list", f"{path}: неверный instances.format")
        for index, row in enumerate(instances.get("rows", []), start=1):
            validation.require(
                isinstance(row, list) and len(row) == 2,
                f"{path}: Instances, строка {index} должна содержать имя и тип",
            )

    code = document.get("code")
    validation.require(isinstance(code, dict), f"{path}: отсутствует code")
    if isinstance(code, dict):
        validation.require(
            code.get("format") in {None, "template-text"},
            f"{path}: неверный code.format",
        )
        validation.require(
            code.get("language") in {"st-template", "scl"},
            f"{path}: неверный code.language",
        )
        validation.require(isinstance(code.get("text"), str), f"{path}: code.text должен быть строкой")

    known_params = parameter_keys(document)
    referenced_params = referenced_parameter_keys(document)
    unknown_params = sorted(referenced_params - known_params)
    validation.require(not unknown_params, f"{path}: неизвестные параметры: {', '.join(unknown_params)}")
    validation.require(
        all("MetaLib." not in value for value in iter_strings(document)),
        f"{path}: найден запрещённый префикс MetaLib.",
    )


def main() -> int:
    validation = Validation()
    try:
        config = load_config()
        components = discover_components()
        catalog = load_catalog()
    except (OSError, ValueError, yaml.YAMLError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    validation.require(bool(components), "Компоненты MetaKit не найдены")
    configured_roots = [str(value) for value in config.get("component_roots", [])]
    validation.require(
        configured_roots == ["LibTempls", "UnitsTmpls", "SysTmpls"],
        "metakit.yaml: component_roots должны сохранять порядок Lib, Units, Sys",
    )

    names: dict[str, str] = {}
    ids: dict[str, str] = {}
    slugs: dict[str, str] = {}
    for component in components:
        validate_component(validation, component)
        for value, owner, label in (
            (component.name, names, "имя"),
            (component.component_id, ids, "UUID"),
            (component.slug, slugs, "slug"),
        ):
            if value in owner:
                validation.errors.append(
                    f"{component.relative_path}: повторяется {label} {value!r}; впервые в {owner[value]}"
                )
            else:
                owner[value] = component.relative_path

    component_paths = {component.relative_path for component in components}
    catalog_paths = set(catalog)
    for missing in sorted(component_paths - catalog_paths):
        validation.errors.append(f"docs/catalog.yaml: нет описания {missing}")
    for extra in sorted(catalog_paths - component_paths):
        validation.errors.append(f"docs/catalog.yaml: лишнее описание {extra}")
    for path, item in catalog.items():
        for key in ("title", "category", "summary", "use_when"):
            validation.require(bool(str(item.get(key) or "").strip()), f"docs/catalog.yaml: {path}: пустое поле {key}")

    required_docs = [
        "docs/index.md",
        "docs/concepts/component-types.md",
        "docs/concepts/params-and-data.md",
        "docs/guides/custom-unit.md",
        "docs/guides/shared-configuration.md",
        "docs/guides/watchdog.md",
        "docs/deployment.md",
    ]
    for relative in required_docs:
        validation.require((REPOSITORY_ROOT / relative).is_file(), f"Отсутствует {relative}")

    if validation.errors:
        for error in validation.errors:
            print(f"ERROR: {error}", file=sys.stderr)
        print(f"MetaKit validation failed: {len(validation.errors)} error(s)", file=sys.stderr)
        return 1

    counts: dict[str, int] = {}
    for component in components:
        counts[component.template_kind] = counts.get(component.template_kind, 0) + 1
    summary = ", ".join(f"{key}={value}" for key, value in counts.items())
    print(f"MetaKit validation passed: {len(components)} components ({summary})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
