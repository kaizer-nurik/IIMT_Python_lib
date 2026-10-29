# Параметры

Все Arm-параметры задаются до `connect()`, для каждой руки независимо. Ошибка
неизвестного параметра не игнорируется. SI: radians, seconds, metres; только
advance задаётся в milliseconds. Настройки не являются сертификатом безопасности.

| Arm | По умолчанию | Назначение |
|---|---|---|
| name / ip | обязательны | имя руки / IPv4, уникальные endpoints |
| port | 29999 | SDK и независимое TCP read соединение |
| joint_names | шесть CI05 имён | строго SDK axis1…6, глобально уникальны |
| sdk_library | packaged vendor | абсолютный путь к DLL/SO, не Python SDK |
| enable_motion | false | подключение/чтение возможны, ServoJ запрещён |
| command_rate / read_rate | 125 / 125 Hz | независимо, диапазон [0.01,125] |
| read_timeout | .1 s | whole TCP transaction, включая connect/greeting |
| state_timeout | .2 s | stale/слишком длительное измерение → abort |
| startup_timeout | 5 s | ожидание первого свежего state; не прерывает vendor Login |
| servo_a / servo_v | 5 / 3 | scalar ServoJ параметры, не массив dq/ddq |
| lookahead_time / gain | .012 s / 0 | как в текущем SDK; эффект требует калибровки |
| advance_ms | 0 ms | 0…1000, pre-roll команд до nominal epoch |
| start_tolerance | .02 rad | measured start vs q0 |
| path_tolerance | 3 rad | наследованный широкий предел, НЕ рекомендация безопасности |
| goal_tolerance | .003 rad | измеренная конечная ошибка |
| goal_time_tolerance | 2 s | ожидание measured endpoint после nominal duration |
| jitter_warning | .004 s | warning, counter, пропуск просроченного слота, не replay |
| clock_jump_tolerance | .1 s | wall/steady divergence → abort |
| windows_timer_resolution_ms | 1 ms | дополнительный Windows process timer request; 0 отключает только этот запрос; у двух рук берётся minimum nonzero; Linux игнорирует |
| allow_protective_stop_release | false | explicit opt-in API_Clear после успешного Stop |
| min_position / max_position | ниже | шесть углов, пересечение с URDF |
| max_velocity | [3.1415]×6 rad/s | пересечение с velocity URDF; для планов ещё max_step×rate |
| max_acceleration | [1.875,2.5,3.75,3.125,3.75,3.75] rad/s² | проверка интерполированного задания |
| max_step | [.02]×6 rad | максимальный скачок между фактически отправленными командами |

max_position = [6.2832, 2.6167, 2.8783, 3.0528, 3.0528, 6.2832];
min_position = -max_position. Положения/производные finite; времена строго возрастают.
Positions-only linear имеет нулевое сегментное ускорение, но углы скорости на
стыках: эта проверка **не гарантирует ограничение физического ускорения** у CSV.
Динамику сглаживания внутри робота задаёт прошивка/ServoJ, не Python-графики.

## Scene / model

- `urdf`: файл, fixed/revolute, ровно6/12 управляемых joints.
- `joint_names`: порядок всех arms/SDK.
- `package_paths`: явный package URI→directory, ROS environment не нужен.
- `disabled_collisions`: явные pairs; only fixed base/floor exemptions.
- `workspace`: `[xmin,xmax,ymin,ymax]` world metres или None (отключить стены).
- `floor_z`: world height или None (отключить пол).
- `collision_resolution=.02`: максимальный шаг дискретной проверки в joint space;
  планировщик принимает (0,.1]. Предпроверка траекторий также семплирует по времени.
- `ci05_scene(margins=(.5,.5,.5,.5))`: X−/X+/Y−/Y+ вокруг экстремумов баз.
- `ci05_scene(left_base=..., right_relative=...)`: xyz+rpy, правая относительно левой.

## Время выполнения

`start_delay=3` — **Python API/message field**, не скрытая настройка контроллера.
Preflight сначала заканчивается, потом клиент формирует `start_unix_ns`. Явный
`start_unix_ns` не переносится при долгой проверке; истёкшая цель отвергается.
Нужен достаточный pre-roll для максимального advance двух рук. Номинальная шкала
не сдвигается ни при advanced dispatch, ни при пропущенном такте.

На Windows timed waits используют interruptible high-resolution waitable timers
(Windows 10 1803+), не обычный `sleep` и не busy-spin. `timeBeginPeriod(1)` сам по
себе оказался недостаточен в проверенной VM. `windows_timer_resolution_ms=0` не
отключает high-resolution waitable timer. Ошибка создания/ожидания такого таймера
не скрывается переходом на низкую частоту. Это всё ещё best effort, не hard RT.

## Mock

`MockRobot(host='127.0.0.1',port=0,positions=...,lag=0,read_delay=0,log=...)` запускает
реальный TCP сервер. `port=0` выбирает свободный порт. `lag` — модель очереди команд,
не эмуляция внутреннего регулятора. `set_faults(timeout_every=N,timeout_delay=.3,
read_delay=...,fail_stop=True,fail_clear=True)` — тестовые fault injections. Не
экспортируйте mock/IPC в недоверенную сеть. `positions` — исходные измеренные углы;
нулевая CI05-поза может конфликтовать с полом/workspace, используйте начало CSV.

## Диагностика

Per arm: read_calls/read_timeouts/read_errors, sends/missed_slots/warnings,
last/max read/send duration, last/max send interval, max_lateness, first_send_stamp,
state_age_s, message, clear_status. Global: active,connected,fault,dropped_samples.
`timed_wait_backend` и `windows_timer_status` показывают механизм ожидания и
результат дополнительного запроса timer resolution.
Не путайте чистое время API_Servoj с задержкой механического следования.

Измерение: `stamp_unix_ns` = host receive completion, `received_monotonic_ns`, `age_s`,
read_duration_s; velocity = конечная разность успешных измерений. Timeout не меняет
positions/stamp. Desired имеет отдельные `desired_stamp_unix_ns`, `nominal_elapsed_s`,
`start_unix_ns`, `goal_id`; номинальная шкала, не преждевременная ServoJ цель.

В wire log mock поле `monotonic_ns` берётся из `time.perf_counter_ns()` (QPC на
Windows), а `unix_ns` — отдельная UTC-привязка. Интервалы benchmark считаются по
первому: `time.monotonic_ns()` в CPython 3.12 Windows оказался слишком грубым
для измерения jitter 8-миллисекундного цикла. Эти часы не следует вычитать из
native `received_monotonic_ns`: начала отсчёта разных API не обязаны совпадать.
