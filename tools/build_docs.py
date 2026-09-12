from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import markdown

from metakitlib import (
    DATA_COLUMNS,
    REPOSITORY_ROOT,
    component_instances,
    discover_components,
    is_blank_row,
    load_catalog,
    load_config,
    non_blank_data_rows,
    parameter_groups,
    parameter_keys,
    template_kind_label,
    unique_blocks,
)


KIND_ORDER = {"LibTempls": 0, "UnitsTmpls": 1, "SysTmpls": 2}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build static MetaKit documentation")
    parser.add_argument("--output", default="dist/docs", help="Output directory")
    parser.add_argument("--base-url", default="/docs/", help="Public URL prefix")
    parser.add_argument("--timestamp", help="UTC timestamp in YYYYMMDD_HHMMSS format")
    return parser.parse_args()


def normalize_base_url(value: str) -> str:
    value = "/" + value.strip("/")
    return value + "/"


def clean_output(path: Path) -> None:
    resolved = path.resolve()
    if resolved == Path(resolved.anchor) or len(resolved.parts) < 3:
        raise ValueError(f"Refusing to clean unsafe output path: {resolved}")
    if resolved.exists():
        shutil.rmtree(resolved)
    resolved.mkdir(parents=True, exist_ok=True)


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8", newline="\n")


def url(base_url: str, relative: str = "") -> str:
    return base_url + relative.lstrip("/")


def markdown_html(path: Path, *, drop_first_heading: bool = False) -> str:
    source = path.read_text(encoding="utf-8")
    if drop_first_heading:
        source = re.sub(r"^#\s+.+?\n+", "", source, count=1)
    return markdown.markdown(source, extensions=["fenced_code", "tables", "toc"])


def component_href(base_url: str, component: dict[str, Any]) -> str:
    return url(base_url, f"components/{component['slug']}/")


def render_sidebar(base_url: str, active: str) -> str:
    items = [
        ("overview", "Обзор", ""),
        ("catalog", "Каталог компонентов", "components/"),
        ("types", "Типы компонентов", "concepts/component-types/"),
        ("params", "Params и Data", "concepts/params-and-data/"),
        ("custom", "Собственный контур", "guides/custom-unit/"),
        ("shared", "Общие настройки", "guides/shared-configuration/"),
        ("watchdog", "WatchDog", "guides/watchdog/"),
        ("deployment", "Сборка и развёртывание", "deployment/"),
    ]
    rows: list[str] = []
    current_group = ""
    groups = {
        "overview": "MetaKit",
        "types": "Основные понятия",
        "custom": "Руководства",
        "deployment": "Эксплуатация",
    }
    for key, label, href in items:
        if key in groups and groups[key] != current_group:
            current_group = groups[key]
            rows.append(f'<div class="sidebar-title">{html.escape(current_group)}</div>')
        class_name = "active" if active == key else ""
        rows.append(f'<a class="{class_name}" href="{url(base_url, href)}">{html.escape(label)}</a>')
    return "\n".join(rows)


def render_page(
    *,
    config: dict[str, Any],
    base_url: str,
    title: str,
    body: str,
    active: str,
    build_timestamp: str,
    description: str = "",
) -> str:
    page_title = f"{title} — MetaKit"
    description = description or str(config.get("description", ""))
    sidebar = render_sidebar(base_url, active)
    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="{html.escape(description, quote=True)}">
  <title>{html.escape(page_title)}</title>
  <link rel="stylesheet" href="{url(base_url, 'assets/styles.css')}">
</head>
<body>
  <header class="topbar">
    <a class="brand" href="{url(base_url)}">
      <span class="brand-mark">TENION</span>
      <span class="brand-divider"></span>
      <span class="brand-product">MetaKit</span>
    </a>
    <div class="top-meta">
      <span class="desktop-only">Версия {html.escape(str(config.get('version', 'current')))}</span>
      <button class="mobile-nav" type="button" data-mobile-nav>Меню</button>
    </div>
  </header>
  <div class="layout">
    <aside class="sidebar">{sidebar}</aside>
    <main class="content">
      {body}
      <footer class="footer">MetaKit {html.escape(str(config.get('version', 'current')))} · build {html.escape(build_timestamp)} · PromSoftService</footer>
    </main>
  </div>
  <script src="{url(base_url, 'assets/app.js')}"></script>
