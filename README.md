# Photoprint backend

Backend MVP управленческой платформы «Фотопринт»: 12 KPI, заказы и CRM-воронка, производство, финансы и HR, цепочка Alert → решение → задача → проверка результата, прогноз на четыре недели, импорт пяти источников, качество данных и аудит. Все демосуммы синтетические, валюта BYN.

Python 3.13, FastAPI, PostgreSQL **15+**, SQLAlchemy async и Alembic. Версии и лицензии пакетов — в [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md). Frontend разрабатывается отдельно. Публичная схема доступна на `/openapi.json`, Swagger — `/docs`.

## Локальный запуск

Нужны `uv` и доступная PostgreSQL. Из корня проекта:

```sh
uv sync --frozen
cp -n .env.example .env
```

Заполните `.env`: `DATABASE_URL`, случайный `JWT_SECRET_KEY` длиной от 32 байт и пять разных `DEMO_*_PASSWORD` длиной 12–128 символов. Секрет можно получить командой:

```sh
uv run python -c 'import secrets; print(secrets.token_urlsafe(48))'
```

Не заменяйте существующий `.env` шаблоном. Обычный PostgreSQL URL и `postgresql+asyncpg://` поддерживаются; `sslmode=require` преобразуется для asyncpg. Для миграций укажите прямое или session-pool соединение в `MIGRATION_DATABASE_URL`, если основной URL использует transaction pooler. Пользователь миграций должен иметь права создания таблиц и представлений.

Следующие команды **меняют базу из `.env`**. Перед запуском проверьте её назначение:

```sh
uv run alembic upgrade head
uv run python scripts/seed.py
./start.sh --reload
```

Сервер: `http://localhost:8000`. `GET /health` и `/health/db` проверяют соединение с базой: 200 при успехе, 503 при недоступности. `start.sh` запускает сервер; миграции и seed автоматически не выполняет. `PORT` меняет порт.

Повторный seed добавляет отсутствующие записи, сохраняет пароли и изменения пользователей. Набор содержит 500 заказов, 200 клиентов, 300 обращений, сделки, производство, финансы, HR, дневные планы и сценарий с критическим отклонением и дефицитом мощности. `DEMO_REFERENCE_DATE=YYYY-MM-DD` фиксирует опорную дату при первоначальном заполнении; без него используется текущая дата Минска. Для новой демонстрационной даты создайте отдельную базу: обычный seed не переносит уже созданные факты.

| Логин | Пароль из окружения | Доступ |
| --- | --- | --- |
| `admin@fotoprint.demo` | `DEMO_ADMIN_PASSWORD` | Администрирование, импорт, все данные |
| `director@fotoprint.demo` | `DEMO_DIRECTOR_PASSWORD` | Все бизнес-данные и операции, чтение аудита |
| `manager@fotoprint.demo` | `DEMO_MANAGER_PASSWORD` | Свое подразделение, финансовые и HR-агрегаты |
| `analyst@fotoprint.demo` | `DEMO_ANALYST_PASSWORD` | Чтение бизнес-данных, проверки качества |
| `employee@fotoprint.demo` | `DEMO_EMPLOYEE_PASSWORD` | Свои задачи и прямо связанные заказы/решения |

Seed требует все пять паролей. Учётные данные в репозитории не хранятся. `POST /api/v1/demo/reset` доступен только admin при `DEMO_MODE=true` вне production и требует `{"confirm":"RESET_DEMO_DATA"}`. Он восстанавливает известные демозаписи, архивирует задачи и сохраняет историю/аудит/пароли. При обнаружении сторонних фактов возвращает 409. Для production маршрут не регистрируется.

## Shell-обёртки

В корневой папке `sh/` есть исполняемые обёртки для Python-скриптов из `scripts/`. Они сами переходят в корень проекта, передают аргументы и возвращают код завершения Python-процесса. Нужны `uv` и установленное окружение проекта (`uv sync --frozen`).

