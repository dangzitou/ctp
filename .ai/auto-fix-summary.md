修复 dashboard 应用监听端口不匹配问题：app.py 硬编码监听 5000 端口，但 docker-compose 配置期望监听 8080 端口（HAProxy 负载均衡器转发目标）

修改文件:
- runtime/dashboard/app.py