</body>
</html>
"""


def render_badge(kind: str) -> str:
    label = template_kind_label(kind)
    modifier = {"Unit": "badge-unit", "Sys": "badge-sys"}.get(label, "")
    return f'<span class="badge {modifier}">{html.escape(label)}</span>'


def render_component_card(component: dict[str, Any], base_url: str) -> str:
    search = " ".join(
        [
            component["name"],
            component["title"],
            component["summary"],
            component["category"],
            *component["blocks"],
        ]
    ).lower()
    badges = [render_badge(component["kind"])]
    badges.extend(f'<span class="badge">{html.escape(block)}</span>' for block in component["blocks"][:3])
    return f"""
<a class="card component-card" href="{component_href(base_url, component)}"
   data-search="{html.escape(search, quote=True)}"
   data-kind="{html.escape(template_kind_label(component['kind']))}"
   data-category="{html.escape(component['category'], quote=True)}">
  <div class="badges">{''.join(badges)}</div>
  <h3>{html.escape(component['title'])}</h3>
  <p>{html.escape(component['summary'])}</p>
  <div class="card-path">{html.escape(component['relative_path'])}</div>
</a>
"""


def render_stats(items: list[tuple[str, str]]) -> str:
    return '<div class="stats">' + "".join(
        f'<div class="stat"><span class="stat-value">{html.escape(value)}</span><span class="stat-label">{html.escape(label)}</span></div>'
        for value, label in items
    ) + "</div>"


def render_parameter_groups(document: dict[str, Any]) -> str:
    sections: list[str] = []
    for index, group in enumerate(parameter_groups(document), start=1):
        keys = group[0]
        value_rows = group[1:] or [[""] * len(keys)]
        first_key = next((value for value in keys if value), "")
        first_value = value_rows[0][0] if value_rows and value_rows[0] else ""
        title = first_value if first_key.startswith("$") and first_value else f"Группа параметров {index}"
        header_cells = "".join(f"<th><code>{html.escape(key)}</code></th>" for key in keys)
        rows: list[str] = []
        for row in value_rows:
            padded = [*row, *([""] * max(0, len(keys) - len(row)))]
            rows.append("<tr>" + "".join(f"<td><code>{html.escape(value)}</code></td>" for value in padded[: len(keys)]) + "</tr>")
        sections.append(
            f'<h3>{html.escape(title)}</h3><div class="table-wrap"><table><thead><tr>{header_cells}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>'
        )
    return "".join(sections)


def render_data_table(document: dict[str, Any]) -> str:
    header_cells = "".join(f"<th>{html.escape(column)}</th>" for column in DATA_COLUMNS)
    body_rows: list[str] = []
    code_columns = {"Type", "Data block", "Tag", "Value", "HMI", "Flt", "Wrn", "Alm", "Trend", "Conf"}
    for raw_row in document.get("data", {}).get("rows", []):
        if is_blank_row(raw_row):
            body_rows.append(f'<tr class="separator-row"><td colspan="{len(DATA_COLUMNS)}"></td></tr>')
            continue
        row = [*raw_row, *([""] * max(0, len(DATA_COLUMNS) - len(raw_row)))]
        cells: list[str] = []
        for column, value in zip(DATA_COLUMNS, row):
            value_text = "" if value is None else str(value)
            rendered = html.escape(value_text)
            if value_text and column in code_columns:
                rendered = f"<code>{rendered}</code>"
            cells.append(f"<td>{rendered}</td>")
        body_rows.append("<tr>" + "".join(cells) + "</tr>")
    return f'<div class="table-wrap"><table><thead><tr>{header_cells}</tr></thead><tbody>{"".join(body_rows)}</tbody></table></div>'


def render_instances(document: dict[str, Any]) -> str:
    rows = component_instances(document)
    if not rows:
        return "<p>Компонент не создаёт экземпляры функциональных блоков.</p>"
    body = "".join(
        f"<tr><td><code>{html.escape(name)}</code></td><td><code>{html.escape(block)}</code></td></tr>"
        for name, block in rows
    )
    return f'<div class="table-wrap"><table><thead><tr><th>Экземпляр</th><th>Тип MetaLib</th></tr></thead><tbody>{body}</tbody></table></div>'


def render_component_page(
    component: dict[str, Any],
    all_components: list[dict[str, Any]],
    *,
    config: dict[str, Any],
    base_url: str,
    build_timestamp: str,
) -> str:
    document = component["document"]
    download_url = url(base_url, f"downloads/components/{component['relative_path']}")
    block_badges = "".join(f'<span class="badge">{html.escape(block)}</span>' for block in component["blocks"])
    related = [
        item for item in all_components
        if item["relative_path"] != component["relative_path"] and item["category"] == component["category"]
    ][:4]
    related_html = "".join(render_component_card(item, base_url) for item in related)
    code = str(document.get("code", {}).get("text", ""))
    code_id = f"code-{component['slug']}"
    body = f"""