| Обёртка | Назначение и побочные действия |
| --- | --- |
| `./sh/seed.sh` | Загружает демоданные в БД из `.env`; требует миграции и пять DEMO-паролей. |
| `./sh/import_data.sh crm data/mock/crm.json` | Импортирует файл в БД; принимает те же аргументы, что Python CLI. Относительный путь считается от корня проекта. |
| `./sh/export_openapi.sh` | Перезаписывает корневой `openapi.json`; другой путь задаётся через `--output`. |
| `./sh/start_server.sh` | Запускает сервер через deployment entrypoint: по умолчанию сначала применяет миграции. Для запуска без миграций задайте `MIGRATE_ON_START=false`. |
| `./sh/test_postgres.sh -q` | Запускает полный набор тестов на отдельной временной PostgreSQL; удалённая БД не используется. |

`./start.sh --reload` остаётся обычным запуском для разработки без автоматических миграций. Проверяйте назначение `DATABASE_URL` перед seed, импортом и запуском с миграциями.

## Подключение Frontend

- Базовый URL: `/api/v1`. Объекты — `{data: ...}`, списки — `{items,total,page,page_size,pages}`. Ошибки — `{detail:{code,message,fields,request_id}}`.
- `POST /auth/login`: JSON `email`, `password`. Access JWT возвращается в `data.access_token`; передавайте `Authorization: Bearer ...`. Срок — 15 минут.
- Refresh хранится в HttpOnly Cookie на `/api/v1/auth`; `POST /auth/refresh` и `/auth/logout` отправляются с `credentials: "include"`. Срок refresh — 7 дней, ротация обязательна. Повторное использование старого refresh отзывает семейство.
- `FRONTEND_URL` — один точный origin, без пути. В локальной разработке `http://localhost:5173`, Cookie Secure=false/SameSite=lax. Для отдельных HTTPS-сайтов задайте `APP_ENV=production`, `COOKIE_SECURE=true`, `COOKIE_SAMESITE=none`, HTTPS `FRONTEND_URL`/`BACKEND_URL`. Cookie-операции проверяют Origin.
- Создание заказа, решения и задачи требует UUIDv4 в `Idempotency-Key`. Повтор с тем же телом возвращает исходные статус/ответ, другой запрос с тем же ключом — 409. Срок ключа 24 часа. PATCH требует актуальный `version`; конфликт — 409.
- Manager видит кампании, связанные с заказами/сделками своего подразделения, включая общие. `CampaignOut.budget` — `number|null`: для manager всегда `null`, для остальных разрешённых ролей — общий бюджет.
- UI может использовать `allowed_actions`; сервер независимо проверяет права. Чужое подразделение в фильтре manager даёт 403, недоступный объект по UUID — 404.
- Периоды `date_from`/`date_to` включительны, календарь `Europe/Minsk`, время хранится в UTC. Неизвестные query-параметры отклоняются; диапазон ограничен 366 днями.
- `null`/`no_data` означает отсутствие источника или неопределённую долю. Пустая загруженная сумма/счётчик — 0. HR и общие расходы не распределяются по продуктам; ответ содержит `ignored_filters`.

Группы API: `/users`, `/departments`, `/products`, `/customers`, `/campaigns`, `/orders`, `/sales/*`, `/production/*`, `/finance/*`, `/hr/summary`, `/support/interactions`, `/dashboard`, `/metrics`, `/alerts`, `/decisions`, `/tasks`, `/forecast`, `/integrations`, `/data-quality/*`, `/audit-logs`, `/analytics/metabase-embed`. Точные тела и ответы — в OpenAPI. Для передачи схему можно выгрузить без соединения с БД:

```sh
uv run python scripts/export_openapi.py
```

Пишется `openapi.json` в корне; production-схема по умолчанию исключает демонстрационный reset.

## Импорт источников

Admin отправляет `POST /api/v1/integrations/{source}/import`, где source: `crm`, `erp`, `finance`, `support`, `hr`. Максимум 1000 записей и 5 MiB. Сущности:

| Источник | entity_type |
| --- | --- |
| crm | customer, campaign, deal, deal_event |
| erp | department, product, order, order_event, production_record, capacity_plan |
| finance | finance_record |
| support | support_interaction |
| hr | hr_snapshot |

```json
{"records":[{"entity_type":"customer","external_id":"CRM-C-201","event_at":"2026-11-12T09:00:00Z","data":{"name":"Демо-клиент","customer_type":"b2b","segment":"corporate","acquisition_channel":"website"}}]}
```

