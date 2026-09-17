# 本机备份与恢复

设置页的 JSON 导出仅覆盖账本，不是完整应用备份。

本轮提供 `scripts/integration/backup.py`，用于离线私有恢复包。包包含客户数据，必须保存在本机受控目录，不加入 Git 或上传公开位置。工具不会停止服务；创建前必须确认原服务与其他写入进程均已停止，`--writers-stopped` 是操作者确认，不是自动检测结果。

```bash
.venv/bin/python scripts/integration/backup.py create --database <数据库路径> --data-root <data目录> --destination <不存在的备份目录> --writers-stopped
.venv/bin/python scripts/integration/backup.py verify <备份目录>
.venv/bin/python scripts/integration/backup.py restore <备份目录> --destination <不存在的离线恢复目录>
```

恢复目标包含 `database.sqlite3`、`assets/` 与清单，不会自动成为运行中的应用。先核对文件与业务关系，再决定是否切换；真实替换必须有单独批准和回退方案。恢复过程中不会启动监听器或模型。

不包含 `.env`、环境密钥、日志与缓存。恢复后不能假定外部授权、持续分析订阅或加密下载任务仍可直接启用，应先审查授权和密钥。校验和用于发现内容变化，不是可信第三方签名。

本轮仅用合成数据库和文件完成备份、校验、恢复及篡改拒绝测试，没有复制真实客户数据。