<div class="breadcrumbs"><a href="{url(base_url)}">MetaKit</a><span>/</span><a href="{url(base_url, 'components/')}">Компоненты</a><span>/</span>{html.escape(component['name'])}</div>
<section class="hero">
  <div class="eyebrow">{render_badge(component['kind'])} {html.escape(component['category'])}</div>
  <h1>{html.escape(component['title'])}</h1>
  <p class="lead">{html.escape(component['summary'])}</p>
  <div class="badges">{block_badges}</div>
  <div class="hero-actions">
    <a class="button button-primary" href="{download_url}" download>Скачать YAML</a>
    <a class="button" href="#params">Параметры</a>
    <a class="button" href="#code">ST-шаблон</a>
  </div>
</section>
<div class="callout"><strong>Когда использовать:</strong> {html.escape(component['use_when'])}</div>
{render_stats([
    (str(len(parameter_keys(document))), "параметров"),
    (str(len(non_blank_data_rows(document))), "строк Data"),
    (str(len(component_instances(document))), "экземпляров"),
    (template_kind_label(component['kind']), "уровень"),
])}
<h2 id="params">Таблица параметров</h2>
<p>Группы и значения приведены в том же порядке, что и в исходном компоненте MetaGen.</p>
{render_parameter_groups(document)}
<h2>Таблица данных</h2>
<p>Пустые строки сохраняют смысловое разделение настроек и тегов функциональных блоков.</p>
{render_data_table(document)}
<h2>Экземпляры</h2>
{render_instances(document)}
<h2 id="code">ST-шаблон</h2>
<details>
  <summary>Показать исходный шаблон генерации</summary>
  <div class="code-shell"><button class="copy-button" type="button" data-copy="{code_id}">Копировать</button><pre><code id="{code_id}">{html.escape(code)}</code></pre></div>
</details>
<h2>Исходный файл</h2>
<p><code>{html.escape(component['relative_path'])}</code></p>
<p>UUID компонента: <code>{html.escape(str(document['component']['id']))}</code></p>
{f'<h2>Похожие компоненты</h2><div class="cards">{related_html}</div>' if related_html else ''}
"""
    return render_page(
        config=config,
        base_url=base_url,
        title=component["title"],
        body=body,
        active="catalog",
        build_timestamp=build_timestamp,
        description=component["summary"],
    )


def render_catalog_page(
    components: list[dict[str, Any]],
    *,
    config: dict[str, Any],
    base_url: str,
    archive_name: str,
    build_timestamp: str,
) -> str:
    categories = sorted({component["category"] for component in components})
    category_options = "".join(f'<option value="{html.escape(value, quote=True)}">{html.escape(value)}</option>' for value in categories)
    cards = "".join(render_component_card(component, base_url) for component in components)
    body = f"""
<div class="breadcrumbs"><a href="{url(base_url)}">MetaKit</a><span>/</span>Компоненты</div>
<section class="hero">
  <div class="eyebrow">Справочник</div>
  <h1>Каталог компонентов</h1>
  <p class="lead">Актуальные Lib, Unit и Sys-компоненты MetaKit. Каждая страница построена непосредственно из исходного YAML.</p>
  <div class="hero-actions"><a class="button button-primary" href="{url(base_url, f'downloads/{archive_name}')}" download>Скачать весь MetaKit</a></div>
