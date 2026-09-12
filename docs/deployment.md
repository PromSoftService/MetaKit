# Сборка и развёртывание документации

## Сборка

```bash
python -m pip install -r requirements-docs.txt
make verify
```

Результат создаётся в `dist/docs` и рассчитан на публикацию по адресу `/docs/`.

## Развёртывание на VPS

Содержимое `dist/docs` копируется в отдельный каталог, например:

```text
/srv/tenion/metakit-docs/current
```

Для атомарного обновления рекомендуется сначала распаковать новый build в каталог версии, проверить наличие `index.html` и `manifest.json`, затем заменить символическую ссылку `current`.

Пример маршрута Caddy:

```caddyfile
redir /docs /docs/ 308

handle_path /docs/* {
    root * /srv/tenion/metakit-docs/current
    try_files {path} {path}/index.html
    file_server
}

@metakit_downloads path /docs/downloads/*
header @metakit_downloads Content-Disposition "attachment"
```

## GitHub Actions

Workflow `.github/workflows/docs.yml` проверяет все YAML, собирает документацию и публикует artifact `metakit-docs`. Этот artifact можно скачать на VPS и развернуть без установки генератора документации на сервере.

Альтернативный вариант — клонировать MetaKit на VPS и выполнить `make verify`. Выходная структура в обоих случаях одинакова.
