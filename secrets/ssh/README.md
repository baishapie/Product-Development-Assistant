# SSH 密钥目录

用于存放连接数据库服务器（跳板机）的 **SSH 私钥** 与 `known_hosts`。
`secrets/` 已被 `.gitignore` 忽略，**禁止把私钥提交到仓库**。

## 约定
- 私钥文件：`id_ed25519`（推荐）或 `id_rsa`。
- 已知主机：`known_hosts`（可用 `ssh-keyscan -p <port> <host> > known_hosts` 生成）。
- 通过 `.env` 指定：`SSH_KEY_PATH`、`SSH_KNOWN_HOSTS`。

## 权限（重要）
Linux / macOS：
```bash
chmod 600 secrets/ssh/id_ed25519
chmod 700 secrets/ssh
```
Windows（PowerShell，去掉继承并只给当前用户读权限）：
```powershell
icacls secrets\ssh\id_ed25519 /inheritance:r /grant:r "$($env:USERNAME):(R)"
```

## 放置后
1. 在 `.env` 设置 `SSH_ENABLED=true` 及 `SSH_HOST/SSH_USER/SSH_KEY_PATH`。
2. 确认 `.env` 里 `PG_HOST/PG_PORT` 指向**目标数据库在内网的真实地址**（隧道会转发它）。