</section>
<div class="search-panel">
  <input type="search" placeholder="Компонент, блок или назначение" aria-label="Поиск компонентов" data-component-search>
  <select aria-label="Тип компонента" data-kind-filter><option value="">Все типы</option><option>Lib</option><option>Unit</option><option>Sys</option></select>
  <select aria-label="Категория" data-category-filter><option value="">Все категории</option>{category_options}</select>
</div>
<div class="cards">{cards}</div>
<div class="empty-state" data-empty-state>Компоненты по заданным условиям не найдены.</div>
"""
    return render_page(
        config=config,
        base_url=base_url,
        title="Каталог компонентов",
        body=body,
        active="catalog",
        build_timestamp=build_timestamp,
    )


def render_home_page(
    components: list[dict[str, Any]],
    *,
    config: dict[str, Any],
    base_url: str,
    archive_name: str,
    build_timestamp: str,
) -> str:
    counts = {
        kind: sum(component["kind"] == kind for component in components)
        for kind in ("LibTempls", "UnitsTmpls", "SysTmpls")
    }
    intro = markdown_html(REPOSITORY_ROOT / "docs" / "index.md", drop_first_heading=True)
    featured_names = {"Engine", "PidEngineUnit", "General", "WDMaster"}
    featured = [component for component in components if component["name"] in featured_names]
    cards = "".join(render_component_card(component, base_url) for component in featured)
    body = f"""
<section class="hero">
  <div class="eyebrow">Компоненты MetaGen</div>
  <h1>MetaKit</h1>
  <p class="lead">Стандартные блоки, готовые контуры управления и системные компоненты для предсказуемой генерации PLC-проектов.</p>
  <div class="hero-actions">
    <a class="button button-primary" href="{url(base_url, 'components/')}">Открыть каталог</a>
    <a class="button" href="{url(base_url, f'downloads/{archive_name}')}" download>Скачать MetaKit</a>
  </div>
