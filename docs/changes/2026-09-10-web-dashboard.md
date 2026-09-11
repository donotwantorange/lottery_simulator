# 交互式网页仪表盘

## 状态

设计已确认，待实施计划与实现。

## 目标

为现有模拟核心增加个人使用的 Streamlit 网页仪表盘，并支持通过公网域名安全部署到 Linux。

## 已确认内容

- Streamlit 单体应用，SQLite 保存历史；
- Trace 开启时保存逐抽记录，否则只保存参数和汇总；
- Trace 仅允许单轮模拟启用；
- 左侧参数、右侧指标与图表的明亮数据工具布局；
- 参数标签使用“假设主池已累计多少抽仍未出6星”；
- 历史使用双运行卡片对比；
- 后台工作进程提供进度和停止能力；
- 公网入口使用 Caddy HTTPS、Streamlit OIDC 和邮箱白名单；
- Docker Compose 部署并持久化数据库与证书。

## 设计文档

`docs/superpowers/specs/2026-09-10-web-dashboard-design.md`

## 验证结果

实现后补充。

## Git 提交

- `5ec945e docs: design secure interactive web dashboard`
- `f2d61e4 docs: clarify dashboard trace and auth boundaries`

## 任务 5：认证与 fail-closed 配置

- ✅ 新增 `dashboard/auth.py`：仅接受 development/production 与 disabled/oidc；生产环境禁止关闭认证，OIDC 必须配置邮箱白名单；邮箱 trim/lower 后精确匹配。
- ✅ `AuthConfig.from_env()` 使用 `APP_ENVIRONMENT`、`APP_AUTH_MODE`、`STREAMLIT_SERVER_ADDRESS`、`ALLOWED_EMAILS`，默认 production/oidc/127.0.0.1/空白名单，因此缺省配置拒绝启动；构造即验证且不可变，访问门禁再次验证传入配置。
- ✅ 开发免登录仅允许 loopback；门禁同时检查 Streamlit 的实际 `server.address`，拒绝 CLI 覆盖环境变量后绑定公网地址。开发启动必须显式绑定，例如 `--server.address=127.0.0.1`。
- ✅ 未登录显示一个登录按钮并停止；白名单外显示“无权访问此应用”、退出按钮并停止；允许的用户返回规范化邮箱。业务代码不读取或暴露 token。
- ✅ 新增 `.streamlit/config.toml`，明亮主题、`client.showErrorDetails="none"`，不固定服务器监听地址；示例 OIDC URL 使用 `.invalid` 绝对 HTTPS 地址，secret 为空且不暴露 token。
- ✅ `.gitignore` 新增 `.streamlit/secrets.toml`、`data/`、`backups/`、`.env`；未读取真实 secrets 文件。

### 验证

- ✅ RED：`.venv/bin/python -m unittest tests.test_auth -v`，预期并实际得到 `ModuleNotFoundError: No module named 'dashboard.auth'`，退出码 1。
- ✅ GREEN：同一 focused 命令，15 tests / OK；全量 `.venv/bin/python -m unittest discover -v`，93 tests / OK。
- ✅ 因果验证：用 apply_patch 临时移除实际监听地址检查，运行 `.venv/bin/python -m unittest tests.test_auth.AccessGateTests.test_disabled_gate_rejects_actual_public_bind -v`，0.0.0.0、::、None 三个子用例均报 `ValueError not raised`；恢复后 focused 15 tests / OK、全量 `.venv/bin/python -m unittest discover -q` 93 tests / OK。
- ✅ 用当前安装的 Streamlit 读取主题/错误展示配置、用 `tomllib` 解析两个示例配置、检查示例 URL 与空 secret；`git check-ignore` 确认四类私密/运行期路径均忽略；`git diff --check` 通过。
- ⚠️ 以上可验证本地配置拒绝规则和访问门禁行为，不能证明真实 OIDC 提供商、HTTPS 回调、反向代理和生产网络部署已联调。全量测试的 `--trace requires --trials 1` stderr 来自既有负例，测试最终通过。

### 任务提交

- 实现提交：待提交后记录 SHA（避免同一提交自引用）。
