# -*- coding: utf-8 -*-
"""把 round12 的 Jev 评测语料改造成 state 为结构化对象的格式。

输入: D:/任务/jev/data/round12/jev_eval_old.jsonl
输出: D:/任务/jev/data/round15/jev_eval_old.jsonl

state 使用“固定规则字符串 + 动态结构化数据”的混合格式：
1. judge_instructions: 人设、判断逻辑和经验组成的完整字符串；
2. available_tools: 结构化可选工具池；
3. conversation: 结构化对话历史；
4. selected_tools: 当前选中工具名列表。
"""
import argparse
import io
import json
import os
import sys
from collections import Counter


if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')


DEFAULT_TOOL_REPLY = '好的'

# ================= state 模板 =================

JUDGE_INSTRUCTIONS = (
    '你是工具选择裁判。你的唯一任务是：结合对话上下文和工具描述，判断 '
    'selected_tools 是否完整、准确地满足用户当前真实诉求。\n'
    '你只判断工具选择，不检查任何参数、槽位、参数值或调用格式，也不推测参数是否正确。'
    '只采用上下文能够明确支持的诉求，禁止脑补隐含需求；不要假设 available_tools '
    '之外还有其他工具。\n\n'
    '### 判断步骤\n'
    '1. 确定当前诉求：结合完整 conversation，判断当前输入是在补充、修正或继续上一轮，'
    '还是已经明确切换到新任务；以用户当前明确要求完成的事情为准。\n'
    '2. 检查诉求覆盖：用户一次可能提出多个独立指令。selected_tools 必须覆盖所有明确指令；'
    '遗漏任意一项、调用无关工具，或重复执行已经完成且未被再次要求的事项，均为不匹配。\n'
    '3. 检查工具能力：只能依据 available_tools 中的 description 判断。工具必须能够实际完成'
    '用户最终诉求；名称相似但能力不同，或只能完成相关步骤，均为不匹配。\n'
    '4. 比较候选工具：如果选中工具只能间接处理，而 available_tools 中存在能够更直接、明确'
    '完成同一诉求的工具，则不匹配。\n'
    '5. 检查特殊决策工具：Confirm、Deny 仅适用于助手正在请求确认，并且用户当前明确表示'
    '同意或拒绝的情况；如果用户转而问候、提出新问题或新要求，则不能使用。Select 仅适用于'
    '助手正在要求从候选项中选择，并且用户通过序号、名称、描述或其他明确方式选中一项；'
    '仅提到某个对象不代表正在选择。\n\n'
    '### 高风险错误信号\n'
    '以下信号只用于重点复核，不能脱离上下文机械判错：\n'
    '- 用户重复表达或纠正同一诉求，但当前工具仍延续先前未解决诉求的理解。\n'
    '- 用户已经明确切换话题或任务，但当前工具仍在处理旧任务。\n'
    '- 用户提出多个指令，而当前工具集合只覆盖其中一部分。\n'
    '- 当前工具与用户诉求属于相近但不同的最终动作，例如路线导航、地点搜索和叫车。\n'
    '- 工具描述只能完成相关操作，不能完成用户真正要求的结果。\n'
    '- 工具池中存在更直接的工具，而当前选择使用了更泛化或更间接的工具。\n\n'
    '### 判定原则\n'
    '只有上述判断全部通过时才判为匹配。任一项不满足，或上下文不足以确认工具适用，'
    '均判为不匹配。'
)

QUESTION = {
    'tool_select_judge': {
        'type': 'noul',
        'instructions': (
            '按照 state.judge_instructions 判断：selected_tools 是否完整、准确地满足'
            'conversation 中用户当前真实诉求？'
        ),
        'criteria': {
            'true': '选中工具完整、准确地满足用户当前所有明确诉求',
            'false': '存在工具不匹配、诉求遗漏、无关或重复调用、更直接候选、特殊决策工具误用，或上下文不足',
        },
    }
}


def _normalize_tools(tools):
    """工具列表 -> 仅含 name、description 的结构化工具列表。"""
    return [
        {
            'name': str(tool.get('name', '')),
            'description': str(tool.get('description', '')),
        }
        for tool in tools
        if isinstance(tool, dict) and tool.get('name')
    ]


def _selected_tool_names(tools):
    """保留选中工具的顺序和重复调用，只移除描述与其他字段。"""
    return [
        str(tool.get('name'))
        for tool in tools
        if isinstance(tool, dict) and tool.get('name')
    ]


