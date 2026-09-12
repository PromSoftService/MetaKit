from __future__ import annotations

import argparse
import json
import sys
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        attribute = "href" if tag in {"a", "link"} else "src" if tag == "script" else None
        if attribute and values.get(attribute):
            self.links.append(str(values[attribute]))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify the built MetaKit site")
    parser.add_argument("output", nargs="?", default="dist/docs")
    parser.add_argument("--base-url", default="/docs/")
    return parser.parse_args()


def normalize_base(value: str) -> str:
    return "/" + value.strip("/") + "/"


def resolve(output: Path, base: str, value: str) -> Path | None:
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or value.startswith(("mailto:", "#")):
        return None
    path = unquote(parsed.path)
    if not path:
        return None
    if path.startswith("/"):
        if not path.startswith(base):
            raise ValueError(f"absolute link outside base URL: {value}")
        path = path[len(base):]
    target = output / path
    if path.endswith("/") or not Path(path).suffix:
        target /= "index.html"
    return target


def main() -> int:
    options = parse_args()
    output = Path(options.output).resolve()
    base = normalize_base(options.base_url)
    errors: list[str] = []
    for required in ("index.html", "components/index.html", "manifest.json", "assets/styles.css", "assets/app.js"):
        if not (output / required).is_file():
            errors.append(f"missing required output: {required}")
    try:
        manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    components = manifest.get("components", [])
    if manifest.get("base_url") != base:
        errors.append("manifest contains an invalid base_url")
    if manifest.get("component_count") != len(components):
        errors.append("manifest contains an invalid component_count")

    required_sections = (
        "Описание", "Когда применять", "Применение", "Пример использования",
        "Настройки", "Теги для HMI и сообщения", "Частые ошибки",
    )
    for item in components:
        page = output / "components" / str(item["slug"]) / "index.html"
        if not page.is_file():
            errors.append(f"missing component page: {item['slug']}")
            continue
        text = page.read_text(encoding="utf-8")
        for section in required_sections:
            if f">{section}<" not in text:
                errors.append(f"components/{item['slug']}: missing section {section!r}")
        for forbidden in ("Исходная таблица", "ST-шаблон", "Экземпляры MetaLib"):
            if forbidden in text:
                errors.append(f"components/{item['slug']}: technical section leaked: {forbidden}")
        relative = str(item["source"]).removeprefix("yaml/")
        download = output / "downloads/components" / relative
        source = Path(__file__).resolve().parents[1] / str(item["source"])
        if not download.is_file():
            errors.append(f"missing component download: {relative}")
        elif download.read_bytes() != source.read_bytes():
            errors.append(f"component download differs from source: {relative}")

    html_files = sorted(output.rglob("*.html"))
    for page in html_files:
        parser = LinkParser()
        text = page.read_text(encoding="utf-8")
        parser.feed(text)
        if "{{" in text or "}}" in text:
            errors.append(f"unresolved template marker in {page.relative_to(output)}")
        for value in parser.links:
            try:
                target = resolve(output, base, value)
            except ValueError as error:
                errors.append(f"{page.relative_to(output)}: {error}")
                continue
            if target is not None and not target.exists():
                errors.append(f"{page.relative_to(output)}: broken link {value}")

    archive_name = str(manifest.get("archive", ""))
    archive_path = output / "downloads" / archive_name
    expected = {str(item["source"]).removeprefix("yaml/") for item in components}
    if not archive_path.is_file():
        errors.append(f"missing archive: {archive_name}")
    else:
        try:
            with zipfile.ZipFile(archive_path) as archive:
                archived = {name for name in archive.namelist() if name.endswith(".yaml")}
                if archive.testzip():
                    errors.append("archive CRC error")
                if archived != expected:
                    errors.append("archive component set differs from manifest")
                if any(name.startswith(("MetaKit", "yaml/")) for name in archive.namelist()):
                    errors.append("archive contains an extra outer directory")
        except zipfile.BadZipFile:
            errors.append(f"invalid archive: {archive_name}")

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        print(f"Documentation verification failed: {len(errors)} error(s)", file=sys.stderr)
        return 1
    print(f"Documentation verification passed: {len(html_files)} pages, {len(components)} components")
    print(f"Archive verified: {archive_name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
