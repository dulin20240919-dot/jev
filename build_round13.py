# -*- coding: utf-8 -*-
"""把 round12 的 Jev 评测语料改造成 state 为单个字符串的格式。

输入: D:/任务/jev/data/round12/jev_eval_old.jsonl
输出: D:/任务/jev/data/round15/jev_eval_old.jsonl

state 由以下部分组成：
1. 裁判职责和判断边界；
2. 可选工具池；
3. 对话历史；
4. 当前选中工具集合；
5. 有固定顺序的判断步骤；
6. 少而精的高风险错误信号；
7. 最终输出原则。
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

STATE_PREFIX = (
    '你是工具选择裁判。你的唯一任务是：结合对话上下文和工具描述，'
    '判断【当前选中工具集合】是否完整、准确地满足用户当前真实诉求。\n'
    '你只判断工具选择，不检查任何参数、槽位、参数值或调用格式，'
    '也不推测参数是否正确。\n\n'
    '### 输入信息\n\n'
    '【可选工具池】\n'
)

STATE_HISTORY_HEADER = '\n【对话历史】\n'

STATE_SELECTED_HEADER = '\n【当前选中工具集合】\n'

STATE_RULES = (
    '\n### 判断步骤\n\n'
    '1. 确定当前诉求\n'
    '结合完整对话判断用户当前明确要求完成的事情。当前输入可能是在补充、'
    '修正或继续上一轮，也可能已经切换到新的话题。只采用上下文能够明确支持的诉求，'
    '禁止脑补隐含需求。\n\n'
    '2. 检查诉求覆盖\n'
    '用户一次可能提出多个独立指令。当前选中工具集合必须覆盖所有明确指令；'
    '遗漏任意一项、调用无关工具或重复执行已经完成且未被再次要求的事项，均为不匹配。\n\n'
    '3. 检查工具能力\n'
    '只能依据工具描述判断能力。只有工具描述能够实际完成用户诉求时，才能判为匹配。'
    '名称相似但能力不同，或工具只能完成相关步骤却不能完成用户最终目标，均为不匹配。\n\n'
    '4. 比较可选工具\n'
    '如果当前工具能够间接处理，但可选工具池中存在能够更直接、明确完成同一诉求的工具，'
    '则当前选择不匹配。不要假设工具池之外还有其他工具。\n\n'
    '5. 检查特殊决策工具\n'
    'Confirm、Deny 仅适用于助手正在请求用户确认，并且用户当前明确表示同意或拒绝的情况。'
    '如果用户没有回应确认问题，而是提出了新问题或新要求，则不能使用 Confirm 或 Deny。\n'
    'Select 仅适用于助手正在要求用户从候选项中选择，并且用户当前通过序号、名称、描述或'
    '其他明确方式选中了某一项。仅仅提到某个对象，不代表正在进行候选选择。\n\n'
    '### 高风险错误信号\n\n'
    '以下现象提示当前工具可能选错，需要重点检查，但不能脱离上下文机械判错：\n'
    '- 用户重复表达或纠正同一诉求，而助手仍沿用先前未解决该诉求的理解，'
    '说明当前工具可能延续了错误判断。\n'
    '- 用户已经明确切换话题或任务，但当前工具仍在处理之前的话题。\n'
    '- 用户提出多个指令，当前工具集合只完成其中一部分。\n'
    '- 当前工具与用户诉求属于相近但不同的任务，例如路线导航、地点搜索和叫车；'
    '必须以用户最终要完成的动作区分，不能因对象相同而混用。\n'
    '- 当前工具描述只能完成相关操作，不能完成用户真正要求的结果。\n'
    '- 可选工具池中存在更直接完成诉求的工具，而当前选择使用了更泛化或更间接的工具。\n\n'
    '### 输出原则\n\n'
    '满足以下全部条件才判为匹配：\n'
    '- 当前用户诉求能够从上下文中明确确定；\n'
    '- 每个明确诉求都有对应工具；\n'
    '- 每个选中工具的描述确实能完成对应诉求；\n'
    '- 没有无关、重复或沿用旧话题的调用；\n'
    '- 没有被可选工具池中更直接的工具替代；\n'
    '- Confirm、Deny、Select 等特殊工具满足其对话条件。\n'
    '任意一项不满足，或上下文不足以确认工具适用，均判为不匹配。'
)

QUESTION = {
    'tool_select_judge': {
        'type': 'noul',
        'instructions': '判断当前选中工具集合是否完整、准确地满足用户当前真实诉求。',
        'criteria': {
            'true': (
                '所有明确诉求均被合适工具完整覆盖，且不存在无关、重复、'
                '错误延续或可被更直接候选替代的工具。'
            ),
            'false': (
                '工具能力不匹配、存在更直接候选、遗漏部分诉求、调用无关或重复工具、'
                '错误沿用旧话题、特殊决策工具使用条件不成立，或上下文不足以确认适用。'
            ),
        },
    }
}


def _fmt_tools(tools):
    """工具列表 -> “工具名:描述”，以“;\\n”连接。"""
    return ';\n'.join(
        '%s:%s' % (t.get('name', ''), t.get('description', ''))
        for t in tools
        if isinstance(t, dict) and t.get('name')
    )


def _pool_tools(old_state):
    """合并选中工具和其余候选，过滤条件工具并按工具名去重。"""
    pool = []
    seen_names = set()
    candidates = list(old_state.get('tools') or [])
    candidates.extend(old_state.get('other_candidates') or [])

    for tool in candidates:
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
    """将 round12 的 state dict 拼成新版 state 字符串。"""
    sections = [STATE_PREFIX + _fmt_tools(_pool_tools(old_state))]

    history_lines = []
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
            prefix = '用户（当前用户输入）：' if index == last_user_index else '用户：'
            history_lines.append(prefix + str(content))
        elif role == 'tool':
            history_lines.append('助手：' + _tool_reply(content))

    sections.append(STATE_HISTORY_HEADER + '\n'.join(history_lines))
    sections.append(
        STATE_SELECTED_HEADER + _fmt_tools(old_state.get('tools') or [])
    )
    sections.append(STATE_RULES)
    return '\n'.join(sections)


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


def _selected_section(state):
    """提取 state 中的选中工具区，用于快速校验。"""
    try:
        return state.split(STATE_SELECTED_HEADER, 1)[1].split('\n### 判断步骤', 1)[0].strip()
    except IndexError:
        return ''


def main():
    parser = argparse.ArgumentParser(
        description='round12 jsonl -> 新版 state 字符串格式 jsonl'
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
        if '用户（当前用户输入）' not in record['body']['state']
    )
    missing_selected = sum(
        1
        for record in output_records
        if not _selected_section(record['body']['state'])
    )
    print('[校验] state/questions 非空:', invalid_body == 0)
    print(
        '[校验] 每条含“用户（当前用户输入）”:',
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
