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
import yaml


ROOT = Path(__file__).resolve().parents[1]
KIND_ORDER = {"Lib": 0, "Unit": 1, "Sys": 2}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the MetaKit documentation site")
    parser.add_argument("--output", default="dist/docs")
    parser.add_argument("--base-url", default="/docs/")
    parser.add_argument("--timestamp", help="UTC timestamp: YYYYMMDD_HHMMSS")
    return parser.parse_args()


def esc(value: Any, *, quote: bool = False) -> str:
    return html.escape(str(value or ""), quote=quote)


def normalize_base(value: str) -> str:
    return "/" + value.strip("/") + "/"


def link(base: str, relative: str = "") -> str:
    return base + relative.lstrip("/")


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def clean_output(path: Path) -> None:
    resolved = path.resolve()
    if resolved == Path(resolved.anchor) or len(resolved.parts) < 3:
        raise ValueError(f"Unsafe output path: {resolved}")
    if resolved.exists():
        shutil.rmtree(resolved)
    resolved.mkdir(parents=True)


def load_yaml(path: Path) -> dict[str, Any]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"Expected a mapping in {path}")
    return document


def load_guides() -> list[dict[str, Any]]:
    guides = []
    for path in sorted((ROOT / "docs/components").glob("*.yaml")):
        guide = load_yaml(path)
        guide["guide_path"] = path.relative_to(ROOT).as_posix()
        guides.append(guide)
    return sorted(guides, key=lambda item: (
        KIND_ORDER.get(str(item.get("kind")), 99),
        str(item.get("category")),
        str(item.get("title")),
    ))


def markdown_file(path: Path) -> str:
    return markdown.markdown(path.read_text(encoding="utf-8"), extensions=["fenced_code", "tables", "toc"])


def badge(kind: str) -> str:
    modifier = {"Unit": " badge-unit", "Sys": " badge-sys"}.get(kind, "")
    return f'<span class="badge{modifier}">{esc(kind)}</span>'


def sidebar(base: str, active: str) -> str:
    groups = [
        ("MetaKit", [("overview", "Обзор", ""), ("catalog", "Компоненты", "components/")]),
        ("Основные понятия", [("types", "Типы компонентов", "concepts/component-types/")]),
        ("Руководства", [
            ("custom", "Собственный контур", "guides/custom-unit/"),
            ("shared", "Общие настройки", "guides/shared-configuration/"),
            ("watchdog", "WatchDog", "guides/watchdog/"),
        ]),
        ("Эксплуатация", [("deployment", "Сборка и развёртывание", "deployment/")]),
    ]
    rows = []
    for title, items in groups:
        rows.append(f'<div class="sidebar-title">{esc(title)}</div>')
        for key, label, target in items:
            current = " active" if key == active else ""
            rows.append(f'<a class="sidebar-link{current}" href="{link(base, target)}">{esc(label)}</a>')
    return "".join(rows)


def page(*, config: dict[str, Any], base: str, title: str, body: str, active: str, built_at: str, description: str = "") -> str:
    return f'''<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="description" content="{esc(description or config.get('description'), quote=True)}">
  <title>{esc(title)} — MetaKit</title>
  <link rel="stylesheet" href="{link(base, 'assets/styles.css')}">
</head>
<body>
  <header class="topbar">
    <a class="brand" href="{base}"><span class="brand-product">MetaKit</span><span class="brand-note">документация</span></a>
    <button class="nav-button" type="button" data-mobile-nav>Меню</button>
  </header>
  <div class="layout">
    <aside class="sidebar" data-sidebar>{sidebar(base, active)}</aside>
    <main class="content">{body}
      <footer class="footer">MetaKit · версия {esc(config.get('version', 'current'))} · {esc(built_at)}</footer>
    </main>
  </div>
  <script src="{link(base, 'assets/app.js')}"></script>
</body>
</html>'''


