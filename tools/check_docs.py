from __future__ import annotations

import argparse
import json
import sys
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

from metakitlib import discover_components


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []
        self.download_links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        attribute = "href" if tag in {"a", "link"} else "src" if tag == "script" else None
        if attribute and values.get(attribute):
            self.links.append(str(values[attribute]))
        if tag == "a" and "download" in values and values.get("href"):
            self.download_links.append(str(values["href"]))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify built MetaKit documentation")
    parser.add_argument("output", nargs="?", default="dist/docs")
    parser.add_argument("--base-url", default="/docs/")
    return parser.parse_args()


def normalize_base_url(value: str) -> str:
    return "/" + value.strip("/") + "/"


def resolve_link(output: Path, base_url: str, link: str) -> Path | None:
    parsed = urlsplit(link)
    if parsed.scheme or parsed.netloc or link.startswith("mailto:"):
        return None
    path = unquote(parsed.path)
    if not path:
        return None
    if path.startswith("/"):
        if not path.startswith(base_url):
            raise ValueError(f"absolute link is outside base URL: {link}")
        path = path[len(base_url) :]
    candidate = output / path
    if path.endswith("/") or not Path(path).suffix:
        candidate = candidate / "index.html"
    return candidate


def main() -> int:
    args = parse_args()
    output = Path(args.output).resolve()
    base_url = normalize_base_url(args.base_url)
    errors: list[str] = []

    for required in ("index.html", "catalog.json", "manifest.json", "assets/styles.css", "assets/app.js"):
        if not (output / required).is_file():
            errors.append(f"missing required output: {required}")

    try:
        catalog = json.loads((output / "catalog.json").read_text(encoding="utf-8"))
        manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    sources = discover_components()
    source_paths = {component.relative_path for component in sources}
    catalog_paths = {str(component["relative_path"]) for component in catalog.get("components", [])}
    if source_paths != catalog_paths:
        errors.append("catalog.json component set differs from repository")
    if manifest.get("component_count") != len(sources):
        errors.append("manifest.json contains an invalid component_count")
    if catalog.get("base_url") != base_url:
        errors.append("catalog.json contains an invalid base_url")

    component_pages = list((output / "components").glob("*/index.html"))
    if len(component_pages) != len(sources):
        errors.append(f"component pages: {len(component_pages)} instead of {len(sources)}")

    html_paths = sorted(output.rglob("*.html"))
    download_links: list[str] = []
    for page in html_paths:
        parser = LinkParser()
        text = page.read_text(encoding="utf-8")
        parser.feed(text)
        if "{{" in text or "}}" in text:
            errors.append(f"unresolved template marker in {page.relative_to(output)}")
        for link in parser.links:
            try:
                target = resolve_link(output, base_url, link)
            except ValueError as error:
                errors.append(f"{page.relative_to(output)}: {error}")
                continue
            if target is not None and not target.exists():
                errors.append(
                    f"{page.relative_to(output)}: broken link {link} -> {target.relative_to(output)}"
                )
        download_links.extend(parser.download_links)

    if not download_links:
        errors.append("no download links found")

    archive_name = str(manifest.get("archive") or "")
    archive_path = output / "downloads" / archive_name
    if not archive_path.is_file():
        errors.append(f"missing archive: downloads/{archive_name}")
    else:
        try:
            with zipfile.ZipFile(archive_path) as archive:
                bad_file = archive.testzip()
                archived_components = {name for name in archive.namelist() if name.endswith(".yaml")}
                if bad_file:
                    errors.append(f"archive CRC error: {bad_file}")
                if archived_components != source_paths:
                    errors.append("archive component set differs from repository")
                if any(name.startswith("MetaKit") for name in archive.namelist()):
                    errors.append("archive contains an extra outer MetaKit directory")
        except zipfile.BadZipFile:
            errors.append(f"invalid archive: {archive_path.name}")

    for source in sources:
        download = output / "downloads" / "components" / source.relative_path
        if not download.is_file():
            errors.append(f"missing component download: {source.relative_path}")
        elif download.read_bytes() != source.path.read_bytes():
            errors.append(f"component download differs from source: {source.relative_path}")

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        print(f"Documentation verification failed: {len(errors)} error(s)", file=sys.stderr)
        return 1

    print(f"Documentation verification passed: {len(html_paths)} pages, {len(sources)} components")
    print(f"Archive verified: {archive_path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
