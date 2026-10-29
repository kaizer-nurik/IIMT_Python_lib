# Wheels CPython 3.10–3.15 — 2026-10-29

Собраны и проверены **12 wheels `iimt-native==0.1.0`**: шесть для Linux x86-64
и шесть для Windows x64. Файлы находятся в [`wheelhouse/`](../wheelhouse/).
Каждый wheel скомпилирован для своей версии ABI, а не переименован из другой.

## Фактическая матрица проверок

| ABI | Python на Linux | Python на Windows | Pytest Linux / Windows | Ноутбуки single + dual |
|---|---|---|---|---|
| `cp310` | 3.10.22 | 3.10.11 | 70 / 70 | Пройдены на обеих ОС |
| `cp311` | 3.11.17 | 3.11.9 | 70 / 70 | Пройдены на обеих ОС |
| `cp312` | 3.12.15 | 3.12.10 | 70 / 70 | Пройдены на обеих ОС |
| `cp313` | 3.13.16 | 3.13.17 | 70 / 70 | Пройдены на обеих ОС |
| `cp314` | 3.14.8 | 3.14.10 | 70 / 70 | Пройдены на обеих ОС |
| `cp315` | 3.15.0 | 3.15.2 | 70 / 70 | Пройдены на обеих ОС |

Итого **840 пройденных тестов, без ошибок и пропусков**, и 24 успешных выполнения
ноутбука. Patch-версии в таблице фиксируют среду проверки, а не требуют закреплять
устаревший интерпретатор: wheel выбирается по minor-версии Python и платформе.

Для каждого wheel проверены:

- установка в отдельное окружение соответствующего CPython;
- импорт установленных C++-модулей `_control`, `_model`, `_viewer`;
- настоящий SDK производителя с внешним TCP mock на localhost;
- полный pytest, включая контроллер и планирование;
- native GUI с геометрией одной и двух рук;
- CSV-ноутбук: RRTConnect-подход, выполнение CSV, графики задания/состояния/ошибок
  (2 PNG для одной руки, 4 для двух), с проверкой интерпретатора ядра;
- SHA256, все записи `RECORD`, ABI-теги, ELF64/AMD64 на Linux и PE64/AMD64 на Windows;
  Windows-модули импортируют соответствующую `python3XX.dll`.

Linux: Ubuntu 24.04, изолированные uv-окружения, GUI через Xvfb.
Windows: **настоящая Windows Server 2022, build 20348**, локальная KVM VM, не Wine.
В Windows VM GUI использовал тестовый Mesa llvmpipe: он не включён в wheel и
не устанавливался в System32. Это не проверка производительности физического GPU.

## Установка

Имена файлов:

```text
iimt_native-0.1.0-cp3XX-cp3XX-manylinux_2_39_x86_64.whl
iimt_native-0.1.0-cp3XX-cp3XX-win_amd64.whl
```

Замените оба `cp3XX` на `cp310`, `cp311`, …, `cp315`. Например, для Python 3.12:

```bash
# Linux; из корня iimt_native, в нужном Python-окружении:
python -m pip install "./wheelhouse/iimt_native-0.1.0-cp312-cp312-manylinux_2_39_x86_64.whl[notebook]"
```

```powershell
# Windows:
python -m pip install ".\wheelhouse\iimt_native-0.1.0-cp312-cp312-win_amd64.whl[notebook]"
```

Без Jupyter уберите `[notebook]`. Не устанавливайте `wheelhouse/*.whl` целиком:
большинство файлов намеренно несовместимы с выбранным Python/ОС.

**Особенность Windows + Python 3.15 + `[notebook]`:** при этой проверке PyYAML
6.0.3 не имел подходящего Windows wheel; автоматическая сборка его необязательного
C-ускорителя требовала MSVC. Перед установкой notebook-extra установите штатный
pure-Python вариант PyYAML (команда из PowerShell, переменная действует только
в дочернем `cmd`):

```powershell
cmd /C "set PYYAML_FORCE_LIBYAML=0&& python -m pip install PyYAML==6.0.3"
python -m pip install ".\wheelhouse\iimt_native-0.1.0-cp315-cp315-win_amd64.whl[notebook]"
```

Этот путь прошёл установку, `pip check` и оба ноутбука без C++-компилятора в VM.
Сам wheel `iimt-native` и его C++-модули не требуют этого обхода; он относится
только к транзитивной зависимости Jupyter.
Поведение `PYYAML_FORCE_LIBYAML=0` подтверждено
[исходным кодом PyYAML 6.0.3](https://github.com/yaml/pyyaml/blob/6.0.3/setup.py#L141-L152):
он отключает необязательное расширение LibYAML, оставляя Python-реализацию.

## Контрольные суммы и воспроизведение

- [`wheelhouse/SHA256SUMS`](../wheelhouse/SHA256SUMS) — SHA256 всех 12 файлов.
- [`wheelhouse/manifest.json`](../wheelhouse/manifest.json) — размеры, версии Python
  и результаты проверки, привязанные к конкретным хешам.
- `results/python-matrix/linux/` и `results/python-matrix/windows/` — локальные
  журналы, JUnit, выполненные ноутбуки и GUI-свидетельства; `results/` исключён из Git.
- `scripts/linux_matrix/run.py`, `scripts/linux_matrix/run_notebooks.py` — Linux.
- `scripts/windows_cross/build_matrix.sh`, `scripts/windows_vm/python_matrix.ps1`
  — сборка PE и проверки внутри Windows. Подробнее: [DISTRIBUTION.md](DISTRIBUTION.md).

```bash
cd wheelhouse
sha256sum --check SHA256SUMS
```

Неудачные первые попытки сохранены, а не выданы за успех:
Linux 3.10 сначала не имел matplotlib в тестовом окружении;
Windows 3.10 CSV остановился по защитному лимиту шага при задержке планировщика;
Windows 3.15 сначала не установил PyYAML. После исправления тестовых зависимостей
и повторного запуска Windows 3.10 без сборочной нагрузки все проверки выше прошли.
CSV, ограничения безопасности и код контроллера при этом не менялись.
Первый Windows 3.11 notebook дополнительно перепроверен с контролем идентичности ядра.

## Границы результата

- Только **x86-64, стандартный CPython с GIL**. Не ARM64, PyPy, macOS или `cp3XXt`.
- Linux wheels требуют **glibc >= 2.39** (например, Ubuntu 24.04), не Alpine/musl.
- Windows API требует Windows 10 1803+; фактически проверена Server 2022,
  не все версии Windows. Для GUI нужен рабочий OpenGL 2.1+ и графическая сессия.
- Эти проверки используют mock, не физические манипуляторы. Они не доказывают
  hard realtime или гарантированные 125 Гц под любой нагрузкой.
- CI-матрица обновлена до 3.10–3.15, но GitHub Actions здесь не запускался.
  Результаты выше получены локально, включая настоящую Windows VM.
- Старые хеши и отдельные измерения CPython 3.12 в
  [VERIFICATION.md](VERIFICATION.md) относятся к предыдущим бинарным файлам.
- Права на публичное распространение SDK отдельно не установлены:
  [PROVENANCE.md](../vendor/PROVENANCE.md). Публикация wheels не выполнялась.