def list_html(items: Any) -> str:
    if not isinstance(items, list):
        return ""
    return '<ul class="plain-list">' + "".join(f"<li>{esc(item)}</li>" for item in items) + "</ul>"


def guide_link(base: str, guide: dict[str, Any]) -> str:
    return link(base, f"components/{guide['slug']}/")


def source_relative(guide: dict[str, Any]) -> str:
    return str(guide["source"]).removeprefix("yaml/")


def card(base: str, guide: dict[str, Any]) -> str:
    search = " ".join(str(guide.get(key, "")) for key in ("component", "title", "category", "summary")).lower()
    return f'''<a class="component-card" href="{guide_link(base, guide)}" data-search="{esc(search, quote=True)}" data-kind="{esc(guide['kind'], quote=True)}">
  <div class="card-meta">{badge(str(guide['kind']))}<span>{esc(guide['category'])}</span></div>
  <h3>{esc(guide['title'])}</h3>
  <p>{esc(guide['summary'])}</p>
  <span class="card-code">{esc(guide['component'])}</span>
</a>'''


def render_diagram(guide: dict[str, Any]) -> str:
    lanes = guide.get("diagram", {}).get("lanes", [])
    rendered = []
    for lane_index, lane in enumerate(lanes):
        if not isinstance(lane, list) or not lane:
            continue
        width, node_height = 920, 92
        node_width = min(190, max(130, int((width - 48 - (len(lane) - 1) * 52) / len(lane))))
        gap = (width - 48 - node_width * len(lane)) / max(1, len(lane) - 1)
        marker = f"arrow-{guide['slug']}-{lane_index}"
        parts = [
            f'<svg class="flow-svg" viewBox="0 0 {width} 140" role="img" aria-label="Схема обработки">',
            f'<defs><marker id="{marker}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M 0 0 L 10 5 L 0 10 z"/></marker></defs>',
        ]
        for index, label in enumerate(lane):
            x, y = 24 + index * (node_width + gap), 24
            css = "flow-node flow-hmi" if "HMI" in str(label) else "flow-node"
            lines = [part.strip() for part in str(label).splitlines() if part.strip()]
            parts.append(f'<rect class="{css}" x="{x:.1f}" y="{y}" width="{node_width}" height="{node_height}" rx="5"/>')
            start_y = y + 39 - (len(lines) - 1) * 10
            for line_no, text in enumerate(lines[:3]):
                class_name = "flow-title" if line_no == 0 else "flow-label"
                parts.append(f'<text class="{class_name}" x="{x + node_width / 2:.1f}" y="{start_y + line_no * 22}">{esc(text)}</text>')
            if index < len(lane) - 1:
                parts.append(f'<line class="flow-arrow" x1="{x + node_width + 6:.1f}" y1="70" x2="{x + node_width + gap - 7:.1f}" y2="70" marker-end="url(#{marker})"/>')
        parts.append("</svg>")
        rendered.append('<div class="flow-lane">' + "".join(parts) + "</div>")
    return '<div class="flow-diagram">' + "".join(rendered) + "</div>" if rendered else ""


