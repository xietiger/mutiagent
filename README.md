# 本地多 Agent 控制台

在本机 `127.0.0.1` 上把同一个任务并行发给 Codex、Claude Code、Grok Build、CodeBuddy 和 Kimi Code。控制台保存原始输出和归一化结果，并排对照评审发现。它不会自动应用补丁，也不会把多个 Agent 指向同一个可写目录。

已采用的默认选择：

- 只读评审和按 Agent 隔离的 Git worktree 都已实现。直接修改当前工作区的模式会拒绝。

## 运行

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m app
```

在「应用程序」里打开 Relay，会在本机打开独立窗口。也可以继续用浏览器打开 `http://127.0.0.1:8765`。监听地址固定为 `127.0.0.1`。

```bash
.venv/bin/pytest
```

## Agent 路径

控制台只执行登记时确认过的绝对路径，运行时不再按 `PATH` 查找命令名。Kimi Code 从 `~/.kimi-code/config.toml` 读取 API Provider 配置。

## 执行方式

- 只读评审：复制一份任务快照，所有 Agent 读取同一份快照。Codex 使用 `read-only` sandbox，Claude 使用 `--restricted` 和 `Read,Glob,Grep`。
- Grok Build 使用只读 sandbox 和只读工具白名单；CodeBuddy 使用只读工具白名单。两者都通过 JSON Schema 输出结构化结果。
- Kimi Code 使用自身配置的 API Provider；只读模式额外通过 macOS 文件写保护运行，worktree 模式才会开启自动编辑权限。
- 独立 worktree：每个 Agent 从同一个基线提交创建自己的 worktree。完成后只收集 patch，不合并、不应用、不提交。
- 状态由退出码、超时、取消和结构化结果是否合法决定。Agent 自己写出的成功字样不能覆盖失败、超时或取消。
- 停止顺序是 `SIGINT`，等待宽限期，然后 `SIGTERM`，最后 `SIGKILL` 整个进程组。
- 服务重启后不会把正在运行的任务一律改回排队。能对上的 runner 会继续观察；已经有退出记录的不会重跑；没有结果的标记为失败。

环境变量只继承 `HOME`、`PATH`、语言、时区和代理等白名单，以及对应 CLI 的配置目录。不会默认继承 API key、token 或 `.env`。
