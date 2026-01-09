import os
import json
import asyncio
import re
import ast
import sys
import subprocess
import tempfile
import platform
from openai import AsyncOpenAI
from dotenv import load_dotenv

# 自动修正 Windows 系统代理
for key in ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"]:
    proxy = os.environ.get(key)
    if proxy and not proxy.startswith("http"):
        print(f"Fixing proxy format: {key}={proxy}")
        os.environ[key] = f"http://{proxy}"

load_dotenv()

client = AsyncOpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com",
    timeout=60.0,
    max_retries=2
)

# ==========================================
# 1. 核心 Prompts
# ==========================================

SYSTEM_CLASSIFIER = """你是一个意图识别专家。
任务：分析用户输入，分类为：
1. **task**: 描述性需求（如“写个游戏”、“开发网站”、“数据分析脚本”）。
2. **problem**: 算法题目（含IO格式、样例、时间限制）。
3. **code**: 用户提供了完整代码请求修复。

输出JSON: {"type": "task"|"problem"|"code", "language": "python"|"cpp", "has_code_snippet": bool}
"""


def get_explainer_prompt(category):
    latex_rule = "3. **公式格式强制**：行内公式必须用单美元符号包裹（如 $E=mc^2$），独立公式块用双美元符号（$$...$$）。严禁使用 \\( ... \\) 或直接使用小括号。"

    if category == "task":
        return f"""你是一个资深技术文档工程师。请生成一份 JSON 格式的工程架构文档。
输出JSON: {{"simple": "Markdown文本", "academic": "Markdown文本"}}
内容要求：
1. simple: 使用生动比喻解释程序运行流程（如“舞台”、“演员”）。
2. academic: 类似 README.md，包含技术栈、模块划分、关键类设计。
{latex_rule}
"""
    else:
        return f"""你是一个计算机科学金牌讲师。请生成一份 JSON 格式的算法解析报告。
输出JSON: {{"simple": "Markdown文本", "academic": "Markdown文本"}}
内容要求：
1. simple: 使用通俗比喻解释算法流程。
2. academic: 包含算法定义、状态转移、严谨的时空复杂度分析。
{latex_rule}
"""
def enforce_architecture_lock(original_code, new_code, design_blueprint):
    """
    真正的架构锁：基于AST检查核心函数名和类名是否被篡改。
    """
    try:
        tree_orig = ast.parse(original_code)
        tree_new = ast.parse(new_code)
        
        # 提取关键签名 (FunctionDef, ClassDef)
        def get_signatures(tree):
            return {node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
        
        orig_sigs = get_signatures(tree_orig)
        new_sigs = get_signatures(tree_new)
        
        # 1. 刚性约束：原有的核心接口必须存在
        missing = orig_sigs - new_sigs
        if missing:
            return False, f"架构锁违规：检测到核心接口丢失 {missing}，拒绝合入。"
            
        # 2. 蓝图约束：如果蓝图规定了算法类型（如必须用DP），这里可以做更深的检查
        # (简单实现可以是检查是否引入了非法库，或者递归深度等)
        
        return True, "架构一致"
    except Exception as e:
        return False, f"代码解析失败，视为违规: {e}"

# 在 Review 环节调用：
# is_valid, msg = enforce_architecture_lock(old_code, current_code, approved_design)
# if not is_valid:
#     score = 0  # 强制打分归零
#     critique = f"**架构锁触发**：{msg}。请恢复原有结构！"

SYSTEM_REVERSE_ARCHITECT = """你是一个代码逆向分析专家。
任务：阅读用户提供的代码，提取其核心架构设计。
输出JSON:
{
    "algorithm": "识别出的算法",
    "data_structures": "使用的核心数据结构",
    "headers": "代码中引用的关键头文件",
    "complexity": "当前代码的时空复杂度",
    "blueprint": "代码核心逻辑摘要"
}
"""

SYSTEM_FEASIBILITY_ANALYST = """你是一个算法可行性评估专家。
任务：判断用户代码的【核心算法思路】是否能解决问题。

**判定标准（Tolerance Policy）**：
1. **必须通过 (Pass)**：
   - 算法类型正确且复杂度在可接受范围内。
   - 只要思路对，即使有Bug、格式错误或漏了空行，也**必须判 Pass**。
2. **拒绝 (Fail)**：
   - 算法完全错误（如贪心解动态规划）。
   - 复杂度严重超标（如：N=100时用了 O(2^N) 递归）。

输出JSON:
{
    "pass": true/false,
    "reason": "简述理由。",
    "recommendation": "如果 Fail，推荐改用什么算法（如：'建议改用动态规划'）。"
}
"""


def get_architect_prompt(recommendation=None):
    base = """你是一个高级系统架构师。
任务：设计技术方案。**不要写代码**。
输出JSON: {"algorithm": "...", "data_structures": "...", "headers": "...", "complexity": "...", "blueprint": "..."}"""

    if recommendation:
        return f"{base}\n\n**最高指令**：之前的方案因性能问题被否决。**你必须采纳以下建议**：\n{recommendation}"
    return base


SYSTEM_ARCHITECT_REVIEWER = """你是一个算法设计审查员。
输出JSON: {"pass": true/false, "critique": "..."}
"""


# V10.22: 动态 Coder Prompt，区分工程任务和算法题
def get_coder_prompt(category, design_plan=None, language="cpp"):
    lang_specific = ""
    if language == "python":
        lang_specific = "3. **语言强制**: 必须使用 **Python 3** (if __name__ == '__main__':)。"
    else:
        lang_specific = "3. **语言强制**: 必须使用 **C++** (含main函数, 必须包含必要的头文件)。"

    # 差异化约束
    io_constraint = ""
    if category == "task":
        io_constraint = """
4. **工程交互模式 (Interactive Mode)**：
   - **允许并鼓励**输出友好的提示信息（如 "Press Enter to start", "Game Over"）。
   - 代码应具有良好的模块化结构。
   - 需考虑代码的健壮性和用户体验。
"""
    else:
        io_constraint = """
4. **OJ 洁癖模式 (Silent Mode)**：
   - **严禁**输出任何提示语（如 "请输入N:", "结果是:"）。
   - 只输出题目要求的**纯数据**。
   - 严格遵守输入输出格式，多一个空格都可能导致判题失败。
"""

    base = f"""
**严格约束**：
1. **必须包含详细的中文注释**。
2. **只输出一个** Markdown 代码块。
{lang_specific}
{io_constraint}
"""
    if design_plan:
        return f"""你是一个执行力极强的 ACM/工程选手。
{base}
**最高指令（架构锁）**：
你必须**严格执行**以下架构：
【算法/模块】: {design_plan.get('algorithm', '未指定')}
【数据结构】: {design_plan.get('data_structures', '未指定')}
【步骤/蓝图】: {design_plan.get('blueprint', '未指定')}

**严禁擅自更换核心架构！**
"""
    return f"""你是一个资深工程师。{base} 要求代码健壮。"""


def get_prompts_by_category(category):
    if category == "problem":
        return {
            "REVIEWER": """你是一个 OJ 判题系统。
**必须输出 JSON**。
1. 若 Runner 提示 FAIL，score=0。
2. 若 Runner 提示 PASS，**score 必须 >= 85**。
**所有反馈必须使用中文。**
"""
        }
    return {
        "REVIEWER": """你是一个架构审查员。
**必须输出 JSON**。
如果代码有功能问题，score < 60。
**所有反馈必须使用中文。**
"""
    }


SYSTEM_TEST_EXTRACTOR = """提取题目中的测试样例为JSON列表。
格式: [{"input": "...", "output": "..."}, ...]

**重要原则（Format Consistency）**：
1. **优先提取**：如果有明确样例，只提取提供的。
2. **智能补全**：如果**必须生成**（用户未提供），请生成 3-5 个用例：
   - 包含简单情况（Small Case）。
   - **必须包含边界大值**（Large/Edge Case，如 N=最大值）。
   - 严格遵守题目 IO 格式。
"""

SYSTEM_DEBUGGER = """你是一个算法调试专家。
请分析代码为何未通过测试。
请仔细对比【期望输出】和【实际输出】的差异（如换行符、空格、标点、多余的提示文字）。
**必须使用中文。**
输出JSON: {"analysis": "...", "suggestion": "..."}
"""

# --- V10.22: 双轨审查系统 ---

# 轨道 A: 算法题审计员 (严厉、洁癖、反幻觉)
SYSTEM_AUDITOR_ALGORITHM = """你是一个 ACM 算法竞赛判题官。
**现状：代码已通过测试（功能正确）。**
任务：检查算法规范性。

**审查标准**：
1. **复杂度**：是否满足时间/空间限制？(严禁 O(2^N) 除非 N 很小)。
2. **IO 规范**：是否有多余的输出？（必须纯净输出）。
3. **反幻觉**：只看当前代码，不要复读历史错误。如果代码是循环，严禁说是递归。

输出JSON: {"score": <85-100>, "pass": true, "critique": "..."}
"""

# 轨道 B: 工程项目审计员 (宽容、注重体验、架构)
SYSTEM_AUDITOR_PROJECT = """你是一个资深软件架构师。
**现状：代码已通过测试（或无需测试）。**
任务：检查工程质量和用户体验。

**审查标准**：
1. **用户体验 (UX)**：是否有清晰的提示指引（如 "按回车开始"）？交互是否流畅？
2. **代码结构**：是否模块化（函数/类分离）？变量命名是否语义化？
3. **兼容性**：是否考虑了不同环境的运行（如跨平台输入处理）？
4. **注意**：对于工程/游戏类任务，**允许并鼓励**使用 `input()` 进行交互，**不要求**静默输出。

输出JSON: {"score": <85-100>, "pass": true, "critique": "..."}
"""

SYSTEM_IMPROVER = """你是一个资深技术导师。
代码已经完美通过测试。现在请给出 **锦上添花** 的建议。
输出JSON: {"critique": "Markdown建议"}
"""

SYSTEM_VISUALIZER = """生成 Mermaid JS 流程图 (graph TD)。
1. 节点描述必须使用**中文简述**，不要包含代码符号。
2. 节点ID使用 A, B, C...
输出JSON:
{
    "nodes": [{"id": "A", "text": "开始"}, ...],
    "edges": [{"from": "A", "to": "B", "label": "可选"}, ...]
}
"""


# ==========================================
# 2. 工具函数
# ==========================================

async def call_llm(system_prompt, user_content, json_mode=False, temperature=1.0):
    try:
        response = await client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_content}],
            response_format={"type": "json_object"} if json_mode else {"type": "text"},
            temperature=temperature,
            timeout=60
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f">> LLM Error: {e}")
        return "{}" if json_mode else f"Error: {str(e)}"