def render_parameter_groups(groups: Any) -> str:
    result = []
    group_index = 0
    for group in groups or []:
        items = [item for item in group.get("items", []) if not str(item.get("key", "")).startswith("$")]
        if not items:
            continue
        group_index += 1
        title = str(group.get("title", ""))
        if title.startswith("Группа параметров") and items:
            first = str(items[0].get("key", ""))
            if first.startswith("Eng"):
                title = "Подключение двигателя"
            elif first.startswith("Valve"):
                title = "Подключение клапана"
            elif first.startswith("CtrlValve"):
                title = "Подключение регулирующего клапана"
            elif first.startswith(("PID", "PIDD", "Sens")):
                title = "Измерение и регулятор"
            elif first.startswith("Out"):
                title = "Подключение аналогового выхода"
            elif first.startswith("Flt"):
                match = re.search(r"(\d+)$", first)
                title = f"Аварийный сигнал {match.group(1)}" if match else "Аварийные сигналы"
            elif first.startswith("Wrn"):
                match = re.search(r"(\d+)$", first)
                title = f"Предупреждение {match.group(1)}" if match else "Предупреждения"
            else:
                title = "Подключение и команды"
        if not re.match(r"^\d+\.\s", title):
            title = f"{group_index}. {title}"
        keys = "".join(f'<th><code>{esc(item.get("key"))}</code></th>' for item in items)
        values = "".join(f'<td><code>{esc(item.get("example", item.get("default")))}</code></td>' for item in items)
        details = "".join(
            f'<div class="parameter-description"><code>{esc(item.get("key"))}</code><p>{esc(item.get("description"))}</p></div>'
            for item in items
        )
        intro = f'<p class="parameter-intro">{esc(group.get("intro"))}</p>' if group.get("intro") else ""
        result.append(f'<section class="parameter-group"><h3>{esc(title)}</h3>{intro}<div class="parameter-strip"><table class="parameter-table"><thead><tr>{keys}</tr></thead><tbody><tr>{values}</tr></tbody></table></div><div class="parameter-details">{details}</div></section>')
    return "".join(result)


def human_cell(value: Any, field: str) -> str:
    text = str(value or "")
    if field == "default":
        match = re.fullmatch(r'%"" if .+ else "([^"]*)"%', text)
        if match:
            text = match.group(1)
    if field in {"key", "tag", "source"}:
        text = text.removesuffix('"%')
        text = re.sub(r"\|([^|]+)\|", r"<\1>", text)
    return text