def _pool_tools(old_state):
    """合并选中工具和其余候选，过滤条件工具并按工具名去重。"""
    pool = []
    seen_names = set()
    selected_tools = list(old_state.get('tools') or [])
    other_candidates = list(old_state.get('other_candidates') or [])

    # 被选中的工具始终进入工具池。
    for tool in selected_tools:
        if not isinstance(tool, dict):
            continue
        name = str(tool.get('name', ''))
        if not name or name in seen_names:
            continue
        pool.append(tool)
        seen_names.add(name)

    # 只过滤其余候选中的 Event 条件工具。
    for tool in other_candidates:
        if not isinstance(tool, dict):
            continue
        name = str(tool.get('name', ''))
        if not name or name.endswith('Event') or name in seen_names:
            continue
        pool.append(tool)
        seen_names.add(name)
    return pool


def _tool_reply(content):
    """从 tool 消息中提取助手可见回复，取不到时返回默认回复。"""
    if isinstance(content, (list, dict)):
        parsed = content
    else:
        try:
            parsed = json.loads(content)
        except (TypeError, ValueError):
            return DEFAULT_TOOL_REPLY

    items = parsed if isinstance(parsed, list) else [parsed] if isinstance(parsed, dict) else []
    for item in items:
        if not isinstance(item, dict):
            continue
        assistant_reply = item.get('assistantReply') or {}
        if not isinstance(assistant_reply, dict):
            assistant_reply = {}
        for text in (item.get('responseText'), assistant_reply.get('text')):
            if text and str(text).strip():
                return str(text).strip()
    return DEFAULT_TOOL_REPLY


def build_state(old_state):
    """将 round12 的 state dict 转换为新版结构化 state。"""
    conversation = []
    messages = old_state.get('messages') or []
    last_user_index = max(
        (
            index
            for index, message in enumerate(messages)
            if isinstance(message, dict) and message.get('role') == 'user'
        ),
        default=-1,
    )
    for index, message in enumerate(messages):
        if not isinstance(message, dict):
            continue
        role = message.get('role')
        content = message.get('content') or ''
        if role == 'user':
            conversation.append({
                'role': 'user',
                'content': str(content),
                'is_current': index == last_user_index,
            })
        elif role == 'tool':
            conversation.append({
                'role': 'assistant',
                'content': _tool_reply(content),
            })

    return {
        'judge_instructions': JUDGE_INSTRUCTIONS,
        'available_tools': _normalize_tools(_pool_tools(old_state)),
        'conversation': conversation,
        'selected_tools': _selected_tool_names(old_state.get('tools') or []),
    }


def transform(record):
    """将一条 round12 记录转换为新版记录。"""
    old_state = record['body']['state']
    result = {
        'session': {'sessionId': 'testsigma-prompt'},
        'body': {
            'model': 'jev-latest',
            'state': build_state(old_state),
            'questions': QUESTION,
        },
    }

    # 评估/追溯字段原样保留；不存在的可选字段保留为 null。
    required_fields = ('label', 'source', 'case_index', 'query', 'model_output', 'id', 'plan')
    optional_fields = ('sheet', 'domain', 'turn', 'output_type')
    result.update({field: record[field] for field in required_fields})
    result.update({field: record.get(field) for field in optional_fields})
    return result


def main():
    parser = argparse.ArgumentParser(
        description='round12 jsonl -> 新版结构化 state 格式 jsonl'
    )
    parser.add_argument(
        '--input',
        default=r'D:\任务\jev\data\round12\jev_eval_old.jsonl',
    )
    parser.add_argument(
        '--out',
        default=r'D:\任务\jev\data\round15\jev_eval_old.jsonl',
    )
    args = parser.parse_args()

    with open(args.input, encoding='utf-8') as source:
        records = [json.loads(line) for line in source if line.strip()]
    output_records = [transform(record) for record in records]

    output_dir = os.path.dirname(os.path.abspath(args.out))
    os.makedirs(output_dir, exist_ok=True)
    with open(args.out, 'w', encoding='utf-8') as target:
        for record in output_records:
            target.write(json.dumps(record, ensure_ascii=False) + '\n')

    print('read %d -> written %d -> %s' % (len(records), len(output_records), args.out))

    invalid_body = sum(
        1
        for record in output_records
        if not record['body']['state'] or not record['body']['questions']
    )
    missing_current_user = sum(
        1
        for record in output_records
        if not any(
            message.get('role') == 'user' and message.get('is_current')
            for message in record['body']['state'].get('conversation', [])
        )
    )
    missing_selected = sum(
        1
        for record in output_records
        if not record['body']['state'].get('selected_tools')
    )
    print('[校验] state/questions 非空:', invalid_body == 0)
    print(
        '[校验] 每条含当前用户输入:',
        missing_current_user == 0,
        '(缺失 %d)' % missing_current_user,
    )
    print(
        '[校验] 每条选中工具区非空:',
        missing_selected == 0,
        '(缺失 %d)' % missing_selected,
    )
    print('[校验] label 分布:', dict(Counter(r['label'] for r in output_records)))


if __name__ == '__main__':
    main()
