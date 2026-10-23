# Frank A股估值：GitHub OAuth 云端服务

**OAuth 服务 v0.3.2：修复免费实例重建后客户端注册丢失。授权状态先用 Render 原签名密钥派生的 Fernet 密钥加密，再通过专用 HTTPS 凭据写入已有 Gomami-Frank VPS 的 SQLite。41 项离线测试通过，涵盖注册、授权码、令牌和刷新在应用/存储重建后的恢复。桌面与网页版此前均由持有人确认可读。**

原有服务只接收固定 Bearer 密钥。此候选增加标准 OAuth 发现、PKCE、登录回调和授权码交换，通过 GitHub 确认身份；只允许 Snowflakeblues 的固定账号 ID `235202824` 读取。只请求 `read:user` 身份范围，不请求仓库权限。ChatGPT 使用服务签发的短期 OAuth 令牌，原资产接口密钥仅由服务器使用，两者分开。

## 你需要完成的一次性配置

1. 打开 [GitHub 新建 OAuth App](https://github.com/settings/applications/new)，使用 Snowflakeblues 登录。
2. 填写下面三项并注册应用。生成 Client Secret 的步骤由账号持有人本人完成。

| GitHub 字段 | 值 |
| --- | --- |
| Application name | `Frank A股估值` |
| Homepage URL | `https://frank-ashare-mcp.onrender.com` |
| Authorization callback URL | `https://frank-ashare-mcp.onrender.com/auth/callback` |

保留短期令牌的默认保护，不启用 Device Flow。创建后在应用详情中找到 Client ID，并生成 Client Secret。不要把 Client Secret 或资产 API Key 发到聊天里。

3. 在 [现有 Render 服务的 Environment 页面](https://dashboard.render.com/web/srv-dbcovivb9u1s73cdqe00/env) 配置：

| 环境变量 | 内容 |
| --- | --- |
| `GITHUB_OAUTH_CLIENT_ID` | GitHub 应用 Client ID |
| `GITHUB_OAUTH_CLIENT_SECRET` | GitHub 应用 Client Secret；也可保存在同名 Render Secret File |
| `ASHARE_ASSET_API_KEY` | 原资产估值接口的有效访问密钥；也可保存在同名 Render Secret File |
| `OAUTH_SIGNING_KEY` | 使用 Render Generate 生成的独立随机值，至少 32 字符 |
| `OAUTH_STATE_API_KEY` | 独立随机的状态存储凭据，至少 32 字符，与其他密钥分开 |
| `OAUTH_STATE_BACKEND` | `remote`；Render 上强制使用远端持久存储，禁止退回临时目录 |

这是 OAuth 方案的新配置要求。原资产密钥由 Render 的安全环境变量提供，不再依赖 ChatGPT 传入固定 API Key。

## 服务部署配置（由协作代理处理）

复用现有服务 ID、Git 仓库和 `deploy/frank-ashare-mcp` 分支，不修改 main。OAuth 源码可放在 `services/frank-ashare-mcp/oauth/`，服务切换到 Python，保留 Free、新加坡、自动部署 Off。

| 项目 | 值 |
| --- | --- |
| Runtime | Python |
| Build | `pip install -r services/frank-ashare-mcp/oauth/requirements.txt` |
| Start | `python services/frank-ashare-mcp/oauth/server_oauth.py` |
| Health check | `/health` |
| MCP | `https://frank-ashare-mcp.onrender.com/mcp` |

服务器缺少必需配置时拒绝启动。客户端注册、授权事务、授权码、上游令牌、JTI 与刷新记录全部使用同一远端加密存储。VPS 仅保存密文，不持有 Render 的加密/签名密钥；原估值接口和持仓数据不变。免费 Render 仍会休眠，但实例重建不再清空授权状态。此前已丢失的客户端必须在 ChatGPT 重新注册一次，不能凭来路不明的客户端 ID 自动恢复。

GitHub OAuth App 通常不提供刷新令牌。下游访问令牌有效期上限为 7 天，短于上游有效期时按上游收紧；每次使用仍通过原 GitHub 校验器核对有效凭据及持有人身份。上游撤销、会话到期、退出连接或密钥轮换仍可能要求重新登录。

VPS 运行 `frank-oauth-state.service`，专用无登录用户、仅监听 `127.0.0.1:9088`，内存上限 64 MiB；现有 HTTPS 站点单独反代 `/internal/oauth-state`。该接口仅接受专用 Bearer 凭据，不提供列举、任意文件读写或解密操作。SQLite 位于 `/var/lib/frank-oauth-state/state.sqlite3`；恢复配置位于 `/root/projects/frank-oauth-state-recovery`。一致性备份必须使用 SQLite backup API，Render 原 `OAUTH_SIGNING_KEY` 必须保持不变。

## 插件切换与验收

线上 OAuth 服务成功后，再将同一个私人插件的 `mcp.json` 认证改为 `{"type":"oauth"}` 并更新使用说明，保留身份与私人可见性。不要在 OAuth 服务上线之前发布该插件变更。

ChatGPT 端将通过“连接”发起登录，不再显示 API Key 表单。登录 Snowflakeblues，确认读取授权后返回 ChatGPT，再调用 `get_ashare_valuation`。若旧连接状态仍在，需从客户端支持的重新连接入口更新；不能靠修改插件简介证明连接已生效。

只有实际登录、从 ChatGPT 调用工具并返回有效源快照后，才能确认真实持仓已读通。报告还需核对估值日期、新鲜度、持仓确认状态与覆盖范围。

## 已完成的本地验证

`python -m unittest discover -p 'test*.py' -q`：41 项通过，使用虚构凭证和快照。覆盖账号 ID 限制、无凭证/伪造令牌拒绝、OAuth 发现、PKCE、网页和桌面回调、同意页面、授权码重放拒绝、模拟工具调用、秘密文件、加密存储鉴权及明文写入拒绝、命名空间、TTL、删除，以及应用/SQLite 重建后的授权码兑换、工具调用、刷新令牌轮换。

## 当前 Windows 桌面客户端

隔离测试使用已安装的 Codex 0.163.0-alpha.11：当前通用包没有加载出 MCP；使用旧版兼容清单且不带通用根清单的测试包能列出该服务。为让当前桌面版本可用，已用正式 `codex mcp add` 注册同一云端地址，名称为 `frank-ashare-cloud`，启动等待设为 90 秒以适应 Render 免费实例唤醒。

桌面登录使用 PKCE 和 `http://127.0.0.1:<临时端口>/callback`，仅允许此回环地址的 callback 路径。GitHub 应用的上游回调仍为 Render 上的 `/auth/callback`，无需改成 localhost。持有人固定 ID 限制和授权同意要求保持启用。

## 文档

- [OpenAI MCP 认证](https://developers.openai.com/plugins/build/auth)
- [FastMCP OAuth Proxy](https://gofastmcp.com/servers/auth/oauth-proxy)
- [GitHub 创建 OAuth App](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/creating-an-oauth-app)
