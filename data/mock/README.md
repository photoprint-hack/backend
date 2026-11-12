# Примеры импорта пяти источников

JSON и CSV содержат одинаковые вымышленные записи за 9–10 ноября 2026 года, суммы в BYN. Это небольшие связанные примеры для проверки интеграций; полный демонстрационный набор 500/200/300 создаёт `scripts/seed.py`.

После миграций и создания администратора импортируйте в отдельную демонстрационную базу в порядке:

```sh
uv run python scripts/import_data.py crm data/mock/crm.json
uv run python scripts/import_data.py erp data/mock/erp.json
uv run python scripts/import_data.py finance data/mock/finance.json
uv run python scripts/import_data.py support data/mock/support.json
uv run python scripts/import_data.py hr data/mock/hr.json
```

Для CSV замените расширение на `.csv`. Повторный импорт не создаёт дубликаты. Ссылки вида `{source,entity_type,external_id}` разрешаются в серверные UUID. Для другой даты измените даты событий и фактов согласованно. Планы KPI этим импортом не создаются: их задаёт seed, поэтому новые контексты без планов могут возвращать `TARGET_MISSING`.

Примеры создают дополнительные факты вне встроенных seed fixtures: после этого `/demo/reset` намеренно вернёт 409 вместо удаления неизвестного набора. Чтобы восстановить изолированный демосценарий, используйте отдельную одноразовую базу.
