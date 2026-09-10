# 抽奖模拟器交互式网页仪表盘设计

## 目标

在不复制或改写抽奖规则的前提下，为现有 Python 抽奖模拟核心增加一个个人使用的 Streamlit 网页仪表盘。网页既可在本机运行，也可通过 Docker 部署到带公网域名的 Linux 服务器。

首版支持实时修改参数、执行和中止模拟、查看图表、保存历史、对比两次历史运行、按需保存 Trace，以及通过 OIDC 和邮箱白名单限制公网访问。

## 已确认产品边界

- 主要供单个用户使用，不建设多租户系统。
- 使用 Streamlit 单体应用，不增加独立 FastAPI、Vue 或 React 服务。
- 页面直接调用现有 `analysis.py`、`engine.py` 和规则模块。
- 历史使用 SQLite 保存。
- 启用 Trace 时保存逐抽详情；未启用时只保存参数和汇总。
- 默认采用明亮、高信息密度的桌面数据工具风格。
- 历史对比采用两次运行并排卡片布局。
- 公网部署必须使用 HTTPS、OIDC 登录和允许邮箱白名单。
- 所有规则及行为修改继续记录在 `docs/changes/`。

## 技术选择

- Python 3.11+
- Streamlit，安装认证扩展 `streamlit[auth]`
- Python 标准库 `sqlite3`
- Streamlit 原生图表、表格和下载组件
- Caddy 作为 HTTPS 终止和反向代理
- Docker Compose 管理 Streamlit 与 Caddy

不增加通用 ORM、外部数据库、JavaScript 前端框架或分布式任务队列。

## 架构

```text
浏览器
  ↓ HTTPS + OIDC
Caddy
  ↓ Docker 内部网络
Streamlit 应用
  ├── 页面与会话状态
  ├── 后台模拟任务管理
  ├── 现有 lottery_simulator 核心
  └── SQLite 历史仓库
          ↓
     data/lottery.sqlite3
```

网页层负责参数校验、任务控制、格式化和展示。模拟引擎仍是规则执行的唯一入口；历史仓库只接收结构化结果，不参与概率计算。

## 页面设计

### 总体布局

采用已确认的单页桌面布局：左侧固定参数，右侧依次显示指标、图表和详情。窄屏时左侧参数区堆叠到结果上方。

左侧参数：

- 规则选择；
- 主池抽数；
- 实验轮数；
- `假设主池已累计多少抽仍未出6星`；
- 可选随机种子；
- Trace 开关；
- 开始模拟、停止模拟按钮。

参数标签对应现有 `initial_pity`。它同时初始化保底进度和主池累计抽数，这一双重语义必须通过帮助文字明确展示。

### 结果区

顶部指标卡显示：

- 主池、赠送和总抽数；
- 主池、赠送和总六星模拟均值；
- 主池、赠送和总理论期望；
- 模拟与理论的绝对误差、相对误差；
- 初始和结束主池累计抽数；
- 实际随机种子和运行耗时。

图表固定为：

1. 主池每抽六星条件概率与首次六星累计概率曲线；
2. 六星数量分布柱状图；
3. 主池、赠送和总模拟值与理论期望对比图。

详情标签页：

- 汇总；
- 主池与赠送拆分；
- Trace 逐抽记录；
- 历史对比。

Trace 未启用时不查询或渲染逐抽明细，并明确显示“本次运行未保存逐抽记录”。当前结果支持下载为 JSON。

### 历史记录

历史默认按创建时间倒序，支持按规则、日期范围和是否含 Trace 筛选。列表显示时间、规则、种子、主池抽数、实验轮数、总六星均值和误差。

用户最多选择两次运行进入并排卡片对比。每张卡片展示参数、指标和六星数量分布；只有两次运行使用相同规则和兼容统计口径时才叠加比较曲线，否则分别显示并提示口径不同。

历史操作包括：

- 查看详情；
- 将历史参数填回参数区，但不自动开始模拟；
- 下载历史 JSON；
- 删除历史。删除前必须二次确认。

## 模拟任务与进度

单用户并不意味着所有模拟都能阻塞页面。网页通过一个后台工作进程运行模拟：

1. 页面创建唯一任务 ID 和可序列化参数快照；
2. 子进程执行模拟，周期性写入完成轮数、总轮数、耗时和状态；
3. Streamlit 使用定时 fragment 轮询任务状态并刷新进度区；
4. 用户点击停止时终止该工作进程，将任务标记为已取消；
5. 只有成功完成的任务才保存历史。