async def call_llm_direct(messages, json_mode=False, temperature=1.0):
    try:
        response = await client.chat.completions.create(
            model="deepseek-chat",
            messages=messages,
            response_format={"type": "json_object"} if json_mode else {"type": "text"},
            temperature=temperature,
            timeout=60
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f">> LLM Error: {e}")
        return "{}" if json_mode else f"Error: {str(e)}"


async def call_llm_stream(system_prompt, messages_history, temperature=1.0):
    try:
        full_messages = [{"role": "system", "content": system_prompt}] + messages_history
        stream = await client.chat.completions.create(
            model="deepseek-chat", messages=full_messages, stream=True, temperature=temperature, timeout=60
        )
        full_content = ""
        async for chunk in stream:
            if chunk.choices[0].delta.content:
                content = chunk.choices[0].delta.content
                full_content += content
                yield {"phase": "code_chunk", "content": content}
        yield {"phase": "stream_finished", "full_content": full_content}
    except Exception as e:
        yield {"phase": "log", "content": f"⚠️ 网络中断: {str(e)[:50]}..."}


def clean_json_text(text):
    if not text: return "{}"
    text = re.sub(r"```json", "", text, flags=re.IGNORECASE)
    text = re.sub(r"```", "", text)
    return text.strip()


def detect_language(text):
    if "```python" in text or "def " in text: return "python"
    return "cpp"


