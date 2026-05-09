# STO CRM — release-only repository

Этот репозиторий предназначен только для готовых релизных билдов СТО CRM и метаданных обновления.

Исходный код, тесты, workflow и внутренние материалы проекта здесь не хранятся.

Автообновление приложения читает последний GitHub Release и его asset `latest.json`. В каждом опубликованном релизе должны быть только release-файлы:

- `STO_CRM.exe`
- `STO_CRM.exe.sha256`
- `latest.json`
- при необходимости краткие release notes

Формат `latest.json` внутри GitHub Release:

```json
{
  "version": "1.17.0",
  "tag": "v1.17.0",
  "name": "СТО CRM 1.17.0",
  "asset": {
    "name": "STO_CRM.exe",
    "size": 12345678,
    "sha256": "...",
    "download_url": "https://github.com/markbakaa88/sto-crm/releases/download/v1.17.0/STO_CRM.exe"
  }
}
```
