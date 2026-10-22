# Frank A�ɹ�ֵ��GitHub OAuth �޸���ѡ

**������ɣ�14 ��ز���ͨ������δ�л����Ϸ���򷢲��°�������ʵ GitHub ��¼����ʵ�ֲ��Դ����ա�**

ԭ�з���ֻ���չ̶� Bearer ��Կ���˺�ѡ���ӱ�׼ OAuth ���֡�PKCE����¼�ص�����Ȩ�뽻����ͨ�� GitHub ȷ�����ݣ�ֻ���� Snowflakeblues �Ĺ̶��˺� ID `235202824` ��ȡ��ֻ���� `read:user` ���ݷ�Χ��������ֿ�Ȩ�ޡ�ChatGPT ʹ�÷���ǩ���Ķ��� OAuth ���ƣ�ԭ�ʲ��ӿ���Կ���ɷ�����ʹ�ã����߷ֿ���

## ����Ҫ��ɵ�һ��������

1. �� [GitHub �½� OAuth App](https://github.com/settings/applications/new)��ʹ�� Snowflakeblues ��¼��
2. ��д�������ע��Ӧ�á����� Client Secret �Ĳ������˺ų����˱�����ɡ�

| GitHub �ֶ� | ֵ |
| --- | --- |
| Application name | `Frank A�ɹ�ֵ` |
| Homepage URL | `https://frank-ashare-mcp.onrender.com` |
| Authorization callback URL | `https://frank-ashare-mcp.onrender.com/auth/callback` |

�����������Ƶ�Ĭ�ϱ����������� Device Flow����������Ӧ���������ҵ� Client ID�������� Client Secret����Ҫ�� Client Secret ���ʲ� API Key ���������

3. �� [���� Render ����� Environment ҳ��](https://dashboard.render.com/web/srv-dbcovivb9u1s73cdqe00/env) ���ã�

| �������� | ���� |
| --- | --- |
| `GITHUB_OAUTH_CLIENT_ID` | GitHub Ӧ�� Client ID |
| `GITHUB_OAUTH_CLIENT_SECRET` | GitHub Ӧ�� Client Secret��Ҳ�ɱ�����ͬ�� Render Secret File |
| `ASHARE_ASSET_API_KEY` | ԭ�ʲ���ֵ�ӿڵ���Ч������Կ��Ҳ�ɱ�����ͬ�� Render Secret File |
| `OAUTH_SIGNING_KEY` | ʹ�� Render Generate ���ɵĶ������ֵ������ 32 �ַ� |
| `OAUTH_STATE_DIR` | `/tmp/frank-ashare-oauth` |

���� OAuth ������������Ҫ��ԭ�ʲ���Կ�� Render �İ�ȫ���������ṩ���������� ChatGPT ����̶� API Key��

## ���������ã���Э������������

�������з��� ID��Git �ֿ�� `deploy/frank-ashare-mcp` ��֧�����޸� main��OAuth Դ��ɷ��� `services/frank-ashare-mcp/oauth/`�������л��� Python������ Free���¼��¡��Զ����� Off��

| ��Ŀ | ֵ |
| --- | --- |
| Runtime | Python |
| Build | `pip install -r services/frank-ashare-mcp/oauth/requirements.txt` |
| Start | `python services/frank-ashare-mcp/oauth/server_oauth.py` |
| Health check | `/health` |
| MCP | `https://frank-ashare-mcp.onrender.com/mcp` |

������ȱ�ٱ�������ʱ�ܾ�������OAuth ״̬�ɿ���ܱ��棻���ʵ��ʹ����ʱ���̣����²����ʵ��״̬��ʧ�������Ҫ�������ӣ������Ӹ��ѳ־ô洢��

## ����л�������

���� OAuth ����ɹ����ٽ�ͬһ��˽�˲���� `mcp.json` ��֤��Ϊ `{"type":"oauth"}` ������ʹ��˵��������������˽�˿ɼ��ԡ���Ҫ�� OAuth ��������֮ǰ�����ò�������

ChatGPT �˽�ͨ�������ӡ������¼��������ʾ API Key ��������¼ Snowflakeblues��ȷ�϶�ȡ��Ȩ�󷵻� ChatGPT���ٵ��� `get_ashare_valuation`����������״̬���ڣ���ӿͻ���֧�ֵ�����������ڸ��£����ܿ��޸Ĳ�����֤����������Ч��

ֻ��ʵ�ʵ�¼���� ChatGPT ���ù��߲�������ЧԴ���պ󣬲���ȷ����ʵ�ֲ��Ѷ�ͨ�����滹��˶Թ�ֵ���ڡ����ʶȡ��ֲ�ȷ��״̬�븲�Ƿ�Χ��

## ����ɵı�����֤

`python -m unittest -v test_oauth`��14 ��ͨ����ʹ���鹹ƾ֤�Ϳ��ա������˺� ID ���ơ���ƾ֤/α�����ƾܾ���OAuth ���֡�PKCE���ص���ͬ��ҳ�桢��Ȩ���طžܾ���ģ�⹤�ߵ��á�Render Secret File ��ȡ�뻷���������ȣ��Լ�ԭʼС���ַ����� stale ״̬������

## �ĵ�

- [OpenAI MCP ��֤](https://developers.openai.com/plugins/build/auth)
- [FastMCP OAuth Proxy](https://gofastmcp.com/servers/auth/oauth-proxy)
- [GitHub ���� OAuth App](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/creating-an-oauth-app)
