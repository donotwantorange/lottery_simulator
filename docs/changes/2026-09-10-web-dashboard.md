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