def extract_code_content(text):
    pattern = r"```(?:\w+)?\n([\s\S]*?)(?:```|$)"
    matches = re.findall(pattern, text, re.DOTALL)
    if matches:
        valid = [m.strip() for m in matches if len(m.strip()) > 20]
        for m in valid:
            if re.search(r"int\s+main", m): return m
        for m in valid:
            if re.search(r"if\s+__name__", m): return m
        if valid: return valid[-1]

    cpp_match = re.search(r"(#include\s*<|int\s+main\s*\()", text)
    if cpp_match:
        return text[cpp_match.start():].strip()
    py_match = re.search(r"(def\s+solution|if\s+__name__\s*==|import\s+sys)", text)
    if py_match:
        return text[py_match.start():].strip()
    return ""


def detect_code_block(text):
    has_markdown = "```" in text
    has_cpp = bool(re.search(r"(#include|int\s+main\s*\()", text))
    has_py = bool(re.search(r"(def\s+|class\s+|import\s+)", text))
    return has_markdown or has_cpp or has_py


def generate_mermaid_from_json(json_str):
    try:
        data = json.loads(clean_json_text(json_str))
        nodes = data.get("nodes", [])
        edges = data.get("edges", [])
        if not nodes: return "graph TD\nA(暂无数据)"
        mermaid_lines = ["graph TD"]
        for node in nodes:
            nid = node.get("id", "A").replace(" ", "")
            raw_text = node.get("text", "节点")
            safe_text = re.sub(r"[^\u4e00-\u9fa5a-zA-Z0-9]", "", raw_text)
            if not safe_text: safe_text = "操作"
            mermaid_lines.append(f'{nid}("{safe_text}")')
        for edge in edges:
            frm = edge.get("from").replace(" ", "")
            to = edge.get("to").replace(" ", "")
            label = edge.get("label", "")
            if label:
                safe_label = re.sub(r"[^\u4e00-\u9fa5a-zA-Z0-9]", "", label)
                mermaid_lines.append(f'{frm} -- "{safe_label}" --> {to}')
            else:
                mermaid_lines.append(f'{frm} --> {to}')
        return "\n".join(mermaid_lines)
    except Exception as e:
        return "graph TD\nA(图表生成失败)"


