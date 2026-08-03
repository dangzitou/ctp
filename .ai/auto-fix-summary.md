修复 dashboard 应用端口不匹配问题：将 dashboard 服务端口从硬编码的 5000 改为通过环境变量 PORT 配置，并设置默认值 8080 以匹配 docker-compose.ha.yml 中 dashboard-lb 的预期

修改文件:
- runtime/dashboard/app.py
