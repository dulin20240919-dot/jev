# -*- coding: utf-8 -*-
"""将 round12 Jev 评测语料转换为 round17 混合结构化格式。

输入:
  D:/任务/jev/data/round12/jev_eval_old.jsonl

输出:
  D:/任务/jev/data/round17/jev_eval_old.jsonl

state 格式:
  {
    "judge_instructions": "<人设、判断逻辑和经验组成的完整字符串>",
    "available_tools": [{"name": "...", "description": "..."}],
    "conversation": [{"role": "...", "content": "...", "is_current": true}],
    "selected_tools": ["ToolName"]
  }
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
            '按照 state.judge_instructions 判断：selected_tools 是否完整、准确地满足 '
            'conversation 中用户当前真实诉求？'
        ),
        'criteria': {
            'true': '选中工具完整、准确地满足用户当前所有明确诉求',
            'false': (
                '存在工具不匹配、诉求遗漏、无关或重复调用、更直接候选、'
                '特殊决策工具误用，或上下文不足'
            ),
        },
    }
}


def _normalize_tools(tools):
    """仅保留工具名和描述。"""
    return [
        {
            'name': str(tool.get('name', '')),
            'description': str(tool.get('description', '')),
        }
        for tool in tools
        if isinstance(tool, dict) and tool.get('name')
    ]


def _selected_tool_names(tools):
    """保留选中工具的顺序和重复调用。"""
    return [
        str(tool.get('name'))
        for tool in tools
        if isinstance(tool, dict) and tool.get('name')
    ]


def _pool_tools(old_state):
    """合并选中工具与其余候选，按名称去重。

    被选中的工具始终进入工具池；仅从 other_candidates 中剔除名称以
    Event 结尾的条件工具。
    """
    pool = []
    seen_names = set()

    for tool in old_state.get('tools') or []:
        if not isinstance(tool, dict):
            continue
        name = str(tool.get('name', ''))
        if not name or name in seen_names:
            continue
        pool.append(tool)
        seen_names.add(name)

    for tool in old_state.get('other_candidates') or []:
        if not isinstance(tool, dict):
            continue
        name = str(tool.get('name', ''))
        if not name or name.endswith('Event') or name in seen_names:
            continue
        pool.append(tool)
        seen_names.add(name)

    return pool


def _tool_reply(content):
    """从 tool 消息中提取助手可见文本，取不到时返回“好的”。

    兼容：
      [{"responseText": "..."}]
      [{"toolResult": {...}, "assistantReply": {"text": "..."}}]
    """
    if isinstance(content, (list, dict)):
        parsed = content
    else:
        try:
            parsed = json.loads(content)
        except (TypeError, ValueError):
            return DEFAULT_TOOL_REPLY

    if isinstance(parsed, list):
        items = parsed
    elif isinstance(parsed, dict):
        items = [parsed]
    else:
        items = []

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


def _build_conversation(messages):
    """只保留 user/tool 消息，并标记最后一条 user 为当前输入。"""
    last_user_index = max(
        (
            index
            for index, message in enumerate(messages)
            if isinstance(message, dict) and message.get('role') == 'user'
        ),
        default=-1,
    )

    conversation = []
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

    return conversation


def build_state(old_state):
    """将 round12 state 转为 round17 state。"""
    selected_tools = old_state.get('tools') or []
    return {
        'judge_instructions': JUDGE_INSTRUCTIONS,
        'available_tools': _normalize_tools(_pool_tools(old_state)),
        'conversation': _build_conversation(old_state.get('messages') or []),
        'selected_tools': _selected_tool_names(selected_tools),
    }


def transform(record):
    """转换一条记录，并原样保留 body 外的评估/追溯字段。"""
    old_state = record['body']['state']
    result = {
        'session': {'sessionId': 'testsigma-prompt'},
        'body': {
            'model': 'jev-latest',
            'state': build_state(old_state),
            'questions': QUESTION,
        },
    }
    result.update({
        key: value
        for key, value in record.items()
        if key not in ('session', 'body')
    })
    return result


def _validate(records):
    """返回各类基础格式问题的数量。"""
    invalid_body = 0
    missing_current_user = 0
    missing_selected_tools = 0
    selected_not_in_pool = 0

    for record in records:
        body = record.get('body') or {}
        state = body.get('state') or {}
        if not state or not body.get('questions'):
            invalid_body += 1

        conversation = state.get('conversation') or []
        if not any(
            message.get('role') == 'user' and message.get('is_current')
            for message in conversation
            if isinstance(message, dict)
        ):
            missing_current_user += 1

        selected = state.get('selected_tools') or []
        if not selected:
            missing_selected_tools += 1

        available_names = {
            tool.get('name')
            for tool in state.get('available_tools') or []
            if isinstance(tool, dict)
        }
        if any(name not in available_names for name in selected):
            selected_not_in_pool += 1

    return {
        'invalid_body': invalid_body,
        'missing_current_user': missing_current_user,
        'missing_selected_tools': missing_selected_tools,
        'selected_not_in_pool': selected_not_in_pool,
    }


def main():
    parser = argparse.ArgumentParser(
        description='round12 jsonl -> round17 混合结构化 state jsonl'
    )
    parser.add_argument(
        '--input',
        default=r'D:\任务\jev\data\round12\jev_eval_old.jsonl',
    )
    parser.add_argument(
        '--out',
        default=r'D:\任务\jev\data\round17\jev_eval_old.jsonl',
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

    validation = _validate(output_records)
    print('read %d -> written %d -> %s' % (len(records), len(output_records), args.out))
    print('[校验] state/questions 非空:', validation['invalid_body'] == 0)
    print(
        '[校验] 每条含当前用户输入:',
        validation['missing_current_user'] == 0,
        '(缺失 %d)' % validation['missing_current_user'],
    )
    print(
        '[校验] 每条选中工具非空:',
        validation['missing_selected_tools'] == 0,
        '(缺失 %d)' % validation['missing_selected_tools'],
    )
    print(
        '[校验] 选中工具均在工具池:',
        validation['selected_not_in_pool'] == 0,
        '(异常 %d)' % validation['selected_not_in_pool'],
    )
    print('[校验] label 分布:', dict(Counter(r.get('label') for r in output_records)))


if __name__ == '__main__':
    main()