def sanitize_json(data, raw_text=""):
    if not isinstance(data, dict):
        return {"score": 0, "pass": False, "critique": f"解析异常: {raw_text[:100]}..."}
    critique = str(data.get("critique", ""))
    if not critique or len(critique) < 5:
        critique = str(data.get("suggestion", "")) or "代码符合规范。"
    return {
        "score": int(data.get("score", 0)),
        "pass": bool(data.get("pass", False)),
        "critique": critique
    }


def validate_test_cases(raw_cases):
    valid_cases = []
    if isinstance(raw_cases, dict):
        for val in raw_cases.values():
            if isinstance(val, list):
                raw_cases = val
                break
    if not isinstance(raw_cases, list): return []
    for item in raw_cases:
        if isinstance(item, str):
            try:
                item = json.loads(item.replace("'", '"'))
            except:
                pass
        if isinstance(item, dict) and "input" in item:
            valid_cases.append(item)
    return valid_cases


def normalize_output(text):
    if not text: return ""
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    lines = [line.rstrip() for line in text.strip().split('\n')]
    return '\n'.join(lines).strip()


def run_code(code_str, language, input_str):
    with tempfile.NamedTemporaryFile(mode='w', suffix=f'.{language.replace("python", "py")}', delete=False,
                                     encoding='utf-8') as tmp:
        tmp.write(code_str)
        tmp_path = tmp.name
    try:
        if language == "python":
            cmd = [sys.executable, tmp_path]
        else:  # cpp
            exe = tmp_path + ".exe"
            compile_res = subprocess.run(
                ["g++", tmp_path, "-o", exe],
                capture_output=True
            )
            if compile_res.returncode != 0:
                err_msg = compile_res.stderr.decode(errors='replace')
                return "", f"Compile Error: {err_msg}"
            cmd = [exe]

        result = subprocess.run(
            cmd,
            input=input_str.encode(),
            capture_output=True,
            timeout=5
        )

        stdout = result.stdout.decode(errors='replace')
        stderr = result.stderr.decode(errors='replace')
        return normalize_output(stdout), normalize_output(stderr)

    except subprocess.TimeoutExpired:
        return "", "Timeout"
    except Exception as e:
        return "", str(e)
    finally:
        try:
            os.remove(tmp_path)
        except:
            pass
        if language == "cpp" and os.path.exists(tmp_path + ".exe"):
            try:
                os.remove(tmp_path + ".exe")
            except:
                pass


# ==========================================
# 3. 核心工作流
# ==========================================

