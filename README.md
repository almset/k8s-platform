# k8s-platform — декларативный оркестратор компонентов Kubernetes-платформы

Версия: **1.2.0**

Ansible-фреймворк, который устанавливает/удаляет набор платформенных
компонентов (metrics-server, ingress, cert-manager, ...) в правильном
порядке, на основе графа зависимостей, через сменные драйверы
(Helm, raw-манифесты и т.д.).

## Архитектура: 4 слоя ответственности

```
CATALOG (catalog.yml)       — ЧТО должно быть установлено зависимости, драйвер, репозиторий/чарт, checks, events, rollback.strategy
        ↓
COMPONENT.YML (roles/platform/<name>/component.yml)
    contract: — КАК компонент работает с движком apiVersion, driver.enabled, phases.*.pre_driver/post_driver, events.*.pre/post
    defaults: — ЗНАЧЕНИЯ конфигурации replicas, resources, args, helm values
        ↓
TASKS (roles/platform/<name>/tasks/*.yml)   — РЕАЛИЗАЦИЯ бизнес-логики install_pre.yml / install_post.yml / cleanup_pre.yml / cleanup_post.yml
```

`component.yml` загружается **явно** через `ansible.builtin.include_vars`
(`roles/library/tasks/resolve_and_sort.yml`) — никакого `include_role`,
никакого `tasks/main.yml`, никаких побочных эффектов от автозагрузки
ролевых переменных. Это чистые данные: движок читает YAML и никогда не
выполняет ни одного таска роли компонента на стадии построения графа,
даже если однажды кто-то допишет реальную логику в `tasks/*.yml`.

Драйверы (`roles/library/drivers/<name>/`) — полноценные Ansible-роли
(`tasks/install.yml`, `tasks/cleanup.yml`, `tasks/rollback.yml`), а не
плоские файлы. Это даёт им доступ ко всем обычным механизмам роли
(`defaults`, `vars`, `handlers`, `meta`), если когда-нибудь понадобится.
Какие фазы драйвер реализует — описано декларативно в `driver.yml`
(`driver_capabilities: {install: true, cleanup: true, rollback: true}`),
а не выводится проверкой файла через `stat()`.

## Execution Plan и явное подтверждение

Каждый прогон сначала строит план — компоненты, разбитые на стадии по
графу зависимостей (`Stage 1 / Stage 2 / ...`, параллельно-безопасные
внутри стадии) — и печатает его, **не выполняя ничего**:

```bash
ansible-playbook site.yml -e platform_action=plan
```
```
===== EXECUTION PLAN (requested action: plan) =====

INSTALL (1 component(s) with desired_state=present):
  Stage 1: metrics_server

CLEANUP (0 component(s) with desired_state=absent):
  nothing to do
```

Чтобы реально применить план, `platform_action` (`install`/`cleanup`)
недостаточно — требуется отдельный явный флаг `platform_confirm=true`:

```bash
ansible-playbook site.yml -e platform_action=install -e platform_confirm=true
```

Без него движок покажет план и остановится с ошибкой — по умолчанию
(`platform_action: plan`) голый `ansible-playbook site.yml` без `-e`
всегда безопасен и ничего не применяет.

План строится по **полному** графу зависимостей (не отфильтрованному по
`desired_state` — см. `graph.py`, почему фильтрация до сортировки ломает
корректность), а фильтруется только для отображения. Это не dry-run в
смысле diff с реальным состоянием кластера (то есть не заменяет
`helm diff`) — это структурный план "что и в каком порядке", как первый
шаг к нему.

## Запуск

```bash
make install-deps      # ansible-galaxy collections + python deps
make validate           # схемы catalog.yml + все контракты + driver.yml
make plan                # ansible-playbook site.yml -e platform_action=plan
make install             # -e platform_action=install -e platform_confirm=true
make cleanup              # -e platform_action=cleanup -e platform_confirm=true
```

`site.yml` выполняется на `localhost` (control node с доступом к
kubeconfig/helm) — это **не хак**, а осознанное архитектурное решение,
см. раздел "Почему localhost" ниже.

## Добавление нового компонента

```bash
python3 scripts/generate_component.py my_component --driver helm \
    --install-post --cleanup-post
```

