# IIMT Native — CI-05 без ROS

Python API, **C++-контроллер**, OMPL **RRTConnect**, FCL collision checking и отдельное
небольшое окно GLFW/OpenGL + Dear ImGui. Одна или две руки IIMT-CI-05; совместимый
пользовательский URDF; Linux x86-64 / Windows x64 — целевые платформы.

**12 готовых wheels для CPython 3.10–3.15:** файлы в `wheelhouse/`, точные версии,
SHA256 и результаты — в [WHEEL_MATRIX.md](docs/WHEEL_MATRIX.md). Пройдены 840 тестов
без пропусков и 24 запуска single/dual ноутбука. Windows проверена
на настоящей Windows Server 2022 в локальной KVM-машине, не в Wine; Linux — в
отдельных окружениях соответствующих интерпретаторов. SDK, внешний mock,
single/dual CSV, планирование и GUI проверяются отдельно. Исторические измерения
первой CPython 3.12 поставки: [VERIFICATION.md](docs/VERIFICATION.md).

## Что перенесено из ROS

Полная матрица: [FEATURES.md](docs/FEATURES.md). Основа — успешный прямой
`iimt_ros2_driver`, не старый `ros2_control`:

- ServoJ по одному набору шести углов, абсолютная временная шкала, независимое чтение;
- единый старт двух рук, индивидуальные частоты/упреждения, совместная отмена;
- позиции, опциональные скорости/ускорения для интерполяции, лимиты и tolerances;
- честные timestamps, старение состояния, timeout, диагностические счётчики;
- RRTConnect, self/inter-arm/world collisions, floor и настраиваемый XY workspace;
- CSV без дополнительных точек, отдельный подвод, графики UTC и ошибок после abort;
- внешний mock на обычном IP/порту — в контроллере нет `if mock`.

**Не обещаем hard realtime или 125 свежих измерений/с.** 125 Гц — настраиваемая
целевая частота отправки каждой руки. SDK/сеть/ОС могут опоздать; это warning и
счётчик, не повтор старых точек. Устаревшие данные/нарушение лимитов останавливают
выполнение. Mock не воспроизводит реальную сервосистему/гарантии безопасности.

## Установка без компилятора

Устанавливайте **проверенный wheel своей платформы и версии Python**. Пакет не
опубликован в PyPI; имя в примере ниже — локальный файл:

```bash
python -m venv .venv
# Linux: source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install "./wheelhouse/iimt_native-0.1.0-cp312-cp312-manylinux_2_39_x86_64.whl[notebook]"
# Windows, вместо предыдущей команды:
# python -m pip install "./wheelhouse/iimt_native-0.1.0-cp312-cp312-win_amd64.whl[notebook]"
```