同一实例最多运行一个模拟任务。任务运行时禁用再次启动。页面刷新或 WebSocket 会话丢失后，通过任务 ID 和服务端任务状态恢复显示；不得仅依赖浏览器 Session State 保存任务真相。

后台任务状态包括 `queued`、`running`、`completed`、`cancelled` 和 `failed`。失败状态保存简短、安全的错误摘要，不把服务器堆栈或密钥显示给浏览器。

现有模拟引擎增加可选进度回调和取消检查接口，默认值保持现有 CLI 与 Python API 行为。回调不得改变随机数调用顺序，因此相同参数和种子在 CLI 与网页中仍产生相同结果。

## SQLite 数据设计

数据库位置为 `data/lottery.sqlite3`，采用外键约束和事务。

### `simulation_runs`

- `id`：文本 UUID，主键；
- `created_at`：UTC ISO 8601 时间；
- `rule_name`、`rule_version`；
- `main_draws`、`trials`、`initial_pity`；
- `seed`；
- `trace_enabled`；
- `bonus_draws`、`total_draws`；
- `initial_main_draws`、`final_main_draws`；
- `mean_main_six_stars`、`mean_bonus_six_stars`、`mean_six_stars`；
- `theoretical_expected_main_count`、`theoretical_expected_bonus_count`、`theoretical_expected_count`；
- `mean_count_error`、`mean_count_relative_error`；
- `at_least_one_rate`、`observed_mean_interval`、`theoretical_mean_interval`；
- `count_distribution_json`；
- `duration_seconds`；
- `result_json`：完整结构化汇总快照；
- `schema_version`。

### `draw_records`

- `run_id`：外键，运行删除时级联删除；
- `draw_index`；
- `source`、`source_index`、`bonus_event`；
- `main_draws_completed`；
- `pity_position`、`probability`、`is_six_star`；
- `misses_after_draw`；
- `(run_id, draw_index)` 联合主键。

只有 `trace_enabled=true` 时写入 `draw_records`。一次成功运行的汇总与所有 Trace 行必须在同一事务提交；任一写入失败则全部回滚。

数据库初始化和升级通过 `PRAGMA user_version` 管理，迁移必须是幂等或在事务中原子完成。每次连接启用外键；单实例写入，查询使用明确排序和分页。

## 规则版本

每个可选规则公开稳定的 `name` 和 `version`。历史记录同时保存两者，防止规则修改后把旧结果误认为由当前规则产生。现有 Rule1 首次加入版本字段时定为 `1.1`，代表已包含首次 30 抽赠送子规则。

历史结果始终使用保存时的结果快照展示。只有在用户主动选择“重新运行”时才使用当前代码中的规则版本，并在版本不同处显示提示。

## 认证与公网安全

- Streamlit 使用 OIDC 登录，首版配置一个身份提供商。
- 登录后检查 `st.user.email` 是否在 `ALLOWED_EMAILS` 白名单；不匹配时拒绝访问业务页面。
- OIDC 客户端密钥、Cookie 密钥和邮箱白名单不写入 Git，由部署环境注入。
- Cookie 密钥必须使用高熵随机值。
- 默认不向前端暴露 OIDC access token。
- Streamlit 仅监听 Docker 内部网络，不向宿主机直接发布 8501。
- Caddy 是唯一公网入口，负责 HTTPS 和 HTTP 到 HTTPS 跳转。
- DNS 指向服务器，公网只开放 80 和 443。
- 页面不显示未处理异常、文件系统路径、数据库 SQL 或密钥。

## Docker 与 Linux 部署

`docker-compose.yml` 包含：

- `app`：运行 Streamlit，挂载只读认证配置和可写 `data` 卷；
- `caddy`：发布 80/443，反向代理到 `app:8501`，持久化证书数据。

应用镜像基于官方 Python slim 镜像构建，依赖版本锁定。容器使用非 root 用户运行，`data` 目录单独授权。健康检查覆盖 Streamlit 健康端点；两个服务设置自动重启策略。

部署文档必须包含：DNS、开放端口、OIDC 回调地址、密钥生成、首次启动、升级、数据库备份与恢复、查看日志和回滚步骤。

SQLite 至少每日复制备份到独立目录；备份前使用 SQLite 在线备份 API或在应用停止后复制，不能在未知写入状态下直接复制数据库文件。