</section>
{render_stats([
    (str(len(components)), "компонентов"),
    (str(counts['LibTempls']), "Lib-шаблона"),
    (str(counts['UnitsTmpls']), "Unit-компонентов"),
    (str(counts['SysTmpls']), "Sys-компонента"),
])}
{intro}
<h2>Основные компоненты</h2>
<div class="cards">{cards}</div>
"""
    return render_page(
        config=config,
        base_url=base_url,
        title="Документация",
        body=body,
        active="overview",
        build_timestamp=build_timestamp,
    )


def build_markdown_pages(
    output: Path,
    *,
    config: dict[str, Any],
    base_url: str,
    build_timestamp: str,
) -> None:
    routes = {
        "docs/concepts/component-types.md": ("concepts/component-types/index.html", "Типы компонентов", "types"),
        "docs/concepts/params-and-data.md": ("concepts/params-and-data/index.html", "Params и Data", "params"),
        "docs/guides/custom-unit.md": ("guides/custom-unit/index.html", "Сборка собственного контура", "custom"),
        "docs/guides/shared-configuration.md": ("guides/shared-configuration/index.html", "Общие настройки", "shared"),
        "docs/guides/watchdog.md": ("guides/watchdog/index.html", "WatchDog", "watchdog"),
        "docs/deployment.md": ("deployment/index.html", "Сборка и развёртывание", "deployment"),
    }
    for source, (target, title, active) in routes.items():
        body = f'<div class="breadcrumbs"><a href="{url(base_url)}">MetaKit</a><span>/</span>{html.escape(title)}</div>'
        body += markdown_html(REPOSITORY_ROOT / source)
        write_text(
            output / target,
            render_page(
                config=config,
                base_url=base_url,
                title=title,
                body=body,
                active=active,
                build_timestamp=build_timestamp,
            ),
        )


def create_archive(output: Path, components: list[dict[str, Any]], archive_name: str, timestamp: str) -> None:
    archive_path = output / "downloads" / archive_name
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.strptime(timestamp, "%Y%m%d_%H%M%S")
    zip_stamp = (stamp.year, stamp.month, stamp.day, stamp.hour, stamp.minute, stamp.second)
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        directories: set[str] = set()
        for component in components:
            path = component["source"].path
            relative = component["relative_path"]
            parent = Path(relative).parent
            for directory in [parent, *parent.parents]:
                value = directory.as_posix().strip(".")
                if value:
                    directories.add(value.rstrip("/") + "/")
        for directory in sorted(directories):
            info = zipfile.ZipInfo(directory, date_time=zip_stamp)
            info.external_attr = 0o40755 << 16
            archive.writestr(info, b"")
        for component in components:
            info = zipfile.ZipInfo(component["relative_path"], date_time=zip_stamp)
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, component["source"].path.read_bytes())


def main() -> int:
    args = parse_args()
    base_url = normalize_base_url(args.base_url)
    timestamp = args.timestamp or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    if not re.fullmatch(r"\d{8}_\d{6}", timestamp):
        print("--timestamp must match YYYYMMDD_HHMMSS", file=sys.stderr)
        return 2
    try:
        datetime.strptime(timestamp, "%Y%m%d_%H%M%S")
    except ValueError as error:
        print(f"Invalid --timestamp: {error}", file=sys.stderr)
        return 2

    config = load_config()
    catalog = load_catalog()
    sources = discover_components()
    output = (REPOSITORY_ROOT / args.output).resolve() if not Path(args.output).is_absolute() else Path(args.output).resolve()
    clean_output(output)

    components: list[dict[str, Any]] = []
    for source in sources:
        item = catalog[source.relative_path]
        components.append(
            {
                "source": source,
                "document": source.document,
                "relative_path": source.relative_path,
                "name": source.name,
                "slug": source.slug,
                "kind": source.template_kind,
                "title": str(item["title"]),
                "category": str(item["category"]),
                "summary": str(item["summary"]),
                "use_when": str(item["use_when"]),
                "blocks": unique_blocks(source.document),
            }
        )
    components.sort(key=lambda item: (KIND_ORDER.get(item["kind"], 99), item["category"], item["title"]))

    archive_name = f"{config.get('archive_prefix', 'MetaKit')}_{timestamp}.zip"
    build_timestamp = datetime.strptime(timestamp, "%Y%m%d_%H%M%S").replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")

    shutil.copytree(REPOSITORY_ROOT / "docs" / "assets", output / "assets")
    for component in components:
        target = output / "downloads" / "components" / component["relative_path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(component["source"].path, target)

    create_archive(output, components, archive_name, timestamp)
    build_markdown_pages(output, config=config, base_url=base_url, build_timestamp=build_timestamp)

    write_text(
        output / "index.html",
        render_home_page(
            components,
            config=config,
            base_url=base_url,
            archive_name=archive_name,
            build_timestamp=build_timestamp,
        ),
    )
    write_text(
        output / "components" / "index.html",
        render_catalog_page(
            components,
            config=config,
            base_url=base_url,
            archive_name=archive_name,
            build_timestamp=build_timestamp,
        ),
    )
    for component in components:
        write_text(
            output / "components" / component["slug"] / "index.html",
            render_component_page(
                component,
                components,
                config=config,
                base_url=base_url,
                build_timestamp=build_timestamp,
            ),
        )

    catalog_payload = {
        "name": config.get("name", "MetaKit"),
        "version": config.get("version", "current"),
        "built_at": build_timestamp,
        "base_url": base_url,
        "archive": f"downloads/{archive_name}",
        "components": [
            {
                key: component[key]
                for key in ("name", "slug", "kind", "title", "category", "summary", "use_when", "blocks", "relative_path")
            }
            for component in components
        ],
    }
    write_text(output / "catalog.json", json.dumps(catalog_payload, ensure_ascii=False, indent=2) + "\n")
    manifest = {
        "schema": 1,
        "name": config.get("name", "MetaKit"),
        "version": config.get("version", "current"),
        "built_at": build_timestamp,
        "base_url": base_url,
        "component_count": len(components),
        "archive": archive_name,
    }
    write_text(output / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")

    print(f"Built {len(components)} component pages in {output}")
    print(f"Archive: {archive_name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