Пример выше — для Python 3.12. Для другой версии выбирайте оба тега в имени:
`cp310` — 3.10, `cp311` — 3.11, …, `cp315` — 3.15; не переименовывайте файл.
Все эти сборки — **стандартный CPython с GIL, x86-64**, не PyPy, ARM64 и не
free-threaded Python (`cp313t` / `cp314t` / `cp315t`). Теги должны совпадать с Python,
из которого вызывается `python -m pip`.
Для Windows/Python 3.15 с `[notebook]` нужен описанный в
[инструкции установки](docs/WHEEL_MATRIX.md#установка) preinstall pure-Python PyYAML.

Локальные Linux wheels требуют **glibc >= 2.39** (например Ubuntu 24.04).
Не переименовывайте их в Windows/manylinux другого поколения. Windows wheel
содержит настоящие PE-модули и DLL-зависимости; требует Windows 10 1803+ / Server
2022 и соответствующий CPython x64. Фактически протестирована Server 2022, не все редакции
Windows. Компилятор конечному пользователю не нужен; для GUI нужны рабочий
OpenGL 2.1+ драйвер и графическая сессия. Headless работает с `viewer=False`.
CI-рецепт теперь охватывает 3.10–3.15; фактические локальные проверки отражены
отдельно в матрице, а не выдаются за запуск GitHub Actions.
Сборка, DLL/.so closure, версии, ограничения: [DISTRIBUTION.md](docs/DISTRIBUTION.md).

## Быстрый пример: внешняя имитация

Все примеры в `.py` под Windows запускайте под `if __name__ == "__main__":`.
Jupyter использует импортируемые функции пакета, а не локальные функции-мишени spawn.

```python
from iimt import Robot, Trajectory
from iimt.mock import MockRobot


def main():
    with MockRobot() as mock:  # отдельный TCP-сервер в отдельном процессе
        robot = Robot.single(mock.host, port=mock.port, enable_motion=True)
        try:
            robot.connect(viewer=True)  # контроллер + отдельное 3D окно
            state = robot.get_state()
            q = state["arms"][0]["positions"]
            target = q.copy()
            target[0] += 0.03
            plan = robot.plan(target, scale=0.2)  # RRTConnect + проверка столкновений
            motion = robot.execute_trajectory(plan, start_delay=3.0)
            print(motion.wait(timeout=30))
        finally:
            robot.close()


if __name__ == "__main__":
    main()
```

Mock отдельно, даже на другой машине:

```bash
python -m iimt.mock --host 127.0.0.1 --port 29999 --lag 0.0 --read-delay 0.0
```

В обычном `Arm` укажите этот IP/порт. Нет отдельного транспорта «для mock».
Имитатор принимает реальные команды поставляемого SDK, включая stop/programState;
сохраняет JSONL wire log и позволяет инъекции задержек/ошибок в тестах.

## Настоящий робот

```python
robot = Robot.single("192.168.50.95", enable_motion=False)
robot.connect(viewer=False)
print(robot.get_state())
robot.close()
```

`enable_motion=False` разрешает подключение/чтение, но запрещает выполнение.
После проверки стенда установите `enable_motion=True` **в конфигурации до connect**.
Автоматического включения питания/снятия тормозов нет. Только один управляющий
процесс должен обращаться к роботу: приложение **не может исключить сторонний SDK**.
Аварийный аппаратный останов обязателен; сетевой `cancel()` не заменяет его.

### Важное отличие Stop/Clear

На localhost установлено: `API_ClearUnfinishedTrajectory` в используемой Linux SDK
посылает **`unlock protective stop`**, а не очевидную команду очистки FIFO. Поэтому
новый контроллер **по умолчанию не вызывает её автоматически**. Параметр
`allow_protective_stop_release=False`. При явном opt-in Clear вызывается только после
успешного Stop. Это отклонение от старого ROS-драйвера в пользу запрета неявного
снятия protective stop. Без Clear очищенность очереди не подтверждается; проверить
семантику остановки/очереди на конкретной прошивке необходимо до допуска к железу.
SDK Stop подтверждает состояние протокола, не независимый аппаратный останов.

## Две руки и основания

```python
from iimt import Robot, ci05_scene

scene = ci05_scene(
    dual=True,
    left_base=(-0.0008297, -0.538, 0.0818739, 0, 0, -0.6981317008),
    right_relative=(-0.345440489323, 0.411679944176, -0.082, 0, 0, 0),
    margins=(0.5, 0.5, 0.5, 0.5),  # X−, X+, Y−, Y+ относительно world
)
robot = Robot.dual("192.168.50.95", "192.168.50.92", scene=scene,
                   command_rate=125, read_rate=125, enable_motion=False)
```

`right_relative` — **относительно левой базы**, не world. `xyz` в метрах, `rpy` в
радианах. Модель генерируется без xacro. Пол по умолчанию на высоте нижней базы;
`floor_z=` переопределяет. XY workspace включает обе базы и отступы; потолка нет.
Пол — бесконечная плоскость, не заполненное нижнее полупространство. Боковые стены
в новой реализации — внешние бесконечные halfspaces, а не конечные большие боксы.

Для индивидуальных параметров создайте `Robot([Arm(...), Arm(...)], scene=scene)`;
`joint_names` каждой руки должны содержать шесть имён **в порядке осей SDK**, все
имена уникальны. `Robot.dual()` автоматически использует `left_`/`right_`.

## Пользовательский URDF

```python
from iimt import Scene
scene = Scene(
    urdf="/absolute/path/robot.urdf",
    joint_names=[...],  # 6 или 12 управляемых суставов в порядке arms/SDK
    package_paths={"my_robot": "/absolute/path/my_robot"},
    disabled_collisions=[("base_link", "shoulder_link"), ("base_link", "__floor__")],
    workspace=[-0.5, 0.5, -0.6, 0.6], floor_z=0.0,
)
```

Поддерживаются fixed/revolute, URDF origin/axis, mesh/box/sphere/cylinder. Остальные
подвижные сочленения, mimic и неподдерживаемые конструкции отвергаются, не игнорируются.
DAE/STL загружаются через Assimp; FCL проверяет исходную triangle geometry, не заменяет
её convex hull. Фиксированные инструменты/объекты можно добавить в URDF. Список
исключений коллизий явный; межруковых исключений в штатной модели нет. Из проверок
пола можно исключать только неподвижные базовые links. Границы/скорости URDF
пересекаются с настройками контроллера. Изменение модели — закрытие и новый connect,
не небезопасная смена лимитов во время движения.

## API

| Метод | Результат / семантика |
|---|---|
| `connect(viewer=True)` | отдельный процесс, SDK connections, свежий initial state, GUI отдельно |
| `get_state()` | arms: positions/velocities, receipt UTC ns, monotonic ns, age, valid; desired отдельно |
| `plan(q, timeout=5, scale=.2)` | RRTConnect в 6/12D; отклонение невалидной цели/старта; `Trajectory` |
| `execute_trajectory(t, start_delay=3)` | collision preflight → timestamp сообщения → асинхронный `Execution` |
| `execute_trajectory(t, start_unix_ns=...)` | точный единый UTC epoch; слишком поздний/нехватка preroll — ошибка |
| `Execution.poll()/wait()/cancel()` | результат и накопление samples; ошибка не уничтожает частичные данные |
| `cancel()` | отмена pending preparation и активного исполнения обеих рук |
| `diagnostics()` | rates, duration, age, timeout/error/send/missed-slot counters, fault/clear status |
| `samples()` | забрать накопленные samples; не вызывайте параллельно с `Execution.poll()` |
| `close()` | отмена/остановка, результат cleanup, завершение процессов; warning при неподтверждённом stop |

`check_collision=False` — **явное отключение preflight**, не режим обычной эксплуатации.
Контроллерные guards остаются. Collision checking дискретное; не сертификат
непрерывной безопасности. Одна цель за раз, нет FIFO/скрытой очереди. Partial goal
разрешён только для одной полной руки: вторая удерживает свежую измеренную позу.

`Trajectory(times, positions, joint_names, velocities=None, accelerations=None)`:
positions-only — линейная; +velocity — кубическая; +acceleration — квинтическая
интерполяция. Производные не передаются в ServoJ по осям: робот получает q[6] и
скаляры a/v/t/lookahead/gain. `t=1/command_rate`. Если первая точка позже нуля,
добавляется measured start, как в ROS-драйвере; CSV с t=0 не дополняется. Конечная
явная скорость должна быть нулевой.

RRT-план получает консервативную квинтическую временную параметризацию с остановкой
в **геометрических** вершинах; это не MoveIt TOTG. Проверочные промежуточные точки
не превращаются в остановки. Planning timeout — бюджет алгоритма: отдельный
collision query и постпроверка могут завершиться позже, это не realtime deadline.

## GUI

Серый — измеренная поза, голубой — цель, жёлтый — номинальное задание, зелёный —
анимированный предпросмотр плана. Sliders меняют **только цель**. Plan не движет робот;
Execute запускает только актуальный план, Cancel отменяет. Старые результаты
планирования после изменения цели отбрасываются. Камера: drag/orbit, pan, scroll.
Закрытие окна **не останавливает** уже принятый ход; используйте Cancel/`robot.close()`.
GUI/планирование не исполняются в servo thread. Геометрия кешируется, кадр обновляет
только link transforms. Headless-контроллер не импортирует GUI.

## CSV и графики

[notebooks/csv_single_dual.ipynb](notebooks/csv_single_dual.ipynb): переключатель
`DUAL`, безопасный `USE_MOCK=True`, отдельные RUN_APPROACH/RUN_CSV, 3 секунды до
начала **после проверки**, отдельная случайная суставная цель. Исходные CSV-позиции
и времена сохраняются; dq/ddq из файла намеренно не используются.

Графики имеют глобальную UTC ось. Desired привязан к подтверждённому nominal start,
measured — к времени получения ответа; **никакого сдвига на подобранный лаг**.
Ошибка = actual−desired, вне интервала CSV — NaN, а не искусственный ноль. После
abort строятся частичные графики; metadata/CSV/PNG сохраняются в `results/`.
Калибруемый `advance_ms` сдвигает только отправку: 330 мс не считается универсальным
свойством SDK, значение по умолчанию 0.

## Параметры и устройство

[PARAMETERS.md](docs/PARAMETERS.md) — все настройки с единицами/ограничениями.
[FEATURES.md](docs/FEATURES.md) — матрица ROS → native и отличия.
[VERIFICATION.md](docs/VERIFICATION.md) — фактические проверки и незакрытые критерии.
[WHEEL_MATRIX.md](docs/WHEEL_MATRIX.md) — актуальная матрица Python 3.10–3.15 и wheels.
[vendor/PROVENANCE.md](vendor/PROVENANCE.md) — происхождение SDK и лицензирование.

```
src/iimt/       Python API, IPC, config, external mock, plots
cpp/control/    SDK loader, bounded TCP read, native goal/scheduler
cpp/model/      URDF/FK/Assimp/FCL/OMPL
cpp/viewer/     GLFW/OpenGL/ImGui native renderer
notebooks/      CSV single/dual notebook
data/           исходный CSV (121 точка, 4 секунды)
scripts/        wheel repair/installed-wheel smoke/benchmark
.github/        native Linux/Windows build-and-test jobs
```