## 错误处理

- 参数在任务启动前校验，错误保留当前输入。
- 主池抽数和实验轮数设置可配置上限，并在预计工作量较大时显示警告。
- 任务失败不写 `simulation_runs`。
- 任务取消不保存部分统计。
- 历史保存失败时仍显示已完成模拟结果，并明确提示结果未持久化、提供即时 JSON 下载。
- 数据库迁移失败时应用进入只读错误页，不继续写入。
- 历史记录不存在或 Trace 未保存时使用清晰空状态。
- 删除使用显式确认，成功后才从页面移除记录。

## 可访问性与视觉规范

- 明亮主题，系统字体，正文不小于 16px；
- 状态不只依赖颜色，配合文字或图标；
- 所有控件支持键盘操作并保留清晰焦点；
- 图表同时提供数值表格或可下载数据；
- 长任务显示进度、完成轮数和耗时；
- 响应式窄屏布局不隐藏关键指标；
- 非必要动画遵循 `prefers-reduced-motion`。

## 文件边界

预计新增或修改：

- `dashboard/app.py`：页面入口、认证门禁和导航；
- `dashboard/views/simulation.py`：参数、运行和当前结果；
- `dashboard/views/history.py`：历史列表、详情和双运行对比；
- `dashboard/charts.py`：将结构化结果转为图表数据；
- `dashboard/jobs.py`：后台工作进程、进度、取消和状态恢复；
- `dashboard/repository.py`：SQLite 初始化、迁移、事务和查询；
- `dashboard/models.py`：网页与持久化数据类型；
- `lottery_simulator/engine.py`：可选进度与取消钩子；
- `lottery_simulator/rules/rule_1.py`：规则版本；
- `.streamlit/config.toml` 与 secrets 示例；
- `Dockerfile`、`docker-compose.yml`、`Caddyfile`；
- `requirements.txt`；
- `tests/` 下对应单元、数据库、任务和 Streamlit AppTest；
- `README.md`、部署文档和 `docs/changes/`。

## 测试与验证

### 核心回归

- 现有 41 项测试继续通过；
- 同参数和种子通过 CLI、直接 Python 调用和网页任务产生相同结构化结果；
- 进度回调开关不改变随机结果；
- 取消任务不返回伪完整结果、不写历史。

### 数据库

- 首次初始化与重复初始化；
- 汇总保存、读取、筛选、分页和删除；
- Trace 开启时事务保存所有逐抽行；
- Trace 关闭时 `draw_records` 为零；
- 写入中途失败整体回滚；
- 删除运行级联删除 Trace；
- 旧 schema 迁移测试。

### 页面

- 未登录用户只看到登录入口；
- 非白名单邮箱不能进入业务页；
- 参数标签精确为“假设主池已累计多少抽仍未出6星”；
- 参数错误、任务进行中、完成、取消、失败和保存失败状态；
- 当前结果指标、三类图表、JSON 下载；
- 历史双卡对比与口径不一致提示；
- 删除二次确认；
- 键盘焦点顺序和窄屏关键内容检查。

### 部署

- Docker 镜像构建成功；
- Compose 健康检查通过；
- 应用容器没有公网端口映射；
- Caddy 反向代理和 WebSocket 正常；
- 公网域名强制 HTTPS；
- OIDC 回调、登录、白名单拒绝和登出均验证；
- 重建容器后 SQLite 历史仍存在；
- 备份文件可恢复到临时数据库并查询。

## 验收标准

1. 用户可在网页修改参数、启动或停止模拟，并看到进度。
2. 结果数值与现有核心一致，网页没有重复概率实现。
3. 页面使用确认的明亮单页布局和双运行历史对比。
4. 指定参数标签按确认文案显示。
5. 成功运行自动保存；只有 Trace 运行保存逐抽行。
6. 历史可查看、双运行对比、复用参数、下载和确认删除。
7. 公网只能通过 HTTPS 和白名单 OIDC 账号访问。
8. Docker 重建不丢历史，备份可恢复。
9. 所有新增测试及现有回归测试通过。

## 暂不包含

- 多用户数据隔离与角色权限；
- 多个并发模拟任务；
- PostgreSQL、Redis 或外部任务队列；
- 任意规则的网页编辑器；
- 邮件通知、定时模拟和共享链接；
- 移动端专用交互。