Повторный `(source, entity_type, external_id)` обновляет запись, старое событие пропускается; ошибки возвращаются поштучно. Корректные записи сохраняются даже при частичном успехе и отдельной ошибке перерасчёта. Ссылки принимают платформенный UUID либо объект `{source,entity_type,external_id}` связанной сущности. Связанные [JSON/CSV-примеры](data/mock/README.md) поставляются для всех пяти источников. Рекомендуемый порядок: подразделения/продукты/клиенты → кампании/заказы/сделки → события/производство/финансы/поддержка/HR. Подробные ограничения проверяются перед сохранением.

CLI использует тот же обработчик и активного admin:

```sh
uv run python scripts/import_data.py crm /absolute/path/customers.json
uv run python scripts/import_data.py crm /absolute/path/customers.csv --actor-email admin@fotoprint.demo
```

CSV имеет четыре колонки: `entity_type,external_id,event_at,data`; `data` — JSON в корректно экранированной CSV-ячейке. Проверки качества запускают admin/analyst; история загрузок и результаты доступны через API.

## KPI и управленческий цикл

Расчёты выполняет Backend. Проценты агрегируются из числителей и знаменателей. Новые клиенты определяются по первой завершённой покупке за всю историю в выбранной области; брак — по единицам продукции; SLA — по закрытым обращениям с заданным сроком; HR — по последнему снимку каждого подразделения не позже конца периода.

Отклонение от плана до 5% включительно — normal, свыше 5% до 10% — warning, свыше 10% — critical; для брака хуже рост, для целевых KPI — снижение. Загрузка мощности: <70% warning, 70–100% normal, >100–110% warning, >110% critical. Это настройки демонстрационной модели.

`POST /metrics/recalculate` выполняет admin. Он сохраняет значения и создаёт критические Alert для месячных контекстов. GET Dashboard не создаёт Alert. Один KPI/месяц/подразделение/продукт имеет один Alert; resolved не переоткрывается автоматически. Задачи создаёт пользователь. Завершение задачи не завершает решение: нужны `actual_result`, статус needs_review, затем подтверждение с `verification_note`.

Прогноз сравнивает нормо-часы спроса и мощности. Используется средний спрос четырёх завершённых недель по созданным неотменённым заказам и планы следующих четырёх полных недель. Отсутствие истории или плана отражается как no_data. Дефицит и резерв возвращаются раздельно, без отрицательных величин.

## Metabase

Подписанный embed реализован с отдельным секретом, сроком пять минут и закреплённым подразделением manager. По умолчанию API возвращает **503 BI_UNAVAILABLE** до настройки и проверки dashboard. Общая публичная ссылка не используется.

Порядок настройки отдельного Metabase, SQL-шаблоны карточек и проверка изоляции — в [bi/README.md](bi/README.md). `METABASE_VERIFIED_DASHBOARDS` заполняется только после проверки каждой карточки. Наличие JWT само по себе не гарантирует фильтрацию SQL. Metabase должен читать исключительно восемь BI-представлений через отдельную роль, не таблицы приложения.

## Render и Docker

[render.yaml](render.yaml) описывает Backend с автоматическим деплоем из Git; секреты вводятся в Render, в YAML их нет. Metabase разворачивается отдельным сервисом с отдельной постоянной БД настроек. Настройки обоих сервисов — в [bi/README.md](bi/README.md).

GitHub CI запускает Ruff и тесты на PostgreSQL 17, проверяет актуальность OpenAPI, собирает Docker-образ и сканирует его. Сам workflow ещё не запускался на GitHub. Автодеплой Render пока настроен на каждый commit, независимо от результата CI; для обязательного ожидания проверок выберите соответствующий режим в Render.

Dockerfile запускает приложение непривилегированным пользователем. Команда контейнера `python scripts/start_server.py` сначала выполняет Alembic под PostgreSQL advisory lock, затем запускает Uvicorn. Ошибка миграции останавливает старт; seed при деплое не запускается. Для session advisory lock нужен прямой/session URL в `MIGRATION_DATABASE_URL`. На платном Render можно вынести `python -m alembic upgrade head` в Pre-Deploy Command и выставить `MIGRATE_ON_START=false`.