def render_table(rows: Any, headers: tuple[str, ...], fields: tuple[str, ...], *, empty: str = "Нет отдельных тегов в этой группе.") -> str:
    if not rows:
        return f'<p class="empty-note">{esc(empty)}</p>'
    head = "".join(f"<th>{esc(item)}</th>" for item in headers)
    body = []
    for row in rows:
        cells = []
        for field in fields:
            value = human_cell(row.get(field, ""), field)
            is_code = field in {"key", "tag", "default", "flag", "source"}
            content = f"<code>{esc(value)}</code>" if is_code and value != "" else esc(value)
            cells.append(f"<td>{content}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    return f'<div class="table-wrap"><table><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'


def component_page(guide: dict[str, Any], guides: list[dict[str, Any]], *, config: dict[str, Any], base: str, built_at: str) -> str:
    source_link = link(base, f"downloads/components/{source_relative(guide)}")
    application = guide.get("application", {})
    example = guide.get("example", {})
    related = [item for item in guides if item["slug"] != guide["slug"] and item.get("category") == guide.get("category")][:3]
    related_html = "" if not related else '<section><h2>Похожие компоненты</h2><div class="component-grid">' + "".join(card(base, item) for item in related) + "</div></section>"
    body = f'''
<nav class="breadcrumbs"><a href="{base}">MetaKit</a><span>/</span><a href="{link(base, 'components/')}">Компоненты</a><span>/</span>{esc(guide['title'])}</nav>
<header class="document-header">
  <div class="document-meta">{badge(str(guide['kind']))}<span>{esc(guide['category'])}</span><code>{esc(guide['component'])}</code></div>
  <h1>{esc(guide['title'])}</h1><p class="lead">{esc(guide['summary'])}</p>
  <a class="button" href="{source_link}" download>Скачать компонент YAML</a>
</header>
<section><h2>Описание</h2><p>{esc(guide['description'])}</p>{render_diagram(guide)}</section>
<section><h2>Когда применять</h2><div class="usage-grid"><article><h3>Подходит</h3>{list_html(guide.get('use_cases'))}</article><article><h3>Не подходит</h3>{list_html(guide.get('not_for'))}</article></div></section>
<section id="application"><h2>Применение</h2><p>{esc(application.get('intro'))}</p>{render_parameter_groups(guide.get('parameter_groups'))}<div class="result"><strong>Что получится</strong><p>{esc(application.get('result'))}</p></div></section>
<section><h2>Пример использования</h2><article class="example"><h3>{esc(example.get('title'))}</h3><p>{esc(example.get('scenario'))}</p><div class="result"><strong>Результат</strong><p>{esc(example.get('result'))}</p></div></article></section>
<section><h2>Настройки</h2><p>Эти значения создаются в области конфигурации и могут использоваться на HMI для наладки.</p>{render_table(guide.get('settings'), ('Тег настройки', 'По умолчанию', 'Назначение'), ('key', 'default', 'description'))}</section>
<section><h2>Теги для HMI и сообщения</h2><p>Рабочие значения, состояния и сообщения, которые компонент предлагает вывести оператору.</p>{render_table(guide.get('hmi'), ('Тег', 'HMI', 'Flt', 'Wrn', 'Alm', 'Trend', 'Назначение'), ('tag', 'hmi', 'flt', 'wrn', 'alm', 'trend', 'description'))}</section>
<section><h2>Дополнительные теги HMI</h2>{render_table(guide.get('optional_hmi'), ('Тег', 'Назначение'), ('tag', 'description'), empty='Дополнительные теги не требуются.')}</section>
<section><h2>Частые ошибки</h2><div class="note warning">{list_html(guide.get('common_mistakes'))}</div></section>
{related_html}'''
    return page(config=config, base=base, title=str(guide["title"]), body=body, active="catalog", built_at=built_at, description=str(guide["summary"]))


def catalog_page(guides: list[dict[str, Any]], *, config: dict[str, Any], base: str, archive: str, built_at: str) -> str:
    cards = "".join(card(base, item) for item in guides)
    body = f'''<nav class="breadcrumbs"><a href="{base}">MetaKit</a><span>/</span>Компоненты</nav>
<header class="document-header"><p class="overline">Справочник MetaKit</p><h1>Компоненты</h1><p class="lead">Готовые компоненты MetaGen с понятным описанием применения, параметров, настроек и данных для HMI.</p><a class="button" href="{link(base, 'downloads/' + archive)}" download>Скачать MetaKit</a></header>
<div class="catalog-tools"><input type="search" placeholder="Найти компонент" aria-label="Найти компонент" data-component-search><div class="filter-buttons"><button class="filter active" data-kind-button="">Все</button><button class="filter" data-kind-button="Lib">Lib</button><button class="filter" data-kind-button="Unit">Unit</button><button class="filter" data-kind-button="Sys">Sys</button></div></div>
<div class="component-grid" data-component-grid>{cards}</div><p class="empty-note" data-empty-state hidden>Ничего не найдено.</p>'''
    return page(config=config, base=base, title="Компоненты", body=body, active="catalog", built_at=built_at)


def home_page(guides: list[dict[str, Any]], *, config: dict[str, Any], base: str, archive: str, built_at: str) -> str:
    counts = {kind: sum(item.get("kind") == kind for item in guides) for kind in KIND_ORDER}
    featured_names = {"Sensor", "Engine", "PidEngineUnit", "General", "WDMaster"}
    featured = [item for item in guides if item.get("component") in featured_names]
    body = f'''<header class="home-header"><p class="overline">MetaGen component kit</p><h1>MetaKit</h1><p class="lead">Документация по стандартным компонентам автоматизации: от отдельного датчика до готового контура управления.</p><div class="header-actions"><a class="button primary" href="{link(base, 'components/')}">Открыть каталог</a><a class="button" href="{link(base, 'downloads/' + archive)}" download>Скачать MetaKit</a></div></header>
<div class="stats"><div><strong>{len(guides)}</strong><span>компонентов</span></div><div><strong>{counts['Lib']}</strong><span>Lib</span></div><div><strong>{counts['Unit']}</strong><span>Unit</span></div><div><strong>{counts['Sys']}</strong><span>Sys</span></div></div>
<section class="prose">{markdown_file(ROOT / 'docs/index.md')}</section><section><h2>С чего начать</h2><div class="component-grid">{"".join(card(base, item) for item in featured)}</div></section>'''
    return page(config=config, base=base, title="Документация", body=body, active="overview", built_at=built_at)


def build_markdown_pages(output: Path, *, config: dict[str, Any], base: str, built_at: str) -> None:
    routes = {
        "docs/concepts/component-types.md": ("concepts/component-types/index.html", "Типы компонентов", "types"),
        "docs/guides/custom-unit.md": ("guides/custom-unit/index.html", "Собственный контур", "custom"),
        "docs/guides/shared-configuration.md": ("guides/shared-configuration/index.html", "Общие настройки", "shared"),
        "docs/guides/watchdog.md": ("guides/watchdog/index.html", "WatchDog", "watchdog"),
        "docs/deployment.md": ("deployment/index.html", "Сборка и развёртывание", "deployment"),
    }
    for source, (target, title, active) in routes.items():
        content = f'<nav class="breadcrumbs"><a href="{base}">MetaKit</a><span>/</span>{esc(title)}</nav><article class="prose">{markdown_file(ROOT / source)}</article>'
        write(output / target, page(config=config, base=base, title=title, body=content, active=active, built_at=built_at))


def create_archive(output: Path, guides: list[dict[str, Any]], filename: str, timestamp: str) -> None:
    target = output / "downloads" / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.strptime(timestamp, "%Y%m%d_%H%M%S")
    zip_stamp = (stamp.year, stamp.month, stamp.day, stamp.hour, stamp.minute, stamp.second)
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for guide in guides:
            source = ROOT / str(guide["source"])
            info = zipfile.ZipInfo(source_relative(guide), zip_stamp)
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, source.read_bytes())


