# Функциональность ROS-пакетов и характеристики переноса

Исходная реализация: `iimt_manipulation/ros2_ws/src`, шесть активных пакетов:
`iimt_ros2_driver`, `iimt_ros2_description`, `iimt_ros2_moveit_config`,
`iimt_dual_control`, `iimt_dual_description`, `iimt_dual_moveit_config`.
Старые SystemInterface/controller_manager и topic-FIFO bridge не являются эталоном.

| Функция исходного стека | Характеристика | Native реализация / отличие |
|---|---|---|
| FollowJointTrajectory | принять/отменить/результат, одна цель | Execution + authenticated localhost IPC |
| SDK ServoJ | 6 q + a,v,t,lookahead,gain | та же SDK, отдельный send handle |
| Joint read | независимый bounded TCP reader | C++ Winsock/POSIX, короткий cache mutex |
| Опрос SDK read | возможен, но неinterruptible | новый runtime только bounded TCP; SDK read не выдаётся за bounded |
| Частоты | single profile30,dual125; 1…125 | независимые rate parameters, defaults125, best effort |
| Абсолютное расписание | time_from_start, no catch-up | steady epoch mapped from UTC; missed slot skipped |
| Упреждение | nominal отдельно от advanced send | per-arm advance_ms, default0 |
| Производные | linear/cubic/quintic | порт исходных полиномов; в CSV не создаются |
| Имена суставов | переупорядочение, ровно6 | Python reorder, native SDK-order 6/12 |
| Старт/лимиты/path/goal | finite, q/dq/ddq/step/fresh state | native guards, measured endpoint |
| Ошибки | причина+arm/joint/qdesired/qactual | сохранены, reference desired подписан |
| Stop/Clear | вызывались после отправок | Stop; Clear только явный opt-in и успешный Stop, см.README |
| Двурукая координация | shared epoch, sibling cancel | один controller process, две native reader/sender пары |
| Частичная цель | одна полная рука + hold второй | расширение по fresh measured state |
| Состояние двух рук | отдельные stamps, не синхронное измерение | per-arm records, без выдуманного общего acquisition time |
| Модели | CI05 DAE/STL, prefix, relative mounts | те же mesh bytes, ROS-free URDF generator + customURDF |
| OMPL RRTConnect | 6D/12D планирование | нативный OMPL, FCL full triangle meshes |
| Time parameterization | MoveIt time-optimal adapters | консервативные quintics, не TOTG; возможны остановки в вершинах |
| Self/inter-arm collisions | SRDF intra-arm exclusions | те же whitelist pairs, нет inter-arm исключений |
| Workspace | worldXY margins.5, no ceiling | infinite outside halfspaces; more exact than finite large boxes |
| Floor | plane at lowestbase | та же plane семантика, fixedbase contacts allowed |
| URDF/scene сервисы MoveIt | часть upstream MoveIt | Scene constructor/fixed objects in URDF; нет ROS scene services/hot scene mutation |
| IK | per-arm KDL у MoveIt | исключено пользователем: толькоjointgoals/CSV |
| RViz | отдельное ROS GUI | отдельный native GLFW/ImGui процесс, explicit controls |
| Внутренний mock | instant lastcommand inside driver | внешний SDK-compatible TCP server по требованию пользователя |
| CSV notebook | separateapproach/randomgoals/globaltime/errorplots | один configurable single/dual notebook, plots afterabort |
| Питание/тормоза/IO | legacy messages, не активный API | не добавлены; не выдаются за исходный рабочий функционал |
| Linux Docker | ROSHumble dependencies | нет ROS; wheels, native Windows release gate |

Ограничения: нет pause/resume, torque/current API, произвольных моделей оборудования,
Cartesian goal/IK или гарантии динамики. Поддерживаются fixed/revolute-compatible
CI05 модели, не произвольные URDF-сочленения. У стороннего GUI/MoveIt были другие
upstream-инструменты; новые методы не притворяются API-совместимыми с ROS.

Проверка collisions дискретная, планируется номинальная joint-space линия. При
различном упреждении двух рук фактически отправленные состояния могут лежать вне
этой общей линии; новая проверка **не доказывает безопасность асинхронно сдвинутого
движения**. Значения упреждения/прошивки должны быть калиброваны на реальном стенде.
