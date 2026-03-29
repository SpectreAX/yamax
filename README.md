# YAMAX
**YAML Adaptive Management Agent for proXy** — Gemini 版本

## 快速启动

### 1. 获取 Gemini API Key

前往 https://aistudio.google.com/app/apikey 免费获取

### 2. 准备配置文件

```bash
mkdir config
cp /你的/config.yaml config/config.yaml
```

### 3. 配置 API Key

```bash
cp .env.example .env
# 编辑 .env，填入你的 GEMINI_API_KEY
```

### 4. 启动

```bash
docker compose up --build
```

服务启动后访问 http://localhost:8000/docs 查看接口文档

### 5. 发送指令

```bash
# 添加路由规则
curl -X POST http://localhost:8000/apply \
  -H "Content-Type: application/json" \
  -d '{"instruction": "Google 走台湾节点，Netflix 走新加坡节点"}'

# 查看当前配置
curl http://localhost:8000/config

# 健康检查（含模型信息）
curl http://localhost:8000/health
```

## 接口文档

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/apply` | 发送自然语言指令 |
| GET | `/config` | 查看当前配置内容 |
| GET | `/health` | 服务状态 + 模型信息 |
| GET | `/docs` | FastAPI 自动生成的交互式文档 |

## 切换模型

在 `main.py` 顶部修改 `MODEL` 变量：

```python
MODEL = "gemini-2.0-flash"        # 默认，速度快，免费额度充足
MODEL = "gemini-2.5-pro-preview"  # 推理更强，适合复杂配置修改
```
