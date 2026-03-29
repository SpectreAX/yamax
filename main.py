import os
import json
import yaml
from google import genai
from google.genai import types
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="YAMAX", description="YAML Adaptive Management Agent for proXy")

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
MODEL = "gemini-3-flash-preview"
CONFIG_PATH = os.environ.get("CONFIG_PATH", "/config/config.yaml")

# ── 工具定义（Gemini 格式）────────────────────────────────
read_config_func = types.FunctionDeclaration(
    name="read_config",
    description="读取当前代理配置文件的完整内容",
    parameters=types.Schema(type=types.Type.OBJECT, properties={})
)

list_proxy_groups_func = types.FunctionDeclaration(
    name="list_proxy_groups",
    description="列出所有 proxy-group 的名称和可用节点，用于确认节点组名称",
    parameters=types.Schema(type=types.Type.OBJECT, properties={})
)

update_rule_func = types.FunctionDeclaration(
    name="update_rule",
    description="为指定域名添加路由规则，指向某个 proxy-group。用于简单的单条规则添加。",
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "domain": types.Schema(
                type=types.Type.STRING,
                description="域名，如 google.com"
            ),
            "proxy_group": types.Schema(
                type=types.Type.STRING,
                description="proxy-group 名称，必须和配置文件中完全一致"
            )
        },
        required=["domain", "proxy_group"]
    )
)

write_config_func = types.FunctionDeclaration(
    name="write_config",
    description="将修改后的完整 YAML 写回配置文件。用于复杂修改（如改 DNS、修改 proxy-group 等）。",
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "yaml_content": types.Schema(
                type=types.Type.STRING,
                description="完整的 YAML 配置内容"
            )
        },
        required=["yaml_content"]
    )
)

TOOLS = types.Tool(function_declarations=[
    read_config_func,
    list_proxy_groups_func,
    update_rule_func,
    write_config_func,
])

SYSTEM_PROMPT = """你是 YAMAX，一个代理配置管理 Agent。用户用自然语言描述需求，你来修改 YAML 配置文件。

工作流程：
1. 先用 list_proxy_groups 确认可用的节点组名称（避免写错名字）
2. 简单规则用 update_rule；复杂修改（DNS、整体结构）用 read_config 再 write_config
3. 完成后简洁地告知用户做了什么改动

注意：proxy_group 参数必须和配置文件中的名称完全一致，大小写敏感。"""

# ── 工具执行函数 ──────────────────────────────────────────
def execute_tool(name: str, inputs: dict) -> str:
    if name == "read_config":
        if not os.path.exists(CONFIG_PATH):
            return f"错误：配置文件不存在：{CONFIG_PATH}"
        with open(CONFIG_PATH) as f:
            return f.read()

    elif name == "list_proxy_groups":
        if not os.path.exists(CONFIG_PATH):
            return "错误：配置文件不存在"
        with open(CONFIG_PATH) as f:
            config = yaml.safe_load(f)
        groups = config.get("proxy-groups", [])
        result = {g["name"]: g.get("proxies", [])[:8] for g in groups}
        return json.dumps(result, ensure_ascii=False, indent=2)

    elif name == "update_rule":
        domain = inputs["domain"]
        proxy_group = inputs["proxy_group"]
        if not os.path.exists(CONFIG_PATH):
            return "错误：配置文件不存在"
        with open(CONFIG_PATH) as f:
            config = yaml.safe_load(f)
        rules: list = config.get("rules", [])
        new_rule = f"DOMAIN-SUFFIX,{domain},{proxy_group}"
        if new_rule in rules:
            return f"规则已存在，无需添加：{new_rule}"
        for i, rule in enumerate(rules):
            if rule.startswith("MATCH"):
                rules.insert(i, new_rule)
                break
        else:
            rules.append(new_rule)
        config["rules"] = rules
        with open(CONFIG_PATH, "w") as f:
            yaml.dump(config, f, allow_unicode=True, default_flow_style=False)
        return f"已添加规则：{new_rule}"

    elif name == "write_config":
        yaml_content = inputs["yaml_content"]
        try:
            yaml.safe_load(yaml_content)
        except yaml.YAMLError as e:
            return f"YAML 语法错误，未写入：{e}"
        with open(CONFIG_PATH, "w") as f:
            f.write(yaml_content)
        return "配置已成功写入"

    return f"未知工具：{name}"

# ── Agent 主循环 ──────────────────────────────────────────
def run_agent(instruction: str) -> dict:
    steps = []

    # Gemini 用 contents 列表维护对话历史
    contents = [types.Content(
        role="user",
        parts=[types.Part(text=instruction)]
    )]

    while True:
        response = client.models.generate_content(
            model=MODEL,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                tools=[TOOLS],
                temperature=0,
            )
        )

        candidate = response.candidates[0]
        contents.append(candidate.content)  # 把模型回复加入历史

        # 检查是否有 function call
        function_calls = [
            part for part in candidate.content.parts
            if part.function_call is not None
        ]

        if not function_calls:
            # 没有 function call，取文字回答，结束循环
            final_text = next(
                (part.text for part in candidate.content.parts if part.text),
                ""
            )
            return {"result": final_text, "steps": steps}

        # 执行所有工具调用，收集结果
        tool_response_parts = []
        for part in function_calls:
            fc = part.function_call
            inputs = dict(fc.args) if fc.args else {}
            output = execute_tool(fc.name, inputs)
            steps.append({"tool": fc.name, "input": inputs, "output": output})
            tool_response_parts.append(types.Part(
                function_response=types.FunctionResponse(
                    name=fc.name,
                    response={"result": output}
                )
            ))

        # 把工具结果加入历史，继续下一轮
        contents.append(types.Content(
            role="user",
            parts=tool_response_parts
        ))

# ── HTTP 接口 ─────────────────────────────────────────────
class InstructionRequest(BaseModel):
    instruction: str

@app.post("/apply")
def apply_instruction(req: InstructionRequest):
    """接收自然语言指令，修改代理配置"""
    if not req.instruction.strip():
        raise HTTPException(status_code=400, detail="instruction 不能为空")
    try:
        return run_agent(req.instruction)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
def health():
    """健康检查"""
    return {
        "status": "ok",
        "model": MODEL,
        "config_path": CONFIG_PATH,
        "config_exists": os.path.exists(CONFIG_PATH)
    }

@app.get("/config")
def get_config():
    """读取当前配置文件内容"""
    if not os.path.exists(CONFIG_PATH):
        raise HTTPException(status_code=404, detail="配置文件不存在")
    with open(CONFIG_PATH) as f:
        return {"content": f.read()}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", 8000)),
        reload=True
    )
