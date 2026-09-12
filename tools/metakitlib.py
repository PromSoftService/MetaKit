from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DATA_COLUMNS = [
    "Type",
    "Data block",
    "Tag",
    "Value",
    "Comment",
    "HMI",
    "Flt",
    "Wrn",
    "Alm",
    "Trend",
    "Conf",
]
PARAM_TOKEN_RE = re.compile(r"\|([A-Za-z_$][A-Za-z0-9_$]*)\|")


@dataclass(frozen=True)
class ComponentSource:
    path: Path
    relative_path: str
    document: dict[str, Any]

    @property
    def name(self) -> str:
        return str(self.document["component"]["name"])

    @property
    def component_id(self) -> str:
        return str(self.document["component"]["id"])

    @property
    def template_kind(self) -> str:
        return self.relative_path.split("/", 1)[0]

    @property
    def slug(self) -> str:
        return slugify(self.name)


def load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: корень YAML должен быть объектом")
    return value


def load_config(root: Path = REPOSITORY_ROOT) -> dict[str, Any]:
    return load_yaml(root / "metakit.yaml")


def load_catalog(root: Path = REPOSITORY_ROOT) -> dict[str, dict[str, Any]]:
    value = load_yaml(root / "docs" / "catalog.yaml").get("components")
    if not isinstance(value, dict):
        raise ValueError("docs/catalog.yaml: отсутствует объект components")
    return {str(key): item for key, item in value.items() if isinstance(item, dict)}


def load_component_guide(slug: str, root: Path = REPOSITORY_ROOT) -> dict[str, Any] | None:
    path = root / "docs" / "components" / f"{slug}.yaml"
    if not path.is_file():
        return None
    return load_yaml(path)


def discover_components(root: Path = REPOSITORY_ROOT) -> list[ComponentSource]:
    config = load_config(root)
    components: list[ComponentSource] = []
    for root_name in config.get("component_roots", []):
        component_root = root / str(root_name)
        for path in sorted(component_root.rglob("*.yaml")):
            components.append(
                ComponentSource(
                    path=path,
                    relative_path=path.relative_to(root).as_posix(),
                    document=load_yaml(path),
                )
            )
    return components


def is_blank_row(row: Any) -> bool:
    return not isinstance(row, list) or all(not str(cell or "").strip() for cell in row)


def parameter_groups(document: dict[str, Any]) -> list[list[list[str]]]:
    params = document.get("params", {})
    rows = [params.get("header", []), *params.get("rows", [])]
    groups: list[list[list[str]]] = []
    current: list[list[str]] = []
    for raw_row in rows:
        if is_blank_row(raw_row):
            if current:
                groups.append(current)
                current = []
            continue
        current.append(["" if value is None else str(value) for value in raw_row])
    if current:
        groups.append(current)
    return groups


def parameter_keys(document: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    for group in parameter_groups(document):
        for key in group[0]:
            if key.strip():
                keys.add(key.strip())
    return keys


def parameter_defaults(document: dict[str, Any]) -> list[tuple[str, str, int]]:
    """Return parameter key, first-row default and group index in source order."""
    result: list[tuple[str, str, int]] = []
    for group_index, group in enumerate(parameter_groups(document), start=1):
        keys = group[0]
        values = group[1] if len(group) > 1 else []
        for index, key in enumerate(keys):
            if not key.strip():
                continue
            default = values[index] if index < len(values) else ""
            result.append((key.strip(), default, group_index))
    return result


def iter_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from iter_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from iter_strings(item)


def referenced_parameter_keys(document: dict[str, Any]) -> set[str]:
    result: set[str] = set()
    for value in iter_strings(document):
        result.update(PARAM_TOKEN_RE.findall(value))
    return result


def component_instances(document: dict[str, Any]) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    for row in document.get("instances", {}).get("rows", []):
        if isinstance(row, list) and len(row) >= 2 and str(row[1] or "").strip():
            result.append((str(row[0] or ""), str(row[1])))
    return result


def unique_blocks(document: dict[str, Any]) -> list[str]:
    return list(dict.fromkeys(block for _, block in component_instances(document)))


def non_blank_data_rows(document: dict[str, Any]) -> list[list[Any]]:
    return [row for row in document.get("data", {}).get("rows", []) if not is_blank_row(row)]


def slugify(value: str) -> str:
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", value)
    value = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1-\2", value)
    value = re.sub(r"[^A-Za-z0-9]+", "-", value)
    return value.strip("-").lower()


def template_kind_label(value: str) -> str:
    return {
        "LibTempls": "Lib",
        "UnitsTmpls": "Unit",
        "SysTmpls": "Sys",
    }.get(value, value)