Для существующего Render Docker-сервиса достаточно подключить этот репозиторий, Dockerfile и `/health`. Обязательны `DATABASE_URL`, `JWT_SECRET_KEY`, HTTPS `FRONTEND_URL`/`BACKEND_URL`, production Cookie-параметры. Затем один раз примените seed через Shell/Job с пятью DEMO-паролями, если это выделенная демобаза. Render Secret Files/env используются вместо коммита `.env`.

```sh
docker build -t photoprint-backend .
docker run --rm --env-file .env -p 8000:8000 photoprint-backend
```

Внутри Docker `localhost` указывает на контейнер: строка БД должна вести к доступному хосту. Образ здесь не собирался: доступный Docker daemon отсутствовал. Деплой на Render и работа с удалённой PostgreSQL/Metabase требуют отдельной проверки в целевом окружении.

При неудачном релизе верните предыдущий успешный deploy в Render и проверьте `/health`, login и Dashboard. Миграции автоматически назад не откатываются. Перед миграциями сохраняйте резервную копию; downgrade удаляет данные и применяется только к заведомо одноразовой базе.

## Проверки

Быстрые проверки без БД:

```sh
uv run ruff check app scripts tests
uv run pytest -q tests/test_security.py tests/test_http_contract.py
```

Полный набор с собственной временной PostgreSQL, без Docker и удалённой БД:

```sh
uv run --python 3.12 --no-project --with pgserver python scripts/test_postgres.py -q
```

Python 3.12 нужен только оболочке `pgserver` с готовыми бинарниками. Она запускает тесты интерпретатором проекта Python 3.13, создаёт временный сервер и удаляет его после выполнения. Требуются доступ к пакетам при первом запуске и право запускать локальные процессы/сокеты.

Либо задайте `TEST_DATABASE_URL` на отдельную тестовую PostgreSQL 15+ и выполните `uv run pytest -q`. Тесты создают и удаляют случайные схемы. Не указывайте production: тестовая роль должна иметь права CREATE SCHEMA. Проверка BI-роли дополнительно требует CREATE ROLE и пропускается, если его нет. Без `TEST_DATABASE_URL` интеграционные проверки явно пропускаются.

Проверяются ротация refresh/reuse, роли и изоляция подразделений, полный жизненный цикл решений/задач, история, конкурентные PATCH и Idempotency-Key, KPI/пороговые значения, seed, частичный импорт, качество, прогноз, финансовая сверка, подписи BI и ограниченная роль PostgreSQL. Визуальный Frontend и живой Metabase этими тестами не проверяются.

## Структура

- `app/api/v1/` — маршруты и права на действия.
- `app/schemas/` — предметные пакеты `catalog/`, `workflow/`, `analytics/`, `reporting/`, `integrations/`, общие query/ссылки/история в `shared/`. Небольшие `domain.py` и `responses.py` сохраняют старые импорты; новый код импортирует конкретный модуль.
- `app/services/` — бизнес-правила, расчёты, импорт, аудит.
- `app/models/` — 29 таблиц PostgreSQL в пакетах `orders/`, `analytics/`, `reporting/`, `operations/`; `identity.py` и `workflow.py` объединяют небольшие связанные модели. `alembic/versions/` — фиксированные миграции и BI views.
- `app/seed/` — `service.py` координирует этапы из `stages/`: справочники, заказы, поддержка, планы, источники и демосценарий. `context.py` хранит состояние загрузки и стабильные идентификаторы; порядок этапов и транзакция сохраняются.
- `scripts/` — seed, импорт, экспорт OpenAPI, старт с миграциями, изолированные тесты.
- `sh/` — Bash-обёртки этих Python-скриптов; запускаются из любой директории.
- `tests/` — проверки API и PostgreSQL.

Локальные `agents.md` и `ASSUMPTIONS.local.md` намеренно исключены из Git и содержат координацию и допущения этой рабочей копии. Каталог `docs/` также исключён существующими пользовательскими правилами: для другого клона передайте согласованные ТЗ отдельно. Текущий исполняемый контракт экспортируется из кода.
