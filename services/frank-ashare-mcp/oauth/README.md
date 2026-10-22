# Frank A股估值：GitHub OAuth 修复候选

**代码完成，11 项本地测试通过；尚未切换线上服务或发布新版插件。真实 GitHub 登录与真实持仓仍待验收。**

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
| `GITHUB_OAUTH_CLIENT_SECRET` | GitHub 应用 Client Secret |
| `ASHARE_ASSET_API_KEY` | 原资产估值接口的有效访问密钥 |
| `OAUTH_SIGNING_KEY` | 使用 Render Generate 生成的独立随机值，至少 32 字符 |
| `OAUTH_STATE_DIR` | `/tmp/frank-ashare-oauth` |

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

服务器缺少必需配置时拒绝启动。OAuth 状态由库加密保存；免费实例使用临时磁盘，重新部署或实例状态丢失后可能需要重新连接，不增加付费持久存储。

## 插件切换与验收

线上 OAuth 服务成功后，再将同一个私人插件的 `mcp.json` 认证改为 `{"type":"oauth"}` 并更新使用说明，保留身份与私人可见性。不要在 OAuth 服务上线之前发布该插件变更。

ChatGPT 端将通过“连接”发起登录，不再显示 API Key 表单。登录 Snowflakeblues，确认读取授权后返回 ChatGPT，再调用 `get_ashare_valuation`。若旧连接状态仍在，需从客户端支持的重新连接入口更新；不能靠修改插件简介证明连接已生效。

只有实际登录、从 ChatGPT 调用工具并返回有效源快照后，才能确认真实持仓已读通。报告还需核对估值日期、新鲜度、持仓确认状态与覆盖范围。

## 已完成的本地验证

`python -m unittest -v test_oauth`：11 项通过，使用虚构凭证和快照。覆盖账号 ID 限制、无凭证/伪造令牌拒绝、OAuth 发现、PKCE、回调、同意页面、授权码重放拒绝、模拟工具调用，以及原始小数字符串和 stale 状态保留。

## 文档

- [OpenAI MCP 认证](https://developers.openai.com/plugins/build/auth)
- [FastMCP OAuth Proxy](https://gofastmcp.com/servers/auth/oauth-proxy)
- [GitHub 创建 OAuth App](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/creating-an-oauth-app)