Скрипт создаёт `roles/platform/my_component/component.yml` +
только те `tasks/*_pre.yml`/`*_post.yml`, для которых вы передали флаг —
контракт физически не может объявить фазу без файла, так как оба
генерируются вместе. Затем добавьте запись в `catalog.yml` и включите
компонент в `inventory/production/group_vars/platform.yml`.

## Почему localhost, а не `run_once`

В версии, которую мы рефакторили, граф зависимостей и порядок
установки считались один раз через `run_once: true` и клались в
`set_fact`. Это **не переживает выполнение на нескольких хостах**:
`run_once` выполняет таск один раз, но не транслирует
`set_fact`/`register` на остальные хосты плея — на всех хостах,
кроме первого, факт остаётся undefined, и плей падает.

Так как весь этот движок ничего не делает "на хостах" — он говорит
Helm/kubectl обратиться к API Kubernetes с control-ноды — правильный
паттерн: `hosts: localhost, connection: local, gather_facts: false`.
Тогда факт вычисляется и используется на одном и том же (единственном)
хосте, и никакой проблемы репликации фактов не существует в принципе.

## История версий

### v1.0 — исправление критического черновика

1. **Критический баг вызова драйвера.** Драйверы были плоскими файлами
   (`drivers/helm/install.yml`), а `include_role`+`tasks_from` искал их
   в несуществующем `drivers/helm/tasks/`. Временно исправлено через
   `include_tasks` с явным путём; в v1.2 драйверы стали полноценными
   ролями, и `include_role` снова корректен по построению.
2. **`run_once` не расшаривает факты между хостами.** Весь оркестрирующий
   плей переведён на `hosts: localhost`.
3. **Опциональные `*_pre`/`*_post` таски компонента не проверялись на
   существование файла**, в отличие от драйвера. Добавлена симметричная
   проверка + assert в `validate_contract.yml`.
4. **Хрупкое соглашение об именах `vars['<name>_defaults']`.** Заменено
   в v1.2 на явную загрузку `component.yml` — проблема ушла вместе с
   механизмом, который её порождал.
5. Дописаны отсутствовавшие файлы: `execute_lifecycle.yml`,
   `run_component.yml`, `run_events.yml`, `run_checks.yml`,
   `wait_rollout.yml`, `wait_object.yml`, `filter_plugins/graph.py`
   (`topological_sort` с обнаружением циклов).
6. Реализован драйвер `helm` через `kubernetes.core.helm`.
7. `requirements.yml` для `kubernetes.core`.

### v1.1 — по итогам ревью альтернативной "golden master" версии

Сторонняя версия того же проекта заявляла 10/10, но на деле
регрессировала баг вызова драйвера, не содержала `tasks/main.yml` для
`metrics_server` (первый прогон падает), содержала несовместимые по
типу `events` (catalog объявляет boolean, движок ожидает список),
ссылалась на неопределённую `platform.kubeconfig`/`delegate_host`,
строила граф зависимостей на уже отфильтрованном по `desired_state`
подмножестве (ложные "Missing dependency"), и валидировала jsonschema'ой
только `catalog.yml`. Ни одна из них не попала в этот проект. Забрали
только идею реестра `check_handlers` — но с явным `assert` на
неизвестный тип проверки вместо тихого пропуска.

### v1.2 — по итогам второго ревью

1. **`include_role` как способ загрузки метаданных заменён на явный
   `component.yml` + `include_vars`.** `defaults/main.yml` и
   `vars/main.yml` объединены в один файл с ключами `defaults:`/
   `contract:`, `tasks/main.yml`-заглушка больше не нужна — удалена.
2. **Драйверы стали полноценными Ansible-ролями** (`tasks/install.yml`
   и т.д. вместо плоских файлов) — `include_role`+`tasks_from` теперь
   корректен не как обходной путь, а по прямому назначению механизма.
3. **Контракт возможностей драйвера вместо `stat()`.** `driver.yml`
   (`driver_capabilities: {install, cleanup, rollback}`) — decides
   явно, `run_phase.yml` больше не спрашивает файловую систему.
4. **Стадия Execution Plan + gate подтверждения** — см. раздел выше.
   `platform_action` по умолчанию — `plan`, применение требует
   отдельного `platform_confirm=true`.