async def workflow_orchestrator(user_task: str):
    def log(msg):
        return {"phase": "log", "content": msg}

    yield log("核心初始化...")

    current_code_raw = ""
    test_cases = []
    chat_history = []
    target_language = "cpp"
    approved_design = None
    previous_score = 0
    pivot_recommendation = None

    # 1. 意图识别
    yield log("分析任务意图...")
    task_category = "task"
    try:
        cls_res = await call_llm(SYSTEM_CLASSIFIER, user_task, json_mode=True)
        cls_data = json.loads(clean_json_text(cls_res))
        task_category = cls_data.get("type", "task")
        target_language = cls_data.get("language", "cpp")

        if detect_code_block(user_task):
            extracted = extract_code_content(user_task)
            if len(extracted) > 20:
                current_code_raw = extracted
                task_category = "code"
                target_language = detect_language(current_code_raw)
                yield log("⚡ 检测到用户代码，进入混合模式...")
    except:
        pass

    yield log(f"模式识别: {task_category.upper()} | 目标语言: {target_language.upper()}")
    STRATEGIES = get_prompts_by_category(task_category)

    # 2. 提取样例
    if task_category != "task":
        try:
            cases_str = await call_llm(SYSTEM_TEST_EXTRACTOR, user_task, json_mode=True)
            raw_cases = json.loads(clean_json_text(cases_str))
            test_cases = validate_test_cases(raw_cases)
            if test_cases: yield log(f"提取到 {len(test_cases)} 个测试样例。")
        except:
            pass

    # 3. 架构设计 (Strategic Pivot)
    if current_code_raw:
        yield log("🔍 分析用户代码架构...")
        try:
            rev_res = await call_llm(SYSTEM_REVERSE_ARCHITECT, current_code_raw, json_mode=True)
            user_design = json.loads(clean_json_text(rev_res))

            yield log("⚖️ 评估算法可行性...")
            feasibility_res = await call_llm(SYSTEM_FEASIBILITY_ANALYST, f"题目:{user_task}\n当前设计:{rev_res}",
                                             json_mode=True)
            feasibility = json.loads(clean_json_text(feasibility_res))

            if feasibility.get("pass"):
                approved_design = user_design
                yield log(f"✅ 思路可行: {user_design.get('algorithm')}")
            else:
                yield log(f"❌ 思路错误: {feasibility.get('reason')}")
                pivot_recommendation = feasibility.get("recommendation")
                yield {
                    "phase": "feasibility_alert",
                    "content": {
                        "reason": feasibility.get("reason"),
                        "recommendation": pivot_recommendation
                    }
                }
                yield log(f"🔄 战略转型: {pivot_recommendation}")
                current_code_raw = ""
        except Exception as e:
            yield log(f"架构分析异常: {e}，尝试直接修复。")

    if (not current_code_raw) and task_category in ["problem", "task"]:
        yield log("📐 正在规划架构方案...")
        try:
            for _ in range(2):
                arch_prompt = get_architect_prompt(pivot_recommendation)
                design_res = await call_llm(arch_prompt, user_task, json_mode=True)

                design_json = json.loads(clean_json_text(design_res))
                review_res = await call_llm(SYSTEM_ARCHITECT_REVIEWER, f"题目:{user_task}\n方案:{design_res}",
                                            json_mode=True)
                review_json = json.loads(clean_json_text(review_res))
                if review_json.get("pass"):
                    approved_design = design_json
                    yield log(f"新架构锁定: {design_json.get('algorithm')}")
                    break
        except:
            pass

    # 4. 代码生成
    if current_code_raw:
        target_language = detect_language(current_code_raw)
        chat_history.append(
            {"role": "user", "content": f"题目/需求如下，包含我的代码:\n{user_task}\n\n请帮我检查并完善代码。"})
        wrapped_code = f"```{target_language}\n{current_code_raw}\n```"
        chat_history.append({"role": "assistant", "content": wrapped_code})
        yield {"phase": "final_code", "content": {"code": wrapped_code}}
        yield log("已装载代码，开始审查...")
    else:
        yield log("🏗️ 构建工程代码...")
        coder_sys_prompt = get_coder_prompt(task_category, approved_design, language=target_language)
        design_str = f"\n【已锁定的架构方案】\n{json.dumps(approved_design, ensure_ascii=False)}" if approved_design else ""
        chat_history.append({"role": "user", "content": f"需求: {user_task}{design_str}"})
        async for packet in call_llm_stream(coder_sys_prompt, chat_history):
            if packet["phase"] == "code_chunk":
                yield packet
            elif packet["phase"] == "stream_finished":
                current_code_raw = packet["full_content"]
                chat_history.append({"role": "assistant", "content": current_code_raw})

    # 5. 循环审查
    max_retries = 4
    final_review = None

    for attempt in range(max_retries + 1):
        round_num = attempt + 1
        current_lang = detect_language(current_code_raw)
        pure_code = extract_code_content(current_code_raw)

        if not pure_code:
            yield log("⚠️ 代码提取失败，重试...")
            chat_history.append({"role": "user", "content": "错误：未检测到代码块。请输出 ```cpp 或 ```python。"})
            yield {"phase": "clear_code", "content": ""}
            async for packet in call_llm_stream(
                    get_coder_prompt(task_category, approved_design, language=target_language), chat_history):
                if packet["phase"] == "code_chunk":
                    yield packet
                elif packet["phase"] == "stream_finished":
                    current_code_raw = packet["full_content"]
                    chat_history.append({"role": "assistant", "content": current_code_raw})
            continue

        yield log(f"执行第 {round_num} 轮测试 ({current_lang})...")

        run_passed = True
        run_report = ""
        if test_cases and current_lang != "unknown" and task_category != "task":
            for idx, case in enumerate(test_cases):
                inp, exp = str(case.get("input", "")), normalize_output(str(case.get("output", "")))
                act, err = run_code(pure_code, current_lang, inp)
                if err:
                    run_passed = False
                    run_report += f"[Case {idx + 1} Error] {err}\n"
                    yield log(f"❌ 样例 {idx + 1} 报错")
                elif act != exp:
                    run_passed = False
                    run_report += f"[Case {idx + 1} Fail]\nExpected:\n{exp[:150]}\nActual:\n{act[:150]}\n"
                    yield log(f"❌ 样例 {idx + 1} 不匹配")
                else:
                    yield log(f"✅ 样例 {idx + 1} 通过")
        else:
            if task_category == "task":
                run_report = "任务模式：跳过自动测试。"
            else:
                run_report = "无测试样例。"

        yield log("🔍 专家审查中...")
        review_json = {}
        try:
            if not run_passed:
                debug_input = f"""代码:
{pure_code}

错误:
{run_report}

需求: {user_task}

【注意】请仔细对比 Expected 和 Actual 的差异（如空格、换行、多余的提示文字）。"""
                debug_resp = await call_llm(SYSTEM_DEBUGGER, debug_input, json_mode=True)
                debug_json = json.loads(clean_json_text(debug_resp))
                review_json = {
                    "pass": False, "score": 40,
                    "critique": f"**故障分析**: {debug_json.get('analysis')}\n\n**修复方案**: {debug_json.get('suggestion')}"
                }
            else:
                design_context = json.dumps(approved_design, ensure_ascii=False) if approved_design else "无（自由发挥）"
                audit_input = f"""
【原始需求】:
{user_task}

【已确认的架构蓝图】:
{design_context}

【待审查代码】:
{pure_code}

请根据上述蓝图和需求，对代码进行规范性审计。
"""
                # V10.22 核心: 审计分流 (Audit Forking)
                selected_auditor = SYSTEM_AUDITOR_PROJECT if task_category == "task" else SYSTEM_AUDITOR_ALGORITHM

                audit_messages = [
                    {"role": "system", "content": selected_auditor},
                    {"role": "user", "content": audit_input}
                ]
                audit_resp = await call_llm_direct(audit_messages, json_mode=True)

                raw_json = json.loads(clean_json_text(audit_resp))
                review_json = sanitize_json(raw_json, raw_text=audit_resp)
                review_json["pass"] = True

                current_score = review_json.get("score", 0)
                if current_score >= 90 and len(review_json.get("critique", "")) < 15: review_json["score"] = 95
                if current_score == previous_score and current_score >= 85: review_json["score"] = 95
                previous_score = current_score
        except Exception as e:
            review_json = {"pass": False, "score": 0, "critique": f"审查异常: {str(e)}"}

        yield {
            "phase": "iteration",
            "data": {"round": round_num, "code": current_code_raw, "review": review_json}
        }

        # 修复逻辑：必须 run_passed 且是首次，才强制打磨
        is_user_first_run = (task_category == 'code' and attempt == 0 and run_passed)

        if review_json["score"] >= 95 and run_passed and not is_user_first_run:
            yield log("代码完美通过。✨")
            final_review = review_json
            break
        else:
            if attempt < max_retries:
                effective_score = 90 if is_user_first_run else review_json['score']
                yield log(f"得分 {effective_score}，触发{'深度打磨' if is_user_first_run else '修正'}...")

                fix_temp = 0.7 if not run_passed else 0.0
                refine_instruction = ""

                if is_user_first_run:
                    refine_instruction = f"代码功能已通过测试。现在请**优化代码风格**：\n1. 规范变量命名。\n2. 添加详细中文注释。\n3. 优化代码结构（保持功能不变）。\n问题参考: {review_json['critique']}"
                else:
                    refine_instruction = f"问题:\n{review_json['critique']}\n\n报告:\n{run_report}\n\n请修改代码。保持使用 {target_language}。"

                if approved_design: refine_instruction += f"\n\n**警报**：严禁更改【{approved_design.get('algorithm')}】算法框架！"

                chat_history.append({"role": "user", "content": refine_instruction})
                yield {"phase": "clear_code", "content": ""}
                async for packet in call_llm_stream(
                        get_coder_prompt(task_category, approved_design, language=target_language), chat_history,
                        temperature=fix_temp):
                    if packet["phase"] == "code_chunk":
                        yield packet
                    elif packet["phase"] == "stream_finished":
                        current_code_raw = packet["full_content"]
                        chat_history.append({"role": "assistant", "content": current_code_raw})
            else:
                yield log("已达最大重试次数。")
                final_review = review_json

    if not run_passed:
        yield log("⚠️ 熔断：代码存在功能性错误。")
        yield {"phase": "final_code_update", "content": {"review": final_review}}
        yield {"phase": "failure_report", "content": {"message": "抱歉，代码多次修复后仍无法通过测试。",
                                                      "issues": run_report + "\n" + final_review.get('critique', '')}}
        yield {"phase": "done", "content": ""}
        return

    yield log("生成进阶建议...")
    try:
        improver_res = await call_llm(SYSTEM_IMPROVER, f"代码:\n{extract_code_content(current_code_raw)}",
                                      json_mode=True)
        improver_json = json.loads(clean_json_text(improver_res))
        final_review["critique"] = improver_json.get("critique", "无建议")
        final_review["score"] = 100
    except:
        pass

    yield {"phase": "final_code_update", "content": {"review": final_review}}

    yield log("生成深度解析报告...")
    final_pure_code = extract_code_content(current_code_raw)

    async def task_viz():
        json_str = await call_llm(SYSTEM_VISUALIZER, f"代码:\n{final_pure_code}", json_mode=True, temperature=0.0)
        return generate_mermaid_from_json(json_str)

    async def task_exp():
        prompt = get_explainer_prompt(task_category)
        return await call_llm(prompt, f"任务:{user_task}\n代码:{current_code_raw}", json_mode=True, temperature=0.4)

    try:
        results = await asyncio.gather(task_viz(), task_exp(), return_exceptions=True)
        viz_res = results[0]
        exp_res_raw = results[1]

        if isinstance(viz_res, Exception):
            yield log(f"Viz Error: {viz_res}")
        else:
            yield {"phase": "diagram", "content": viz_res.strip()}

        if isinstance(exp_res_raw, Exception):
            yield log(f"Exp Error: {exp_res_raw}")
        else:
            try:
                data = json.loads(clean_json_text(exp_res_raw))
                yield {"phase": "explanation", "content": data}
            except Exception as e:
                fallback_data = {
                    "simple": "自动解析结构异常，以下为原始内容：\n\n" + str(exp_res_raw),
                    "academic": "（解析失败）"
                }
                yield {"phase": "explanation", "content": fallback_data}

    except Exception as e:
        yield log(f"Final Report Error: {e}")

    yield log("任务完成。")
    yield {"phase": "done", "content": ""}