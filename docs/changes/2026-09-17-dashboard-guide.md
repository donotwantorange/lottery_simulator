# 网页页面详细说明

## 状态与目标

已完成。根据用户要求，将对话中的详细页面讲解整理为独立使用说明，并在现有使用入口加入链接。

## 确认内容与作用边界

覆盖侧栏参数及配置、数据来源、六个结果标签页、历史管理、统计口径和推荐操作顺序。仅修改文档，不修改规则、界面、数据库、服务器或依赖；不进行在线提交。

## 涉及文件

- `docs/dashboard-guide.md`：新增详细页面说明。
- `README.md`、`docs/local-usage.md`：加入阅读入口。
- 本记录：保留修改计划及完成结果。

## 验证结果

✅ 文档口径已核对当前 `dashboard/app.py`、`dashboard/views/simulation.py`、`dashboard/views/configuration.py`、`dashboard/views/history.py` 和 `dashboard/charts.py`。新增相对链接目标均存在，十个章节及两处阅读入口已检查，`git diff --check` 通过。验证范围为文档与代码口径、链接和差异格式，不代表重新进行浏览器功能验收；文档修改不涉及代码，不重复运行全套功能测试。

## Git提交

本次仅修改本地文档，未创建提交或推送。
