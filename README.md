
# k8s‑platform — декларативный оркестратор компонентов Kubernetes‑платформы

**Версия:** `1.2.0`

Ansible‑фреймворк для установки/удаления набора платформенных компонентов (metrics‑server, ingress, cert‑manager, …) в корректном порядке на основе графа зависимостей, с использованием сменных драйверов (Helm, raw‑манифесты и т.д.).

---

## Оглавление

- [Архитектура: 4 слоя ответственности](#архитектура-4-слоя-ответственности)
- [Execution Plan и явное подтверждение](#execution-plan-и-явное-подтверждение)
- [Запуск](#запуск)
- [Добавление нового компонента](#добавление-нового-компонента)
- [Почему localhost, а не `run_once`](#почему-localhost-а-не-run_once)
- [История версий](#история-версий)

---

## Архитектура: 4 слоя ответственности

Данные и логика разделены на четыре уровня, каждый из которых решает строго свою задачу.

| Уровень | Файл(ы) | Назначение |
|---------|---------|------------|
| **CATALOG** | `catalog.yml` | **ЧТО** должно быть установлено – перечень зависимостей, драйвер, репозиторий/чарт, проверки (checks), события (events), стратегия отката (rollback.strategy). |
| **COMPONENT** | `roles/platform/<name>/component.yml` | **КАК** компонент работает с движком (контракт) и **какие значения** использует по умолчанию. |
| **TASKS** | `roles/platform/<name>/tasks/*.yml` | **РЕАЛИЗАЦИЯ** бизнес‑логики – сценарии `install_pre.yml`, `install_post.yml`, `cleanup_pre.yml`, `cleanup_post.yml`. |
| **DRIVERS** | `roles/library/drivers/<name>/` | Полноценные Ansible‑роли, реализующие фазы `install`, `cleanup`, `rollback` через свои `tasks/`. |

### Детали слоёв

#### 1. CATALOG (`catalog.yml`)
Глобальный манифест, в котором перечислены все компоненты платформы. Для каждого указываются:
- зависимости (dependencies)
- драйвер (driver)
- репозиторий / чарт (repository / chart)
- проверки (checks)
- события (events)
- стратегия отката (rollback.strategy)

#### 2. COMPONENT.YML (`roles/platform/<name>/component.yml`)
Загружается **явно** через `ansible.builtin.include_vars` (в `roles/library/tasks/resolve_and_sort.yml`) – **никакого** `include_role`, `tasks/main.yml` или побочных эффектов от автозагрузки ролевых переменных. Это чистые данные: движок читает YAML и никогда не выполняет ни одного таска роли компонента на стадии построения графа.

Файл содержит две секции:

- **`contract`** – взаимодействие с движком:
  - `apiVersion`
  - `driver.enabled`
  - `phases.*.pre_driver` / `post_driver`
  - `events.*.pre` / `post`

- **`defaults`** – значения конфигурации по умолчанию:
  - `replicas`
  - `resources`
  - `args`
  - `helm values`

#### 3. TASKS (`roles/platform/<name>/tasks/*.yml`)
Реализуют конкретные шаги, которые должны быть выполнены **до** или **после** работы драйвера в каждой фазе (install / cleanup). Файлы создаются только для тех фаз, которые объявлены в контракте.

#### 4. Драйверы (`roles/library/drivers/<name>/`)
Это полноценные Ansible‑роли со стандартной структурой (`tasks/`, `defaults/`, `handlers/`, `meta/`). Какие фазы драйвер поддерживает – декларативно описано в `driver.yml` через ключ `driver_capabilities` (например, `{install: true, cleanup: true, rollback: true}`). Движок **не** проверяет наличие файлов через `stat()`, а полагается на этот манифест.

---

## Execution Plan и явное подтверждение

Каждый запуск сначала строит **план** – компоненты, разбитые на стадии по графу зависимостей (`Stage 1`, `Stage 2`, …), с возможностью параллельного выполнения внутри стадии. План печатается в консоль, **ничего не применяя**.

```bash
ansible-playbook site.yml -e platform_action=plan
```

Пример вывода:
```
===== EXECUTION PLAN (requested action: plan) =====

INSTALL (1 component(s) with desired_state=present):
  Stage 1: metrics_server

CLEANUP (0 component(s) with desired_state=absent):
  nothing to do
```

Чтобы **реально применить** план, необходимо указать не только `platform_action` (`install`/`cleanup`), но и дополнительный флаг `platform_confirm=true`:

```bash
ansible-playbook site.yml -e platform_action=install -e platform_confirm=true
```

Без `platform_confirm` движок покажет план и остановится с ошибкой.  
По умолчанию (`platform_action: plan`) даже простой вызов `ansible-playbook site.yml` без параметров **всегда безопасен** – он только отображает план.

**Важно:** план строится по **полному** графу зависимостей (без фильтрации по `desired_state` – см. `graph.py`). Фильтрация применяется только для вывода, чтобы не нарушить корректность топологической сортировки.  
Это **не** dry‑run в смысле сравнения с реальным состоянием кластера (не заменяет `helm diff`), а структурный план «что и в каком порядке».

---

## Запуск

Для работы доступны Make‑команды:

```bash
make install-deps      # ansible-galaxy collections + python deps
make validate           # проверка схем catalog.yml, контрактов и driver.yml
make plan               # ansible-playbook site.yml -e platform_action=plan
make install            # -e platform_action=install -e platform_confirm=true
make cleanup            # -e platform_action=cleanup -e platform_confirm=true
```

Плейбук `site.yml` выполняется на **`localhost`** (control node с доступом к kubeconfig/helm). Это не хак, а осознанное архитектурное решение – см. раздел [Почему localhost](#почему-localhost-а-не-run_once).

---

## Добавление нового компонента

Для быстрого создания заготовки используйте скрипт:

```bash
python3 scripts/generate_component.py my_component --driver helm \
    --install-post --cleanup-post
```

Скрипт создаёт:
- `roles/platform/my_component/component.yml` с контрактом и дефолтами;
- только те `tasks/*_pre.yml` / `*_post.yml`, для которых переданы соответствующие флаги (контракт и файлы генерируются синхронно).

После этого:
1. Добавьте запись о компоненте в `catalog.yml`.
2. Включите компонент в `inventory/production/group_vars/platform.yml` (укажите `desired_state: present`).

---

## Почему localhost, а не `run_once`

В ранних версиях граф зависимостей и порядок установки вычислялись один раз через `run_once: true` и сохранялись в `set_fact`. Это **не работает** на нескольких хостах – `run_once` выполняет таск только на одном хосте, но факт не транслируется на остальные хосты плейбука. В результате на всех хостах, кроме первого, факт остаётся неопределённым, и выполнение падает.

Поскольку весь движок взаимодействует с Kubernetes через Helm/kubectl с control‑ноды, а не выполняет действия на удалённых хостах, правильный паттерн – **единый хост**:

```yaml
hosts: localhost
connection: local
gather_facts: false
```

Тогда факт вычисляется и используется на одном и том же хосте, проблема репликации фактов просто отсутствует.

---

## История версий

### v1.0 – исправление критического черновика

- **Критический баг вызова драйвера** – драйверы были плоскими файлами (`drivers/helm/install.yml`), а `include_role`+`tasks_from` искал их в `drivers/helm/tasks/`. Временно исправлено через `include_tasks` с явным путём; в v1.2 драйверы стали полноценными ролями.
- **`run_once` не расшаривает факты** – весь оркестрирующий плей переведён на `hosts: localhost`.
- **Опциональные `*_pre`/`*_post` таски компонента не проверялись на существование файла** – добавлена симметричная проверка + `assert` в `validate_contract.yml`.
- **Хрупкое соглашение об именах `vars['<name>_defaults']`** – заменено на явную загрузку `component.yml` (v1.2).
- Дописаны недостающие файлы: `execute_lifecycle.yml`, `run_component.yml`, `run_events.yml`, `run_checks.yml`, `wait_rollout.yml`, `wait_object.yml`, `filter_plugins/graph.py` (топологическая сортировка с обнаружением циклов).
- Реализован драйвер `helm` через `kubernetes.core.helm`.
- Добавлен `requirements.yml` для `kubernetes.core`.

### v1.1 – по итогам ревью альтернативной «golden master» версии

Сторонняя версия заявляла 10/10, но на деле:
- регрессировала баг вызова драйвера;
- не содержала `tasks/main.yml` для `metrics_server` (первый прогон падал);
- содержала несовместимые по типу `events` (catalog объявлял boolean, движок ожидал список);
- ссылалась на неопределённые `platform.kubeconfig` / `delegate_host`;
- строила граф на отфильтрованном по `desired_state` подмножестве (ложные «Missing dependency»);
- валидировала только `catalog.yml` через jsonschema.

Ни одна из этих проблем не попала в данный проект. Заимствована только идея реестра `check_handlers` – но с явным `assert` на неизвестный тип проверки (вместо тихого пропуска).

### v1.2 – по итогам второго ревью

- **`include_role` как способ загрузки метаданных заменён на явный `component.yml` + `include_vars`.**  
  `defaults/main.yml` и `vars/main.yml` объединены в один файл с ключами `defaults:` / `contract:`. Заглушка `tasks/main.yml` больше не нужна – удалена.
- **Драйверы стали полноценными Ansible‑ролями** – `tasks/install.yml` и т.д. вместо плоских файлов; `include_role`+`tasks_from` теперь используется по прямому назначению.
- **Контракт возможностей драйвера вместо `stat()`.**  
  В `driver.yml` добавлен ключ `driver_capabilities: {install, cleanup, rollback}`, и `run_phase.yml` больше не проверяет файловую систему.
- **Внедрена стадия Execution Plan + gate подтверждения** (см. соответствующий раздел).  
  `platform_action` по умолчанию – `plan`, применение требует отдельного `platform_confirm=true`.

---

## Связь трёх ключевых слоёв (наглядная схема)

```
CATALOG (catalog.yml)
   │
   ├── зависимости
   ├── драйвер
   ├── репозиторий/чарт
   ├── checks
   ├── events
   └── rollback.strategy
        │
        ▼
COMPONENT.YML (roles/platform/<name>/component.yml)
   ├── contract:
   │    ├── apiVersion
   │    ├── driver.enabled
   │    ├── phases.*.pre_driver / post_driver
   │    └── events.*.pre / post
   └── defaults:
        ├── replicas
        ├── resources
        ├── args
        └── helm values
        │
        ▼
TASKS (roles/platform/<name>/tasks/*.yml)
   ├── install_pre.yml
   ├── install_post.yml
   ├── cleanup_pre.yml
   └── cleanup_post.yml
```

---

*Документ актуален для версии 1.2.0 и поддерживается в репозитории проекта.*