def main() -> int:
    options = parse_args()
    base = normalize_base(options.base_url)
    timestamp = options.timestamp or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    if not re.fullmatch(r"\d{8}_\d{6}", timestamp):
        print("--timestamp must match YYYYMMDD_HHMMSS", file=sys.stderr)
        return 2
    try:
        parsed = datetime.strptime(timestamp, "%Y%m%d_%H%M%S")
    except ValueError as error:
        print(f"Invalid --timestamp: {error}", file=sys.stderr)
        return 2
    config = load_yaml(ROOT / "metakit.yaml")
    guides = load_guides()
    output = Path(options.output)
    output = output.resolve() if output.is_absolute() else (ROOT / output).resolve()
    clean_output(output)
    shutil.copytree(ROOT / "docs/assets", output / "assets")
    for guide in guides:
        source = ROOT / str(guide["source"])
        target = output / "downloads/components" / source_relative(guide)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    archive = f"{config.get('archive_prefix', 'MetaKit')}_{timestamp}.zip"
    create_archive(output, guides, archive, timestamp)
    built_at = parsed.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
    build_markdown_pages(output, config=config, base=base, built_at=built_at)
    write(output / "index.html", home_page(guides, config=config, base=base, archive=archive, built_at=built_at))
    write(output / "components/index.html", catalog_page(guides, config=config, base=base, archive=archive, built_at=built_at))
    for guide in guides:
        write(output / f"components/{guide['slug']}/index.html", component_page(guide, guides, config=config, base=base, built_at=built_at))
    manifest = {
        "schema": 2,
        "name": config.get("name", "MetaKit"),
        "version": config.get("version", "current"),
        "built_at": built_at,
        "base_url": base,
        "component_count": len(guides),
        "archive": archive,
        "components": [{"component": item["component"], "slug": item["slug"], "kind": item["kind"], "source": item["source"]} for item in guides],
    }
    write(output / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(f"Built {len(guides)} component pages in {output}")
    print(f"Archive: {archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
